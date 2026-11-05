import json
import uuid
from pathlib import Path
from typing import Any

from app.dm.base import DungeonMaster
from app.memory import Memory
from app.models import (
    Character,
    DmContext,
    Session,
    SessionView,
    StateChange,
    TurnResult,
)
from app.repo import Repo
from app.rules.checks import ability_check
from app.rules.combat import attack
from app.rules.dice import Rng
from app.scenario import Scenario, Scene

MAX_DM_CHANGE_AMOUNT = 30
VALID_DISPOSITIONS = {"hostile", "wary", "neutral", "friendly"}


class _LiveSession:
    def __init__(self, session: Session, scenario: Scenario, memory: Memory) -> None:
        self.session = session
        self.scenario = scenario
        self.memory = memory
        self.enemies: dict[str, Character] = {}
        self.log: list[dict[str, str]] = []
        self.load_scene_enemies()

    def load_scene_enemies(self) -> None:
        self.enemies = {
            e.id: e.model_copy(deep=True) for e in self.scenario.current_scene().enemies
        }


class Orchestrator:
    def __init__(
        self,
        dm: DungeonMaster,
        repo: Repo,
        scenarios_dir: Path,
        rng: Rng | None = None,
    ) -> None:
        self.dm = dm
        self.repo = repo
        self.scenarios_dir = Path(scenarios_dir)
        self.rng = rng or Rng()
        self._scenario_ids: dict[str, Path] = {}
        for path in sorted(self.scenarios_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self._scenario_ids[data["id"]] = path
        self._live: dict[str, _LiveSession] = {}

    def list_scenarios(self) -> list[dict[str, str]]:
        result = []
        for scenario_id, path in sorted(self._scenario_ids.items()):
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append(
                {"id": scenario_id, "title": data["title"], "premise": data["premise"]}
            )
        return result

    def start_session(self, scenario_id: str, character: Character) -> SessionView:
        if scenario_id not in self._scenario_ids:
            raise ValueError(f"unknown scenario: {scenario_id}")
        scenario = Scenario.load(self._scenario_ids[scenario_id])
        session = Session(
            id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            scene_id=scenario.current_scene().id,
            character=character,
        )
        memory = Memory(session.id)
        self._live[session.id] = _LiveSession(session, scenario, memory)
        self.repo.create_session(session.id, scenario_id, session.scene_id, character)
        return self.get_state(session.id)

    def get_state(self, session_id: str) -> SessionView:
        live = self._get_live(session_id)
        return SessionView(
            session=live.session,
            scene=self._scene_payload(live, for_dm=False),
            facts=[f.text for f in live.memory.recall()],
            log=list(live.log),
        )

    def ask_dm(self, session_id: str, text: str) -> str:
        live = self._get_live(session_id)
        ctx = DmContext(
            premise=live.scenario.premise,
            scene=self._scene_payload(live, for_dm=True),
            player_action=text,
            facts=[f.text for f in live.memory.recall()],
            outcomes=[],
            recent_turns=live.log[-3:],
            character=live.session.character.model_dump(),
        )
        return self.dm.answer_question(ctx)

    def submit_action(self, session_id: str, text: str) -> TurnResult:
        live = self._get_live(session_id)
        character = live.session.character
        scene = live.scenario.current_scene()

        intent = self.dm.classify_intent(text, scene)
        outcomes: list[dict[str, Any]] = []

        if intent.kind == "check" and intent.skill:
            scene_check = live.scenario.check_for_skill(intent.skill)
            if scene_check is not None:
                result = ability_check(character, scene_check.skill, scene_check.dc, self.rng)
                outcome = result.model_dump()
                outcome["kind"] = "check"
                outcome["grants_fact"] = scene_check.grants_fact
                outcomes.append(outcome)
                if result.success and scene_check.grants_fact:
                    self._record_fact(live, scene_check.grants_fact, source="check")

        if intent.kind == "attack":
            target = next((e for e in live.enemies.values() if e.hp > 0), None)
            if target is not None:
                result = attack(character, target, self.rng)
                target.hp = result.target_hp_after
                outcome = result.model_dump()
                outcome["kind"] = "attack"
                outcome["target_name"] = target.name
                outcomes.append(outcome)
                if target.hp > 0:
                    counter = attack(target, character, self.rng)
                    character.hp = counter.target_hp_after
                    counter_outcome = counter.model_dump()
                    counter_outcome["kind"] = "counterattack"
                    counter_outcome["attacker_name"] = target.name
                    outcomes.append(counter_outcome)
                if all(e.hp <= 0 for e in live.enemies.values()) and scene.combat_reward_fact:
                    outcome["combat_won_fact"] = scene.combat_reward_fact
                    self._record_fact(live, scene.combat_reward_fact, source="combat")

        ctx = DmContext(
            premise=live.scenario.premise,
            scene=self._scene_payload(live, for_dm=True),
            player_action=text,
            facts=[f.text for f in live.memory.recall()],
            outcomes=outcomes,
            recent_turns=live.log[-3:],
            character=character.model_dump(),
        )
        response = self.dm.narrate(ctx)

        applied, discarded = self._apply_state_changes(live, response.state_changes)

        scene_changed = False
        scene_on_enter: str | None = None
        exits = live.scenario.available_exits()
        trigger = response.scene_trigger
        if not (trigger and any(e.trigger == trigger for e in exits)):
            facts = {f.text for f in live.memory.recall()}
            trigger = next((e.trigger for e in exits if e.trigger in facts), None)
        if trigger:
            old_scene = live.scenario.current_scene()
            live.memory.summarize_scene(
                old_scene.id, f"Сцена «{old_scene.title or old_scene.id}» завершена."
            )
            new_scene = live.scenario.advance(trigger)
            if new_scene is not None:
                scene_changed = True
                scene_on_enter = new_scene.on_enter
                live.session.scene_id = new_scene.id
                live.load_scene_enemies()
                self.repo.update_session_scene(live.session.id, new_scene.id)

        live.session.turn_count += 1
        live.log.append({"player": text, "dm": response.narration})

        result = TurnResult(
            narration=response.narration,
            npc_lines=response.npc_lines,
            rolls=outcomes,
            applied_changes=applied,
            discarded_changes=discarded,
            scene_id=live.session.scene_id,
            scene_changed=scene_changed,
            scene_on_enter=scene_on_enter,
            character=character,
            facts=[f.text for f in live.memory.recall()],
        )
        self.repo.save_turn(
            session_id, live.session.turn_count, text, result.model_dump_json()
        )
        self.repo.update_session_character(session_id, character)
        return result

    def _get_live(self, session_id: str) -> _LiveSession:
        live = self._live.get(session_id)
        if live is None:
            raise KeyError(f"unknown session: {session_id}")
        return live

    def _scene_payload(self, live: _LiveSession, for_dm: bool) -> dict[str, Any]:
        scene = live.scenario.current_scene().model_dump()
        met = {
            f.text.removeprefix("met_npc:")
            for f in live.memory.recall()
            if f.text.startswith("met_npc:")
        }
        for npc in scene["npcs"]:
            known = npc["id"] in met
            if for_dm:
                npc["known"] = known
            else:
                npc.pop("secrets", None)
                npc.pop("personality", None)
                if not known:
                    npc["name"] = npc["label"]
        for enemy in scene["enemies"]:
            live_enemy = live.enemies.get(enemy["id"])
            if live_enemy is not None:
                enemy["hp"] = live_enemy.hp
        return scene

    def _record_fact(self, live: _LiveSession, text: str, source: str) -> None:
        if live.memory.has(text):
            return
        fact = live.memory.add(
            text, source=source, scene_id=live.session.scene_id
        )
        self.repo.add_fact(live.session.id, fact)

    def _apply_state_changes(
        self, live: _LiveSession, changes: list[StateChange]
    ) -> tuple[list[StateChange], list[StateChange]]:
        applied: list[StateChange] = []
        discarded: list[StateChange] = []
        character = live.session.character
        scene: Scene = live.scenario.current_scene()
        npc_ids = {npc.id for npc in scene.npcs}

        for change in changes:
            if not self._is_valid(change, live, character, npc_ids):
                discarded.append(change)
                continue
            applied.append(change)
            if change.type == "grant_fact":
                self._record_fact(live, change.fact or "", source="dm")
            elif change.type == "remove_fact":
                live.memory.remove(change.fact or "")
            elif change.type == "damage":
                character.hp = max(0, character.hp - (change.amount or 0))
            elif change.type == "heal":
                character.hp = min(character.max_hp, character.hp + (change.amount or 0))
            elif change.type == "add_item":
                if change.item not in character.inventory:
                    character.inventory.append(change.item or "")
            elif change.type == "remove_item":
                if change.item in character.inventory:
                    character.inventory.remove(change.item)
            elif change.type == "set_npc_disposition":
                self._record_fact(
                    live, f"npc_disposition:{change.npc_id}:{change.disposition}", source="dm"
                )
            elif change.type == "meet_npc":
                self._record_fact(live, f"met_npc:{change.npc_id}", source="dm")
        return applied, discarded

    @staticmethod
    def _is_valid(
        change: StateChange,
        live: _LiveSession,
        character: Character,
        npc_ids: set[str],
    ) -> bool:
        if change.type == "grant_fact":
            return bool(change.fact and change.fact.strip())
        if change.type == "remove_fact":
            return bool(change.fact) and live.memory.has(change.fact or "")
        if change.type in ("damage", "heal"):
            return (
                change.target == "player"
                and change.amount is not None
                and 1 <= change.amount <= MAX_DM_CHANGE_AMOUNT
            )
        if change.type == "add_item":
            return bool(change.item and change.item.strip())
        if change.type == "remove_item":
            return bool(change.item) and (change.item or "") in character.inventory
        if change.type == "set_npc_disposition":
            return (
                change.npc_id in npc_ids
                and (change.disposition or "") in VALID_DISPOSITIONS
            )
        if change.type == "meet_npc":
            return change.npc_id in npc_ids
        return False

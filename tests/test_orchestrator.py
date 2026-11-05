from pathlib import Path

import pytest

from app.dm.scripted import ScriptedDM
from app.models import DmResponse, StateChange, build_character
from app.orchestrator import Orchestrator
from app.repo import Repo
from app.rules.dice import Rng

BASE = Path(__file__).resolve().parent.parent


@pytest.fixture()
def orchestrator(tmp_path) -> Orchestrator:
    repo = Repo(tmp_path / "test.db")
    return Orchestrator(
        dm=ScriptedDM(),
        repo=repo,
        scenarios_dir=BASE / "scenarios",
        rng=Rng(seed=11),
    )


@pytest.fixture()
def session_id(orchestrator) -> str:
    character = build_character("Тест", "fighter")
    view = orchestrator.start_session("curse-of-the-salted-goat", character)
    return view.session.id


def test_start_session(orchestrator, session_id):
    view = orchestrator.get_state(session_id)
    assert view.session.scenario_id == "curse-of-the-salted-goat"
    assert view.scene["id"] == "tavern"
    assert view.session.character.char_class == "fighter"


def test_full_turn_with_skill_check(orchestrator, session_id):
    result = orchestrator.submit_action(session_id, "Уговариваю старосту выдать контракт")
    assert result.narration
    check_rolls = [r for r in result.rolls if r.get("kind") == "check"]
    assert len(check_rolls) == 1
    assert check_rolls[0]["skill"] == "persuasion"
    # fighter cha 8 -> -1, no proficiency; dc 12, seed 11 d20 = 16 -> total 15, success
    assert check_rolls[0]["success"]
    assert "has_contract" in result.facts
    # ScriptedDM routes the granted fact into a scene trigger
    assert result.scene_changed
    assert result.scene_id == "docks"

    persisted_facts = orchestrator.repo.list_facts(session_id)
    assert "has_contract" in persisted_facts
    turns = orchestrator.repo.list_turns(session_id)
    assert len(turns) == 1


def test_free_action_has_no_rolls(orchestrator, session_id):
    result = orchestrator.submit_action(session_id, "Заказываю эль и слушаю шторм")
    assert result.narration
    assert result.rolls == []
    assert not result.scene_changed
    assert result.scene_id == "tavern"


def test_invalid_state_changes_are_discarded(orchestrator, session_id, monkeypatch):
    def narrate_with_garbage(ctx):
        return DmResponse(
            narration="Мастер пытается сжульничать.",
            state_changes=[
                StateChange(type="destroy_world"),
                StateChange(type="damage", target="player", amount=9999),
                StateChange(type="set_npc_disposition", npc_id="ghost", disposition="friendly"),
                StateChange(type="grant_fact", fact="dm_granted_hint"),
            ],
        )

    monkeypatch.setattr(orchestrator.dm, "narrate", narrate_with_garbage)
    result = orchestrator.submit_action(session_id, "Слушаю старосту")

    assert [c.type for c in result.applied_changes] == ["grant_fact"]
    assert "dm_granted_hint" in result.facts
    assert [c.type for c in result.discarded_changes] == [
        "destroy_world",
        "damage",
        "set_npc_disposition",
    ]
    assert result.character.hp == result.character.max_hp


def test_damage_and_heal_validation_bounds(orchestrator, session_id, monkeypatch):
    def narrate(ctx):
        return DmResponse(
            narration="Ловушка!",
            state_changes=[
                StateChange(type="damage", target="player", amount=4),
                StateChange(type="heal", target="player", amount=2),
                StateChange(type="add_item", item="ржавый ключ"),
                StateChange(type="remove_item", item="несуществующий предмет"),
            ],
        )

    monkeypatch.setattr(orchestrator.dm, "narrate", narrate)
    result = orchestrator.submit_action(session_id, "Иду вперёд")
    hp = result.character.max_hp
    assert result.character.hp == hp - 4 + 2
    assert "ржавый ключ" in result.character.inventory
    assert [c.type for c in result.discarded_changes] == ["remove_item"]


def test_combat_turn_in_warehouse(orchestrator, session_id):
    # walk to the warehouse through scripted checks (seed 11 d20 = 16 for both)
    orchestrator.submit_action(session_id, "Уговариваю старосту выдать контракт")
    orchestrator.submit_action(session_id, "Обыскиваю пирс в поисках следов соли")
    state = orchestrator.get_state(session_id)
    assert state.scene["id"] == "warehouse"
    assert len(state.scene["enemies"]) == 2

    result = orchestrator.submit_action(session_id, "Атакую ближайшего громилу мечом")
    attack_rolls = [r for r in result.rolls if r.get("kind") == "attack"]
    assert len(attack_rolls) == 1
    assert attack_rolls[0]["target_name"].startswith("Громила")
    if attack_rolls[0]["hit"]:
        live_enemy = next(
            e for e in orchestrator.get_state(session_id).scene["enemies"]
            if e["id"] == attack_rolls[0]["target_id"]
        )
        assert live_enemy["hp"] == attack_rolls[0]["target_hp_after"]


def test_ask_dm_is_out_of_game(orchestrator, session_id):
    before = orchestrator.get_state(session_id)
    answer = orchestrator.ask_dm(session_id, "Сколько у меня хп?")
    assert "HP" in answer
    after = orchestrator.get_state(session_id)
    assert after.session.turn_count == before.session.turn_count == 0
    assert after.log == before.log == []
    assert after.facts == before.facts


def test_ask_dm_unknown_session(orchestrator):
    with pytest.raises(KeyError):
        orchestrator.ask_dm("no-such-session", "вопрос")


def test_npc_names_hidden_until_met(orchestrator, session_id, monkeypatch):
    view = orchestrator.get_state(session_id)
    npcs = {n["id"]: n for n in view.scene["npcs"]}
    assert npcs["mayor"]["name"] == "Коренастый мужчина у окна"
    assert npcs["innkeeper"]["name"] == "Пышная женщина за стойкой"
    assert "secrets" not in npcs["mayor"]

    captured = {}

    def narrate(ctx):
        captured["ctx"] = ctx
        return DmResponse(
            narration="Мужчина протягивает руку: «Бранн. Староста здешний».",
            state_changes=[
                StateChange(type="meet_npc", npc_id="mayor"),
                StateChange(type="meet_npc", npc_id="ghost"),
            ],
        )

    monkeypatch.setattr(orchestrator.dm, "narrate", narrate)
    result = orchestrator.submit_action(session_id, "Спрашиваю, как его зовут")

    dm_npcs = {n["id"]: n for n in captured["ctx"].scene["npcs"]}
    assert dm_npcs["mayor"]["known"] is False
    assert [c.npc_id for c in result.applied_changes] == ["mayor"]
    assert [c.npc_id for c in result.discarded_changes] == ["ghost"]

    view = orchestrator.get_state(session_id)
    npcs = {n["id"]: n for n in view.scene["npcs"]}
    assert npcs["mayor"]["name"] == "Староста Бранн"
    assert npcs["innkeeper"]["name"] == "Пышная женщина за стойкой"


def test_dm_receives_current_player_action(orchestrator, session_id, monkeypatch):
    captured = {}
    original = orchestrator.dm.narrate

    def narrate(ctx):
        captured["ctx"] = ctx
        return original(ctx)

    monkeypatch.setattr(orchestrator.dm, "narrate", narrate)
    orchestrator.submit_action(session_id, "Заказываю эль и слушаю шторм")
    assert captured["ctx"].player_action == "Заказываю эль и слушаю шторм"
    # лог на момент вызова DM ещё не содержит текущий ход — иначе ответы отстают
    assert all(t["player"] != "Заказываю эль и слушаю шторм" for t in captured["ctx"].recent_turns)


def test_scene_advances_without_dm_trigger(orchestrator, session_id, monkeypatch):
    # DM narrates but forgets scene_trigger; engine-granted fact must drive the exit
    monkeypatch.setattr(
        orchestrator.dm,
        "narrate",
        lambda ctx: DmResponse(narration="Староста сдаётся и подписывает контракт."),
    )
    result = orchestrator.submit_action(session_id, "Уговариваю старосту выдать контракт")
    assert "has_contract" in result.facts
    assert result.scene_changed
    assert result.scene_id == "docks"


def test_unknown_session_raises(orchestrator):
    with pytest.raises(KeyError):
        orchestrator.submit_action("no-such-session", "привет")

from app.dm.base import DungeonMaster
from app.models import DmContext, DmResponse, Intent, NpcLine, StateChange
from app.scenario import Scene

ATTACK_KEYWORDS = ("атак", "удар", "бью", "рублю", "стреля", "заклинанием в", "attack", "hit")

SKILL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "persuasion": ("убед", "уговор", "уговар", "договор", "persuad"),
    "intimidation": ("припуг", "запуг", "угрож", "intimidat"),
    "deception": ("обман", "солг", "вру", "bluff", "deceiv"),
    "investigation": ("обыск", "осмотр", "исслед", "изуч", "ищу", "investig", "search"),
    "perception": ("прислуш", "перекинуться", "вгляд", "осматриваюсь", "percep", "listen"),
    "stealth": ("подкрад", "тихо", "спрят", "незамет", "stealth", "sneak"),
    "athletics": ("выбить", "забраться", "прыг", "толкаю", "ломаю", "athletic", "climb"),
    "insight": ("понять", "чувству", "insight"),
    "arcana": ("маги", "arcana"),
    "sleight_of_hand": ("незаметно взять", "карман", "sleight"),
    "acrobatics": ("кувыр", "увернуться", "acrobat"),
    "history": ("вспомнить историю", "history"),
    "religion": ("молитв", "religion"),
    "nature": ("природ", "nature"),
    "survival": ("след", "выжив", "survival"),
    "medicine": ("перевяз", "медицин", "medicine"),
    "animal_handling": ("животн", "animal"),
    "performance": ("выступ", "performance"),
}


class ScriptedDM(DungeonMaster):
    """Deterministic fake DM for tests and development without an API key."""

    def classify_intent(self, text: str, scene: Scene) -> Intent:
        lowered = text.lower()
        living_enemies = [e for e in scene.enemies if e.hp > 0]
        if living_enemies and any(word in lowered for word in ATTACK_KEYWORDS):
            return Intent(kind="attack", reason="attack keyword with living enemies")
        for check in scene.checks:
            for word in SKILL_KEYWORDS.get(check.skill, (check.skill,)):
                if word in lowered:
                    return Intent(kind="check", skill=check.skill, reason="skill keyword")
        return Intent(kind="free", reason="no keywords matched")

    def narrate(self, ctx: DmContext) -> DmResponse:
        parts: list[str] = []
        changes: list[StateChange] = []
        scene_trigger: str | None = None
        exit_triggers = {e["trigger"] for e in ctx.scene.get("exits", [])}

        for outcome in ctx.outcomes:
            kind = outcome.get("kind")
            if kind == "check":
                total, dc = outcome["total"], outcome["dc"]
                if outcome["success"]:
                    parts.append(f"Проверка {outcome['skill']}: {total} против СЛ {dc} — успех.")
                    fact = outcome.get("grants_fact")
                    if fact:
                        changes.append(StateChange(type="grant_fact", fact=fact))
                        if fact in exit_triggers:
                            scene_trigger = fact
                else:
                    parts.append(f"Проверка {outcome['skill']}: {total} против СЛ {dc} — провал.")
            elif kind == "attack":
                if outcome["hit"]:
                    parts.append(
                        f"Атака попадает ({outcome['total']} против КД {outcome['target_ac']}),"
                        f" урон {outcome['damage']}."
                    )
                else:
                    parts.append(
                        f"Атака не попадает ({outcome['total']} против КД {outcome['target_ac']})."
                    )
                if outcome.get("combat_won_fact"):
                    fact = outcome["combat_won_fact"]
                    parts.append("Последний враг падает.")
                    changes.append(StateChange(type="grant_fact", fact=fact))
                    if fact in exit_triggers:
                        scene_trigger = fact

        if not parts:
            parts.append("Мастер кивает, вплетая действие в ткань истории.")

        npc_lines: list[NpcLine] = []
        npcs = ctx.scene.get("npcs", [])
        if npcs:
            npc_lines.append(NpcLine(npc_id=npcs[0]["id"], line="Хм. Посмотрим, что из этого выйдет."))

        return DmResponse(
            narration=" ".join(parts),
            npc_lines=npc_lines,
            state_changes=changes,
            scene_trigger=scene_trigger,
        )

    def answer_question(self, ctx: DmContext) -> str:
        hp = ctx.character.get("hp"), ctx.character.get("max_hp")
        goal = ctx.scene.get("goal") or "нет"
        facts = ", ".join(ctx.facts) if ctx.facts else "пока нет"
        return (
            f"(Вне игры) HP персонажа: {hp[0]}/{hp[1]}. Цель сцены: {goal}. "
            f"Известные факты: {facts}."
        )

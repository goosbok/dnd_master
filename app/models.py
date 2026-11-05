import json
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRD_CLASSES_PATH = PROJECT_ROOT / "data" / "srd" / "classes.json"


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


class Character(BaseModel):
    id: str
    name: str
    char_class: str
    level: int = 1
    abilities: dict[str, int]
    hp: int
    max_hp: int
    ac: int
    proficiency_bonus: int = 2
    skills: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    attack_bonus: int = 0
    damage_die: int = 6
    damage_bonus: int = 0

    def modifier(self, ability: str) -> int:
        return ability_modifier(self.abilities[ability])

    def is_proficient(self, skill: str) -> bool:
        return skill in self.skills

    @property
    def is_alive(self) -> bool:
        return self.hp > 0


def build_character(
    name: str,
    char_class: str,
    srd_path: Path = SRD_CLASSES_PATH,
) -> Character:
    classes = json.loads(srd_path.read_text(encoding="utf-8"))
    template = classes.get(char_class)
    if template is None:
        raise ValueError(f"unknown class: {char_class}")
    return Character(id=str(uuid.uuid4()), name=name, char_class=char_class, **template)


class Fact(BaseModel):
    id: str
    text: str
    source: str = "engine"
    scene_id: str | None = None


class Intent(BaseModel):
    kind: Literal["free", "check", "attack"] = "free"
    skill: str | None = None
    reason: str = ""


class NpcLine(BaseModel):
    npc_id: str
    line: str


class StateChange(BaseModel):
    type: str
    fact: str | None = None
    item: str | None = None
    target: str | None = None
    amount: int | None = None
    npc_id: str | None = None
    disposition: str | None = None


class DmContext(BaseModel):
    premise: str
    scene: dict[str, Any]
    player_action: str = ""
    facts: list[str]
    outcomes: list[dict[str, Any]] = Field(default_factory=list)
    recent_turns: list[dict[str, str]] = Field(default_factory=list)
    character: dict[str, Any]


class DmResponse(BaseModel):
    narration: str
    npc_lines: list[NpcLine] = Field(default_factory=list)
    state_changes: list[StateChange] = Field(default_factory=list)
    scene_trigger: str | None = None


class TurnResult(BaseModel):
    narration: str
    npc_lines: list[NpcLine] = Field(default_factory=list)
    rolls: list[dict[str, Any]] = Field(default_factory=list)
    applied_changes: list[StateChange] = Field(default_factory=list)
    discarded_changes: list[StateChange] = Field(default_factory=list)
    scene_id: str
    scene_changed: bool = False
    scene_on_enter: str | None = None
    character: Character
    facts: list[str] = Field(default_factory=list)


class Session(BaseModel):
    id: str
    scenario_id: str
    scene_id: str
    character: Character
    turn_count: int = 0


class SessionView(BaseModel):
    session: Session
    scene: dict[str, Any]
    facts: list[str] = Field(default_factory=list)
    log: list[dict[str, str]] = Field(default_factory=list)

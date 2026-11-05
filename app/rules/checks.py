import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.models import Character, ability_modifier
from app.rules.dice import Rng

SKILLS_PATH = Path(__file__).resolve().parents[2] / "data" / "srd" / "skills.json"


@lru_cache(maxsize=1)
def _skill_abilities() -> dict[str, str]:
    data = json.loads(SKILLS_PATH.read_text(encoding="utf-8"))
    return {entry["id"]: entry["ability"] for entry in data}


def skill_ability(skill: str) -> str:
    abilities = _skill_abilities()
    if skill not in abilities:
        raise ValueError(f"unknown skill: {skill}")
    return abilities[skill]


class CheckResult(BaseModel):
    skill: str
    ability: str
    roll: int
    modifier: int
    total: int
    dc: int
    success: bool
    critical: bool


def ability_check(char: Character, skill: str, dc: int, rng: Rng) -> CheckResult:
    ability = skill_ability(skill)
    modifier = char.modifier(ability)
    if char.is_proficient(skill):
        modifier += char.proficiency_bonus
    roll = rng.roll_d20()
    total = roll + modifier
    critical = roll == 20
    success = critical or (roll != 1 and total >= dc)
    return CheckResult(
        skill=skill,
        ability=ability,
        roll=roll,
        modifier=modifier,
        total=total,
        dc=dc,
        success=success,
        critical=critical,
    )

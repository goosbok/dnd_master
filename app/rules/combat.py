from typing import Literal

from pydantic import BaseModel, Field

from app.models import Character
from app.rules.dice import Rng


class Combatant(BaseModel):
    id: str
    name: str
    hp: int
    max_hp: int
    ac: int
    attack_bonus: int
    damage_die: int
    damage_bonus: int = 0
    dex: int = 10
    is_enemy: bool = False

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @classmethod
    def from_character(cls, char: Character, is_enemy: bool = False) -> "Combatant":
        return cls(
            id=char.id,
            name=char.name,
            hp=char.hp,
            max_hp=char.max_hp,
            ac=char.ac,
            attack_bonus=char.attack_bonus,
            damage_die=char.damage_die,
            damage_bonus=char.damage_bonus,
            dex=char.abilities.get("dex", 10),
            is_enemy=is_enemy,
        )


class AttackResult(BaseModel):
    attacker_id: str
    target_id: str
    roll: int
    attack_bonus: int
    total: int
    target_ac: int
    hit: bool
    critical: bool
    damage: int
    target_hp_after: int
    target_dead: bool


def attack(attacker: Character | Combatant, target: Character | Combatant, rng: Rng) -> AttackResult:
    roll = rng.roll_d20()
    total = roll + attacker.attack_bonus
    critical = roll == 20
    hit = critical or (roll != 1 and total >= target.ac)
    damage = 0
    if hit:
        dice = 2 if critical else 1
        damage = max(1, sum(rng.roll(attacker.damage_die) for _ in range(dice)) + attacker.damage_bonus)
    hp_after = max(0, target.hp - damage)
    return AttackResult(
        attacker_id=attacker.id,
        target_id=target.id,
        roll=roll,
        attack_bonus=attacker.attack_bonus,
        total=total,
        target_ac=target.ac,
        hit=hit,
        critical=critical,
        damage=damage,
        target_hp_after=hp_after,
        target_dead=hp_after == 0,
    )


class CombatState(BaseModel):
    combatants: dict[str, Combatant]
    order: list[str]
    initiatives: dict[str, int]
    turn_index: int = 0
    round: int = 1
    finished: bool = False

    def active_id(self) -> str:
        return self.order[self.turn_index]

    def living_enemies(self) -> list[Combatant]:
        return [c for c in self.combatants.values() if c.is_enemy and c.is_alive]

    def living_party(self) -> list[Combatant]:
        return [c for c in self.combatants.values() if not c.is_enemy and c.is_alive]


def start_combat(party: list[Character], enemies: list[Character], rng: Rng) -> CombatState:
    combatants: dict[str, Combatant] = {}
    for char in party:
        combatants[char.id] = Combatant.from_character(char, is_enemy=False)
    for char in enemies:
        combatants[char.id] = Combatant.from_character(char, is_enemy=True)
    initiatives = {
        cid: rng.roll_d20() + (c.dex - 10) // 2 for cid, c in combatants.items()
    }
    order = sorted(combatants, key=lambda cid: initiatives[cid], reverse=True)
    return CombatState(combatants=combatants, order=order, initiatives=initiatives)


class CombatAction(BaseModel):
    type: Literal["attack"] = "attack"
    actor_id: str
    target_id: str


def combat_turn(combat: CombatState, action: CombatAction, rng: Rng) -> CombatState:
    if combat.finished:
        return combat
    state = combat.model_copy(deep=True)
    actor = state.combatants[action.actor_id]
    target = state.combatants[action.target_id]
    if actor.is_alive and target.is_alive:
        result = attack(actor, target, rng)
        target.hp = result.target_hp_after
    if not state.living_enemies() or not state.living_party():
        state.finished = True
        return state
    next_index = state.turn_index
    for _ in range(len(state.order)):
        next_index = (next_index + 1) % len(state.order)
        if next_index == 0:
            state.round += 1
        if state.combatants[state.order[next_index]].is_alive:
            break
    state.turn_index = next_index
    return state

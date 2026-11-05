from app.models import build_character
from app.rules.checks import ability_check
from app.rules.combat import CombatAction, attack, combat_turn, start_combat
from app.rules.dice import FixedRng, Rng


def make_fighter() -> object:
    return build_character("Тест", "fighter")


def test_seeded_rng_reproducible():
    a = Rng(seed=42)
    b = Rng(seed=42)
    assert [a.roll(20) for _ in range(20)] == [b.roll(20) for _ in range(20)]


def test_roll_bounds():
    rng = Rng(seed=7)
    for _ in range(500):
        assert 1 <= rng.roll(20) <= 20
        assert 1 <= rng.roll(6) <= 6


def test_natural_20_is_critical_success_even_below_dc():
    char = make_fighter()
    result = ability_check(char, "athletics", dc=30, rng=FixedRng([20]))
    assert result.roll == 20
    assert result.critical
    assert result.success


def test_natural_1_always_fails():
    char = make_fighter()
    result = ability_check(char, "athletics", dc=1, rng=FixedRng([1]))
    assert result.roll == 1
    assert not result.critical
    assert not result.success


def test_check_uses_ability_modifier_and_proficiency():
    char = make_fighter()  # str 16 -> +3, proficient in athletics (+2)
    result = ability_check(char, "athletics", dc=10, rng=FixedRng([10]))
    assert result.ability == "str"
    assert result.modifier == 5
    assert result.total == 15
    assert result.success


def test_check_without_proficiency():
    char = make_fighter()  # cha 8 -> -1, not proficient in persuasion
    result = ability_check(char, "persuasion", dc=12, rng=FixedRng([10]))
    assert result.modifier == -1
    assert result.total == 9
    assert not result.success


def test_attack_critical_hit_doubles_dice():
    attacker = make_fighter()  # damage d8+3
    target = make_fighter()
    result = attack(attacker, target, FixedRng([20, 5, 5]))
    assert result.critical and result.hit
    assert result.damage == 13  # 5 + 5 + 3
    assert result.target_hp_after == max(0, target.max_hp - 13)


def test_attack_miss_does_no_damage():
    attacker = make_fighter()  # attack +5; target ac 16 -> total 6, miss
    target = make_fighter()
    result = attack(attacker, target, FixedRng([1]))
    assert not result.hit
    assert result.damage == 0
    assert result.target_hp_after == target.hp


def test_combat_to_the_death():
    hero = build_character("Герой", "fighter")
    goblin = build_character("Гоблин", "fighter")
    goblin.hp = goblin.max_hp = 6
    goblin.attack_bonus = 2
    goblin.damage_die = 4
    goblin.damage_bonus = 0
    goblin.ac = 12

    combat = start_combat([hero], [goblin], Rng(seed=1))
    assert set(combat.order) == {hero.id, goblin.id}

    rng = Rng(seed=2)
    guard = 0
    while not combat.finished and guard < 200:
        actor = combat.combatants[combat.active_id()]
        target = (
            combat.living_enemies()[0] if not actor.is_enemy else combat.living_party()[0]
        )
        combat = combat_turn(
            combat, CombatAction(actor_id=actor.id, target_id=target.id), rng
        )
        guard += 1

    assert combat.finished
    assert guard < 200
    dead = [c for c in combat.combatants.values() if not c.is_alive]
    assert len(dead) == 1
    assert dead[0].hp == 0
    # fighter hero strongly outmatches a 6 hp goblin with this seed
    assert combat.living_party()

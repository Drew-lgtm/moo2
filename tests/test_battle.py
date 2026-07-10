"""Golden tests for the canonical combat damage model (ecs/battle.py).

This is the single source of truth for how damage resolves. Every
resolver (strategic auto, tactical auto, tactical per-shot) routes
through these primitives, so pinning them here fences the whole combat
pipeline against accidental drift.
"""
import random

from ecs.battle import (
    Combatant, roll_damage, apply_hit, apply_damage_pool, regen_shields,
    resolve_auto, winner_of, DAMAGE_MIN_MULT, DAMAGE_MAX_MULT,
)


def _c(key=1, empire=1, attack=3, hull=10, shield=0, regen=0, defense=0):
    return Combatant(key=key, empire_id=empire, attack=attack,
                     hull=hull, hull_max=hull, shield=shield,
                     shield_max=shield, shield_regen=regen, defense=defense)


# ---- roll_damage -------------------------------------------------------

def test_roll_damage_within_spread():
    rng = random.Random(0)
    for _ in range(200):
        d = roll_damage(10, rng)
        assert int(round(10 * DAMAGE_MIN_MULT)) <= d <= int(round(10 * DAMAGE_MAX_MULT))


def test_roll_damage_zero_attack():
    assert roll_damage(0, random.Random(0)) == 0


def test_roll_damage_out_of_range():
    assert roll_damage(10, random.Random(0), range_mult=0.0) == 0


def test_roll_damage_half_range():
    # Deterministic seed; half range halves the roll region.
    rng1 = random.Random(5)
    rng2 = random.Random(5)
    full = roll_damage(20, rng1, 1.0)
    half = roll_damage(20, rng2, 0.5)
    assert half <= full


# ---- apply_hit: layered damage ----------------------------------------

def test_hit_shield_absorbs_first():
    t = _c(hull=10, shield=8, regen=0)
    r = apply_hit(t, 5)
    assert r == {"damage": 5, "to_shield": 5, "to_hull": 0, "destroyed": False}
    assert t.shield == 3 and t.hull == 10


def test_hit_spills_shield_to_hull():
    t = _c(hull=10, shield=3)
    r = apply_hit(t, 5)
    assert r["to_shield"] == 3 and r["to_hull"] == 2
    assert t.shield == 0 and t.hull == 8


def test_hit_defense_reduces_but_min_one():
    t = _c(hull=10, defense=4)
    # raw 3 vs defense 4 -> floor at 1 damage.
    r = apply_hit(t, 3)
    assert r["damage"] == 1 and t.hull == 9


def test_hit_defense_partial():
    t = _c(hull=10, defense=2)
    r = apply_hit(t, 5)  # 5-2 = 3 to hull
    assert r["damage"] == 3 and t.hull == 7


def test_hit_kills_at_zero_hull():
    t = _c(hull=3)
    r = apply_hit(t, 10)
    assert r["destroyed"] and t.destroyed and t.hull == 0


def test_hit_on_dead_is_noop():
    t = _c(hull=0)
    t.destroyed = True
    r = apply_hit(t, 10)
    assert r["damage"] == 0


# ---- apply_damage_pool: focus fire ------------------------------------

def test_pool_focus_fires_weakest_first():
    strong = _c(key="strong", hull=20)
    weak = _c(key="weak", hull=3)
    roster = [strong, weak]
    apply_damage_pool(roster, 3, random.Random(0))
    # The 3-hull ship dies; the 20-hull ship untouched.
    assert weak.destroyed
    assert strong.hull == 20


def test_pool_spills_to_next_target():
    a = _c(key="a", hull=3)
    b = _c(key="b", hull=10)
    apply_damage_pool([a, b], 8, random.Random(0))
    assert a.destroyed
    assert b.hull == 5  # 8 - 3 = 5 spilled onto b


def test_pool_terminates_on_empty_roster():
    # No infinite loop when nothing is left to hit.
    apply_damage_pool([], 100, random.Random(0))
    dead = _c(hull=0)
    dead.destroyed = True
    apply_damage_pool([dead], 100, random.Random(0))  # must return


# ---- regen -------------------------------------------------------------

def test_regen_caps_at_max():
    c = _c(hull=10, shield=2, regen=5)
    c.shield_max = 8
    c.shield = 2
    regen_shields([c])
    assert c.shield == 7
    regen_shields([c])
    assert c.shield == 8  # capped, not 12


def test_regen_skips_destroyed():
    c = _c(shield=0, regen=5)
    c.shield_max = 10
    c.destroyed = True
    regen_shields([c])
    assert c.shield == 0


# ---- resolve_auto: full battles ---------------------------------------

def _hostile(a, b):
    return a != b


def test_resolve_auto_stronger_side_wins():
    strong = {1: [_c(key="s1", empire=1, attack=8, hull=20),
                  _c(key="s2", empire=1, attack=8, hull=20)]}
    weak = {2: [_c(key="w1", empire=2, attack=2, hull=5)]}
    combatants = {**strong, **weak}
    resolve_auto(combatants, {}, _hostile, random.Random(1))
    assert winner_of(combatants) == 1


def test_resolve_auto_deterministic_with_seed():
    def build():
        return {
            1: [_c(key="a", empire=1, attack=5, hull=12, shield=6, regen=2)],
            2: [_c(key="b", empire=2, attack=5, hull=12, shield=6, regen=2)],
        }
    c1 = build()
    resolve_auto(c1, {}, _hostile, random.Random(99))
    c2 = build()
    resolve_auto(c2, {}, _hostile, random.Random(99))
    # Same seed → identical hull outcomes.
    assert [x.hull for x in c1[1]] == [x.hull for x in c2[1]]
    assert [x.hull for x in c1[2]] == [x.hull for x in c2[2]]


def test_resolve_auto_planetary_defense_fires():
    # A lone ship vs a colony with only planetary defense (no ships).
    combatants = {1: [_c(key="atk", empire=1, attack=3, hull=8)],
                  2: []}
    resolve_auto(combatants, {2: 20}, _hostile, random.Random(2))
    # Defense 20/round should shred an 8-hull attacker.
    assert all(c.destroyed for c in combatants[1])


def test_resolve_auto_peace_no_damage():
    def all_peace(a, b):
        return False
    combatants = {1: [_c(key="a", empire=1, hull=10)],
                  2: [_c(key="b", empire=2, hull=10)]}
    resolve_auto(combatants, {}, all_peace, random.Random(0))
    assert all(not c.destroyed for side in combatants.values() for c in side)


def test_winner_none_when_both_alive():
    combatants = {1: [_c(key="a", empire=1, hull=10)],
                  2: [_c(key="b", empire=2, hull=10)]}
    assert winner_of(combatants) is None

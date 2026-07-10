"""Golden tests for the deterministic pieces of ground combat.

``invade_planet`` itself is stateful (mutates ECS + DB), so it's
covered by integration tests elsewhere. Here we pin the pure building
blocks the strength formula is built from: planetary defense rating and
the marine tech bonuses.
"""
from ecs.components import BuildState
from ecs.invasion import (
    _planet_defense_rating, MARINES_PER_TRANSPORT, MILITIA_PER_MILLION_POP,
)
from ecs.techs import empire_marine_attack_bonus, empire_marine_defense_bonus


# ---- planet defense rating --------------------------------------------

def test_defense_rating_none_buildstate():
    assert _planet_defense_rating(None) == 0


def test_defense_rating_sums_defense_effects():
    # missile_base +2, star_base +8  ->  10
    bs = BuildState(completed=["missile_base", "star_base"])
    assert _planet_defense_rating(bs) == 10


def test_defense_rating_ignores_non_defense_buildings():
    # research_lab has no 'defense' effect; contributes 0.
    bs = BuildState(completed=["research_lab", "missile_base"])
    assert _planet_defense_rating(bs) == 2


def test_defense_rating_empty_is_zero():
    assert _planet_defense_rating(BuildState()) == 0


# ---- marine tech bonuses ----------------------------------------------

def test_marine_bonus_empty():
    assert empire_marine_attack_bonus(set()) == 0
    assert empire_marine_defense_bonus(set()) == 0


def test_marine_bonus_powered_armor():
    # powered_armor: marine_attack 3, marine_defense 1
    assert empire_marine_attack_bonus({"powered_armor"}) == 3
    assert empire_marine_defense_bonus({"powered_armor"}) == 1


def test_marine_bonus_stacks():
    # powered_armor (atk 3, def 1) + personal_shield (def 2) -> atk 3, def 3
    unlocked = {"powered_armor", "personal_shield"}
    assert empire_marine_attack_bonus(unlocked) == 3
    assert empire_marine_defense_bonus(unlocked) == 3


# ---- sanity on the tuning constants -----------------------------------

def test_invasion_constants_sane():
    assert MARINES_PER_TRANSPORT > 0
    assert MILITIA_PER_MILLION_POP > 0

"""Evolutionary Mutation: evolve past one inborn trait — swap it for a
trait costing no more, or shed it entirely. Once per empire."""
import pytest

from ecs.components import Empire
from ecs.races import (
    TRAITS, effective_traits, race_traits, can_mutate, mutation_replacements,
    apply_mutation, mutations_used, MUTATION_TECH, MAX_MUTATIONS,
)


def _empire(race="Humans", **kw):
    return Empire(id=1, name="P", race_type=race, color="blue", tech_level=0,
                  home_star_id=1, **kw)


UNLOCKED = [MUTATION_TECH]


# ---- gating ------------------------------------------------------------

def test_requires_the_tech():
    assert can_mutate(_empire(), []) is False
    assert can_mutate(_empire(), UNLOCKED) is True


def test_only_once_per_empire():
    e = _empire()
    assert apply_mutation(e, "bc_bonus", "ship_attack", UNLOCKED) is not None
    assert mutations_used(e) == MAX_MUTATIONS
    assert can_mutate(e, UNLOCKED) is False
    # A second attempt is refused and changes nothing.
    before = e.custom_traits
    assert apply_mutation(e, "research_bonus", "ship_hull", UNLOCKED) is None
    assert e.custom_traits == before


# ---- replacement rules -------------------------------------------------

def test_replacements_cost_no_more_than_the_dropped_trait():
    budget = TRAITS["bc_bonus"]["cost"]          # 3
    for t in mutation_replacements("bc_bonus"):
        assert TRAITS[t]["cost"] <= budget
    assert "bc_bonus" not in mutation_replacements("bc_bonus")


def test_cannot_upgrade_to_a_dearer_trait():
    e = _empire()
    # tolerant (6) costs more than bc_bonus (3) -> refused.
    assert apply_mutation(e, "bc_bonus", "tolerant", UNLOCKED) is None
    assert mutations_used(e) == 0                 # nothing spent


def test_cannot_drop_a_trait_you_do_not_have():
    e = _empire()                                 # Humans: bc_bonus, research_bonus
    assert apply_mutation(e, "hive_mind", "ship_attack", UNLOCKED) is None


def test_unknown_replacement_refused():
    e = _empire()
    assert apply_mutation(e, "bc_bonus", "not_a_trait", UNLOCKED) is None


# ---- effects -----------------------------------------------------------

def test_swap_replaces_exactly_one_trait():
    e = _empire()                                 # bc_bonus, research_bonus
    result = apply_mutation(e, "bc_bonus", "ship_attack", UNLOCKED)
    assert "bc_bonus" not in result
    assert "ship_attack" in result and "research_bonus" in result
    # And it's now what the rest of the game reads.
    assert effective_traits(e.race_type, e.custom_traits) == result


def test_shedding_a_weakness_costs_the_mutation():
    e = _empire(race="Raas")                      # fast_growth x2, weak_industry
    assert "weak_industry" in race_traits("Raas")
    result = apply_mutation(e, "weak_industry", None, UNLOCKED)
    assert "weak_industry" not in result
    assert result.count("fast_growth") == 2       # duplicates untouched
    assert mutations_used(e) == 1


def test_only_one_instance_of_a_duplicated_trait_is_removed():
    e = _empire(race="Meklar")                    # industry_bonus x2
    result = apply_mutation(e, "industry_bonus", "ship_hull", UNLOCKED)
    assert result.count("industry_bonus") == 1
    assert "ship_hull" in result


def test_preset_race_untouched_until_it_mutates():
    e = _empire()
    assert e.custom_traits == ""
    assert effective_traits(e.race_type, e.custom_traits) == race_traits("Humans")


# ---- persistence -------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mut.db")
    db.init_db()
    yield


def test_mutation_persists(temp_db):
    from ecs.db import (get_connection, insert_star, insert_empire,
                        update_empire_traits, get_empires)
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        eid = insert_empire(conn, "P", "Humans", "blue", 1, 0)
        conn.commit()
    e = _empire()
    apply_mutation(e, "bc_bonus", "ship_attack", UNLOCKED)
    with get_connection() as conn:
        update_empire_traits(conn, eid, e.custom_traits, e.mutations_used)
        conn.commit()
    row = next(r for r in get_empires() if r["id"] == eid)
    assert row["mutations_used"] == 1
    assert "ship_attack" in row["custom_traits"]
    assert "bc_bonus" not in row["custom_traits"]


# ---- review-hardening --------------------------------------------------

def test_cannot_shed_an_already_paid_one_shot_trait():
    """REGRESSION: rich_homeworld banks its BC at galaxy generation, so
    trading it away afterwards would be free points."""
    from ecs.races import ONE_SHOT_TRAITS
    e = _empire(race="Gnolam")            # bc_bonus x2, rich_homeworld
    assert "rich_homeworld" in ONE_SHOT_TRAITS
    assert apply_mutation(e, "rich_homeworld", "ship_attack", UNLOCKED) is None
    assert mutations_used(e) == 0


def test_cannot_exceed_the_trait_stack_cap():
    """REGRESSION: mutation ignored the custom-race screen's cap of 3."""
    from ecs.races import TRAIT_MAX_STACK
    e = _empire(race="Custom")
    e.custom_traits = ",".join(["ship_attack"] * TRAIT_MAX_STACK + ["bc_bonus"])
    # bc_bonus (3) -> ship_attack (3) is cost-legal but would make a 4th stack.
    assert apply_mutation(e, "bc_bonus", "ship_attack", UNLOCKED) is None

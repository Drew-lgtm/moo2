"""Golden balance tests — pin the constant *relationships* a coherence
audit established, so future value changes are deliberate (a failure here
is the signal), not accidental regressions of the missile/PD design.
"""
from ecs.techs import TECHS
from ecs.ship_design import compute_loadout, _special_priority


MISSILE_LADDER = ["nuclear_missile", "pulson_missile", "merculite_missile",
                  "proton_torpedo"]


def _density(weapon_id):
    eq = TECHS[weapon_id]["equipment"]
    return eq["attack"] / eq["size"]


def test_missile_ladder_is_monotonic():
    """Each missile up the tree must be at least as damage-dense as the
    one before — no dominated tech (the audit's core finding)."""
    ratios = [_density(w) for w in MISSILE_LADDER]
    assert ratios == sorted(ratios), ratios


def test_all_ladder_weapons_are_missiles():
    for w in MISSILE_LADDER:
        assert TECHS[w]["equipment"].get("category") == "missile", w


def test_missiles_are_denser_than_a_same_era_beam():
    """A missile must out-damage a comparable *unblockable* beam to be
    worth its point-defense vulnerability."""
    # merculite (missile) vs disruptor (beam, same rough era) per space.
    assert _density("merculite_missile") > _density("disruptor")


def test_auto_designer_fits_point_defense():
    """The whole missile/fighter drawback relies on ships actually
    carrying point-defense in auto-resolved battles."""
    lo = compute_loadout("cruiser", {"anti_missile_rockets", "laser_cannons",
                                      "heavy_armor"})
    assert "anti_missile_rockets" in lo["specials"]


def test_special_priority_values_point_defense():
    assert _special_priority(TECHS["anti_missile_rockets"]) >= 9

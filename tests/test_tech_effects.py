"""Tests that formerly-stub techs now have real effects.

Each tech in ``STUB_TECHS_WIRED`` used to carry ``effect_stub: True`` —
advertised to the player but doing nothing. As they're wired, they're
moved here and their effect asserted. Techs still legitimately stubbed
(pending a system that doesn't exist yet) are listed in
``STILL_STUBBED`` so the split stays explicit and honest.
"""
from ecs.techs import (
    TECHS, empire_bc_pct_tech, empire_research_pct_tech,
)
from ecs.projects import PROJECTS, projects_in_category


# Techs deliberately left stubbed: they need a system the game doesn't
# have yet. Kept honest — their tooltip still says "not yet implemented".
STILL_STUBBED = {
    "warp_dissipator",       # needs fleet-retreat / order gating
    "evolutionary_mutation",  # needs a mid-game trait-swap UI
}


def test_still_stubbed_are_marked():
    for tid in STILL_STUBBED:
        assert TECHS[tid].get("effect_stub") is True, (
            f"{tid} is listed as still-stubbed but lost its marker — "
            "either wire it and move it out, or restore the flag")


# ---- Batch 1: habitability build projects ------------------------------

HABITABILITY = [
    ("atmospheric_terraforming", "atmospheric_terraforming_b", 2),
    ("irradiation_resistance",   "radiation_shielding",        3),
    ("biomorphic_fungi",         "biomorphic_farms",           1),
    ("gaia_transformation",      "gaia_transformation_b",      5),
    ("artificial_planet",        "artificial_planet_b",        6),
]


def test_habitability_techs_no_longer_stub():
    for tech_id, _proj, _mp in HABITABILITY:
        assert not TECHS[tech_id].get("effect_stub"), tech_id


def test_habitability_projects_exist_and_gated():
    for tech_id, proj_id, max_pop in HABITABILITY:
        proj = PROJECTS[proj_id]
        assert proj["required_tech"] == tech_id
        assert proj["effects"].get("max_pop") == max_pop


def test_habitability_projects_appear_once_tech_unlocked():
    farm = projects_in_category("farming", {"gaia_transformation"})
    assert any(p["id"] == "gaia_transformation_b" for p in farm)


# ---- Batch 2: empire-wide economy percentages --------------------------

def test_economy_pct_techs_no_longer_stub():
    assert not TECHS["galactic_currency_exchange"].get("effect_stub")
    assert not TECHS["federation"].get("effect_stub")


def test_bc_pct_tech():
    assert empire_bc_pct_tech({"galactic_currency_exchange"}) == 25
    assert empire_bc_pct_tech(set()) == 0


def test_research_pct_tech():
    assert empire_research_pct_tech({"federation"}) == 15
    assert empire_research_pct_tech(set()) == 0


# ---- Batch 3: combat / defense / sensors / assimilation ---------------

def test_batch3_stubs_cleared():
    for tid in ("planetary_barrier_shield", "energy_absorber",
                "galactic_unification", "subspace_communications"):
        assert not TECHS[tid].get("effect_stub"), tid


def test_batch3_helpers():
    from ecs.techs import (
        empire_planetary_shield_bonus, empire_ship_shield_bonus,
        empire_assimilation_bonus, empire_sensor_range,
    )
    assert empire_planetary_shield_bonus({"planetary_barrier_shield"}) == 20
    assert empire_ship_shield_bonus({"energy_absorber"}) == 20
    assert empire_assimilation_bonus({"galactic_unification"}) == 4
    # Subspace Communications raises sensor range above the base of 6.
    assert empire_sensor_range({"subspace_communications"}) == 10
    assert empire_sensor_range(set()) == 6


def test_energy_absorber_reaches_combatant_shield():
    # Integration: _build_combatants must fold the Energy Absorber bonus
    # into each ship's shield. Uses a minimal fake component manager.
    from ecs.components import Ship, TechState
    import ecs.combat as combat

    class FakeCM:
        def __init__(self, unlocked):
            self._ship = Ship(id=1, ship_class="frigate", armor_tech=None,
                              shield_tech=None, weapon_tech=None,
                              weapon_count=0, specials=[])
            self._ts = TechState(empire_id=1, current_target=None, progress=0,
                                 unlocked=list(unlocked), locked_out=[])

        def get_all(self, comp):
            return [(999, self._ts)] if comp is TechState else []

        def get_component(self, entity, comp):
            return self._ship if comp is Ship else None

    def bonuses(_eid):
        return (0, 0)

    def stats_full(_e):
        return {"attack": 2, "hull": 0, "defense": 0,
                "shield_capacity": 0, "shield_regen": 0}

    # With Energy Absorber → shield 0 + 20 = 20.
    cm = FakeCM({"energy_absorber"})
    rosters, _ = combat._build_combatants(
        cm, {1: [10]}, bonuses, {}, lambda eid, e: 2, stats_full)
    assert rosters[1][0].shield_max == 20

    # Without it → shield 0.
    cm2 = FakeCM(set())
    rosters2, _ = combat._build_combatants(
        cm2, {1: [10]}, bonuses, {}, lambda eid, e: 2, stats_full)
    assert rosters2[1][0].shield_max == 0


# ---- Batch 4: espionage missions --------------------------------------

def test_batch4_stubs_cleared():
    assert not TECHS["subterfuge"].get("effect_stub")
    assert not TECHS["assassination"].get("effect_stub")


def test_espionage_general_offense():
    from ecs.techs import empire_spy_offense
    assert empire_spy_offense({"subterfuge"}) == 2
    assert empire_spy_offense({"assassination"}) == 2


def test_espionage_mission_bonus_fields():
    assert TECHS["subterfuge"].get("frame_bonus") == 4
    assert TECHS["assassination"].get("assassinate_bonus") == 4


# ---- Batch 5: ship space + bioweapon ----------------------------------

def test_batch5_stubs_cleared():
    assert not TECHS["molecular_compression"].get("effect_stub")
    assert not TECHS["bio_terminators"].get("effect_stub")


def test_molecular_compression_expands_hull_budget():
    from ecs.ship_design import compute_loadout
    base = compute_loadout("cruiser", set())["stats"]["space_total"]
    boosted = compute_loadout("cruiser", {"molecular_compression"})["stats"]["space_total"]
    # +20% budget. Cruiser base space is 20 → +4 = 24.
    assert boosted == base + int(round(base * 0.20))
    assert boosted > base


def test_bio_terminators_field():
    assert TECHS["bio_terminators"].get("bio_militia_pct") == 40

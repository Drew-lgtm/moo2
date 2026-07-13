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

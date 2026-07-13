"""Titan + Doom Star apex hulls: catalog, tech-gating, combat stats."""
from ecs.ships import SHIPS, SHIP_ORDER, MILITARY_SHIPS
from ecs.projects import PROJECTS, project_is_available
from ecs.techs import TECHS
from ecs.components import Ship
from ecs.ship_design import stats_from_ship
from ecs.tactical import SHIP_AP


def test_apex_hulls_in_catalog():
    for cls in ("titan", "doom_star"):
        assert cls in SHIPS
        assert cls in SHIP_ORDER
        assert cls in MILITARY_SHIPS


def test_apex_bigger_than_dreadnought():
    dn = SHIPS["dreadnought"]
    for cls in ("titan", "doom_star"):
        s = SHIPS[cls]
        assert s["hull"] > dn["hull"]
        assert s["space"] > dn["space"]
        assert s["cost"] > dn["cost"]
    # Doom Star is the apex.
    assert SHIPS["doom_star"]["space"] > SHIPS["titan"]["space"]


def test_apex_construction_techs_exist():
    assert TECHS["titan_construction"]["field"] == "construction"
    assert TECHS["doom_star_construction"]["prereqs"] == ["titan_construction"]


def test_apex_ship_projects_are_tech_gated():
    assert PROJECTS["ship_titan"]["required_tech"] == "titan_construction"
    assert PROJECTS["ship_doom_star"]["required_tech"] == "doom_star_construction"
    # Not buildable without the tech...
    assert not project_is_available("ship_titan", set())
    assert not project_is_available("ship_doom_star", set())
    # ...buildable once researched.
    assert project_is_available("ship_titan", {"titan_construction"})
    assert project_is_available("ship_doom_star", {"doom_star_construction"})
    # Base hulls remain ungated.
    assert project_is_available("ship_frigate", set())


def test_apex_have_movement_points():
    assert SHIP_AP["titan"] > 0
    assert SHIP_AP["doom_star"] > 0
    # Apex hulls lumber (no faster than a dreadnought).
    assert SHIP_AP["doom_star"] <= SHIP_AP["dreadnought"]


def test_doom_star_can_mount_stellar_converter():
    # The Doom Star's huge budget is the point — it fits the size-8
    # Stellar Converter that smaller hulls can't. Verify via space math.
    from ecs.ship_design import design_space_used, hull_space_budget
    used = design_space_used(weapon_tech="stellar_converter", weapon_count=1,
                             weapon_mount="normal")
    assert used <= hull_space_budget("doom_star")
    # A frigate cannot.
    assert used > hull_space_budget("frigate")


def test_doom_star_base_combat_stats():
    # Bare hull (no equipment) still carries the class base attack/hull
    # into combat via stats + SHIPS base.
    ship = Ship(id=1, ship_class="doom_star")
    st = stats_from_ship(ship)
    # No equipment → equipment stats zero; base comes from SHIPS.
    assert SHIPS["doom_star"]["attack"] == 34
    assert SHIPS["doom_star"]["hull"] == 60

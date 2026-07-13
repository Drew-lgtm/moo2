"""AI ship-design authoring + build-queue translation.

The AI authors one 'Auto <Class>' blueprint per warship class from its
current tech (heavy mounts for aggressive empires) and its build loop
swaps ``ship_<class>`` orders for the design so enemy fleets vary and
actually field mounts.
"""
import pytest
from types import SimpleNamespace

from ecs.components import Empire, BuildState, Planet
from ecs.component_manager import ComponentManager
from ecs.designs import ShipDesignManager, parse_design_project
from ecs.ai import _ai_ensure_designs, _ai_queue_building, AI_DESIGN_CLASSES


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ai.db")
    db.init_db()
    yield


WEAPON_TECH = {"laser_cannons", "heavy_armor", "class_i_shield"}
# Classes buildable without any apex-hull construction tech.
BASE_WARSHIPS = {"frigate", "carrier", "cruiser", "battleship", "dreadnought"}


def _game():
    return SimpleNamespace(ship_designs=ShipDesignManager())


def test_ensure_designs_creates_one_per_buildable_class(temp_db):
    game = _game()
    emp = Empire(id=1, name="AI", race_type="Humans", color="red",
                 tech_level=0, home_star_id=1, is_player=False)
    dm = _ai_ensure_designs(game, emp, {"aggressive": False}, WEAPON_TECH)
    # Every base warship gets a design; tech-gated hulls do NOT (no
    # Titan/Doom Star construction researched here).
    assert set(dm) == BASE_WARSHIPS
    assert "titan" not in dm and "doom_star" not in dm
    for pid in dm.values():
        assert parse_design_project(pid) is not None
    assert len(game.ship_designs.for_empire(1)) == len(BASE_WARSHIPS)


def test_ensure_designs_includes_apex_hulls_once_teched(temp_db):
    game = _game()
    emp = Empire(id=1, name="AI", race_type="Humans", color="red",
                 tech_level=0, home_star_id=1, is_player=False)
    teched = WEAPON_TECH | {"titan_construction", "doom_star_construction"}
    dm = _ai_ensure_designs(game, emp, {"aggressive": True}, teched)
    assert "titan" in dm and "doom_star" in dm
    # And the apex designs still fit their (larger) hull budgets.
    by_class = {d.ship_class: d for d in game.ship_designs.for_empire(1)}
    assert by_class["titan"].fits(teched)
    assert by_class["doom_star"].fits(teched)


def test_ensure_designs_idempotent(temp_db):
    game = _game()
    emp = Empire(id=1, name="AI", race_type="Humans", color="red",
                 tech_level=0, home_star_id=1, is_player=False)
    _ai_ensure_designs(game, emp, {"aggressive": False}, WEAPON_TECH)
    n1 = len(game.ship_designs.for_empire(1))
    _ai_ensure_designs(game, emp, {"aggressive": False}, WEAPON_TECH)
    n2 = len(game.ship_designs.for_empire(1))
    assert n1 == n2, "designs should be reused, not duplicated"


def test_aggressive_uses_heavy_mount_and_fits(temp_db):
    game = _game()
    emp = Empire(id=1, name="AI", race_type="Humans", color="red",
                 tech_level=0, home_star_id=1, is_player=False)
    _ai_ensure_designs(game, emp, {"aggressive": True}, WEAPON_TECH)
    for d in game.ship_designs.for_empire(1):
        assert d.weapon_mount == "heavy"
        assert d.fits(WEAPON_TECH), f"{d.ship_class} design over budget"


def test_aggressive_designs_always_fit_even_with_huge_weapons(temp_db):
    """REGRESSION (review finding): an aggressive AI with a big weapon
    (Mauler, size 4) must not author an over-budget Heavy design on a
    small hull — it should fall back toward a Normal mount so the design
    always fits. Nothing the AI builds may exceed its hull budget."""
    game = _game()
    emp = Empire(id=1, name="AI", race_type="Humans", color="red",
                 tech_level=0, home_star_id=1, is_player=False)
    # Mauler + battle pods researched — the exact over-budget trap.
    teched = {"mauler_device", "battle_pods", "heavy_armor", "class_i_shield"}
    _ai_ensure_designs(game, emp, {"aggressive": True}, teched)
    for d in game.ship_designs.for_empire(1):
        assert d.fits(teched), (
            f"{d.ship_class} {d.weapon_mount} x{d.weapon_count} over budget")


def test_no_weapon_tech_no_designs(temp_db):
    game = _game()
    emp = Empire(id=1, name="AI", race_type="Humans", color="red",
                 tech_level=0, home_star_id=1, is_player=False)
    dm = _ai_ensure_designs(game, emp, {"aggressive": True}, set())
    assert dm == {}
    assert game.ship_designs.for_empire(1) == []


def test_queue_building_translates_ship_to_design():
    cm = ComponentManager()
    e = 1
    cm.add_component(e, Planet(id=1, planet_type="Terran", size="Medium",
                              colonizable=True))
    cm.add_component(e, BuildState())
    writes = []
    # Priority wants a cruiser; design map redirects to the empire's design.
    _ai_queue_building(cm, e, ["ship_cruiser"], set(), writes,
                       design_map={"cruiser": "design:7"})
    bs = cm.get_component(e, BuildState)
    assert bs.current_project == "design:7"
    assert writes and writes[-1][1][1] == "design:7"


def test_queue_building_no_map_uses_auto():
    cm = ComponentManager()
    e = 1
    cm.add_component(e, Planet(id=1, planet_type="Terran", size="Medium",
                              colonizable=True))
    cm.add_component(e, BuildState())
    writes = []
    # ship_scout is always available (no required_tech); no design map.
    _ai_queue_building(cm, e, ["ship_scout"], set(), writes, design_map={})
    bs = cm.get_component(e, BuildState)
    assert bs.current_project == "ship_scout"

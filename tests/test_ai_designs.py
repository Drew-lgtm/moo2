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


def _game():
    return SimpleNamespace(ship_designs=ShipDesignManager())


def test_ensure_designs_creates_one_per_class(temp_db):
    game = _game()
    emp = Empire(id=1, name="AI", race_type="Humans", color="red",
                 tech_level=0, home_star_id=1, is_player=False)
    dm = _ai_ensure_designs(game, emp, {"aggressive": False}, WEAPON_TECH)
    # Every warship class with a weapon gets a design.
    assert set(dm) == set(AI_DESIGN_CLASSES)
    for cls, pid in dm.items():
        assert parse_design_project(pid) is not None
    # One design per class, all owned by empire 1.
    designs = game.ship_designs.for_empire(1)
    assert len(designs) == len(AI_DESIGN_CLASSES)


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

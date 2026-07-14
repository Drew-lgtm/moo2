"""Ship maintenance: a fleet drains BC each turn (a fraction of its
build cost). The treasury floors at 0 rather than going into debt."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting, StarRef,
    Ship, ShipOwner, ShipAt,
)
from ecs.ships import SHIPS
from ecs.economy import (
    production_tick, empire_per_turn, fleet_upkeep, SHIP_UPKEEP_FRACTION,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "upkeep.db")
    db.init_db()
    yield


def _world(fleet=(), bc=0, workers=0):
    """Player empire (Alkari — no economy traits) with a bare colony and
    ``fleet`` ships parked at its star. Returns (game, cm, emp, planet_e)."""
    from ecs.db import get_connection, insert_star, insert_empire, insert_ship
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        insert_empire(conn, "P", "Alkari", "blue", 1, 0)
        conn.commit()
    em = EntityManager()
    cm = ComponentManager()
    emp = Empire(id=1, name="P", race_type="Alkari", color="blue",
                 tech_level=0, home_star_id=1, bc=bc, research_points=0,
                 is_player=True)
    cm.add_component(em.create_entity(), emp)
    cm.add_component(next(e for e, c in cm.get_all(Empire)), TechState(
        empire_id=1, unlocked=[]))
    star_e = em.create_entity()
    cm.add_component(star_e, StarRef(db_id=1))
    planet_e = em.create_entity()
    cm.add_component(planet_e, Planet(id=1, planet_type="Terran", size="Medium",
                                      colonizable=True, richness="Abundant"))
    cm.add_component(planet_e, Owner(empire_id=1))
    cm.add_component(planet_e, Population(current=max(1, workers), max=12,
                                          workers=workers))
    cm.add_component(planet_e, Orbiting(star_entity=star_e))
    cm.add_component(planet_e, BuildState(current_project=None))
    for sc in fleet:
        with get_connection() as conn:
            sid = insert_ship(conn, 1, sc, 1)
            conn.commit()
        se = em.create_entity()
        cm.add_component(se, Ship(id=sid, ship_class=sc))
        cm.add_component(se, ShipOwner(empire_id=1))
        cm.add_component(se, ShipAt(star_entity=star_e))
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, ship_designs=None,
                           leaders=None, diplomacy=None, turn_log=None,
                           galaxy=SimpleNamespace(difficulty="normal"))
    return game, cm, emp, planet_e


def test_fleet_upkeep_sums_costs():
    game, cm, _emp, _p = _world(fleet=["cruiser", "battleship"])
    expected = int((SHIPS["cruiser"]["cost"] + SHIPS["battleship"]["cost"])
                   * SHIP_UPKEEP_FRACTION)
    assert fleet_upkeep(cm, 1) == expected


def test_no_fleet_no_upkeep():
    game, cm, _emp, _p = _world(fleet=[])
    assert fleet_upkeep(cm, 1) == 0


def test_upkeep_deducted_from_treasury(temp_db):
    # No workers → no income; a fleet with a treasury pays maintenance.
    game, cm, emp, _p = _world(fleet=["battleship"], bc=100, workers=0)
    up = fleet_upkeep(cm, 1)
    assert up > 0
    production_tick(game, new_turn=2)
    assert emp.bc == 100 - up


def test_treasury_floors_at_zero(temp_db):
    # Big fleet, empty treasury, no income → can't pay, floors at 0.
    game, cm, emp, _p = _world(fleet=["battleship", "battleship"], bc=0,
                               workers=0)
    production_tick(game, new_turn=2)
    assert emp.bc == 0


def test_income_offsets_upkeep(temp_db):
    # 5 Alkari workers = 5 industry = 5 BC income (idle colony), minus a
    # frigate's upkeep.
    game, cm, emp, _p = _world(fleet=["frigate"], bc=0, workers=5)
    up = fleet_upkeep(cm, 1)
    production_tick(game, new_turn=2)
    assert emp.bc == max(0, 5 - up)


def test_hud_bc_is_net_of_upkeep(temp_db):
    game, cm, emp, _p = _world(fleet=["cruiser"], bc=0, workers=5)
    per_turn = empire_per_turn(cm, 1)
    assert per_turn["upkeep"] == fleet_upkeep(cm, 1)
    assert per_turn["bc"] == 5 - per_turn["upkeep"]


def test_treasury_exhausted_warns_player_once(temp_db):
    # Player with a treasury, a costly fleet, and no income: the turn it
    # first drops to 0 from upkeep, a warning is logged.
    from ecs.turn_log import TurnLog
    game, cm, emp, _p = _world(fleet=["battleship"], bc=1, workers=0)
    game.turn_log = TurnLog()
    production_tick(game, new_turn=2)
    assert emp.bc == 0
    lines = [text for _turn, _cat, text in game.turn_log.entries]
    assert any("Treasury exhausted" in m for m in lines)
    # Already broke next turn -> no repeat spam.
    production_tick(game, new_turn=3)
    lines2 = [text for _turn, _cat, text in game.turn_log.entries]
    assert sum("Treasury exhausted" in m for m in lines2) == 1

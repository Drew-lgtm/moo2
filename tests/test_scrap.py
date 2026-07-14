"""Scrapping ships for a partial BC refund."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import Empire, Ship, ShipOwner, ShipAt, StarRef
from ecs.ships import SHIPS
from ecs.scrap import scrap_ships, scrap_value, SCRAP_REFUND_FRACTION


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "scrap.db")
    db.init_db()
    yield


def _world(fleet):
    """fleet: list of ship_class. Player empire id 1 with those ships
    parked at one star. Returns (game, cm, emp, [ship_entity...])."""
    from ecs.db import get_connection, insert_star, insert_empire, insert_ship
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)   # id 1
        insert_empire(conn, "P", "Humans", "blue", 1, 0)    # id 1
        conn.commit()
    em = EntityManager()
    cm = ComponentManager()
    emp = Empire(id=1, name="P", race_type="Humans", color="blue",
                 tech_level=0, home_star_id=1, bc=0, research_points=0,
                 is_player=True)
    cm.add_component(em.create_entity(), emp)
    star_e = em.create_entity()
    cm.add_component(star_e, StarRef(db_id=1))
    ships = []
    for sc in fleet:
        with get_connection() as conn:
            sid = insert_ship(conn, 1, sc, 1)
            conn.commit()
        se = em.create_entity()
        cm.add_component(se, Ship(id=sid, ship_class=sc))
        cm.add_component(se, ShipOwner(empire_id=1))
        cm.add_component(se, ShipAt(star_entity=star_e))
        ships.append(se)
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em)
    return game, cm, emp, ships


def test_scrap_value_is_a_fraction_of_cost():
    for sc in ("frigate", "cruiser", "battleship"):
        assert scrap_value(sc) == int(SHIPS[sc]["cost"] * SCRAP_REFUND_FRACTION)


def test_scrap_removes_ships_and_refunds(temp_db):
    game, cm, emp, ships = _world(["cruiser", "cruiser"])
    expected = 2 * scrap_value("cruiser")
    result = scrap_ships(game, ships)
    assert result["scrapped"] == 2
    assert result["refund"] == expected
    assert emp.bc == expected
    # Ships gone from ECS.
    assert not any(cm.get_component(e, Ship) for e in ships)
    assert len([1 for _e, _o in cm.get_all(ShipOwner)]) == 0


def test_scrap_persists_to_db(temp_db):
    game, cm, emp, ships = _world(["battleship"])
    sid = cm.get_component(ships[0], Ship).id
    scrap_ships(game, ships)
    from ecs.db import get_connection
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM ships WHERE id = ?", (sid,)).fetchone()
        emp_row = conn.execute("SELECT bc FROM empires WHERE id = 1").fetchone()
    assert row is None                                   # ship deleted
    assert emp_row["bc"] == scrap_value("battleship")    # refund persisted


def test_scrap_empty_list_is_noop(temp_db):
    game, cm, emp, _ships = _world(["frigate"])
    result = scrap_ships(game, [])
    assert result == {"scrapped": 0, "refund": 0}
    assert emp.bc == 0

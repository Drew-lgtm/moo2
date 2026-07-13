"""Orbital bombardment: firepower, pop loss, defense mitigation,
colony destruction, once-per-turn gating."""
import random
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, Owner, Planet, Population, BuildState, Orbiting, StarRef,
    Ship, ShipOwner, ShipAt,
)
from ecs.bombard import (
    can_bombard, bombard_planet, fleet_bombard_power, BOMBARD_CLASSES,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "bombard.db")
    db.init_db()
    yield


def _world(defender_pop=10, defense_buildings=None, attacker_ships=None):
    """Build attacker empire 1, defender empire 2 owning a colony, with
    the attacker's ships parked at the colony's star."""
    from ecs.db import get_connection, insert_star, insert_empire
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)   # id 1
        insert_empire(conn, "Atk", "Humans", "red", 1, 0)   # id 1
        insert_empire(conn, "Def", "Klackon", "green", 1, 0)  # id 2
        conn.commit()
    em = EntityManager()
    cm = ComponentManager()
    for eid in (1, 2):
        e = em.create_entity()
        cm.add_component(e, Empire(id=eid, name=f"E{eid}", race_type="Humans",
                                   color="red", tech_level=0, home_star_id=1,
                                   is_player=(eid == 1)))
    star = em.create_entity()
    cm.add_component(star, StarRef(db_id=1))
    planet = em.create_entity()
    cm.add_component(planet, Planet(id=1, planet_type="Terran", size="Medium",
                                    colonizable=True))
    cm.add_component(planet, Owner(empire_id=2))
    cm.add_component(planet, Population(current=defender_pop, max=12,
                                       workers=defender_pop))
    cm.add_component(planet, Orbiting(star_entity=star))
    cm.add_component(planet, BuildState(completed=list(defense_buildings or [])))
    from ecs.db import insert_ship
    ships = attacker_ships if attacker_ships is not None else ["cruiser"]
    for cls in ships:
        se = em.create_entity()
        with get_connection() as conn:
            sid = insert_ship(conn, 1, cls, 1)
            conn.commit()
        cm.add_component(se, Ship(id=sid, ship_class=cls))
        cm.add_component(se, ShipOwner(empire_id=1))
        cm.add_component(se, ShipAt(star_entity=star))
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, diplomacy=None,
                           turn_log=None, bombarded_this_turn=set(),
                           galaxy=SimpleNamespace(turn=5))
    return game, cm, planet


def test_can_bombard_requires_warship(temp_db):
    game, cm, planet = _world(attacker_ships=[])
    assert not can_bombard(cm, planet, 1)  # no ships
    game2, cm2, planet2 = _world(attacker_ships=["cruiser"])
    assert can_bombard(cm2, planet2, 1)


def test_troop_transport_cannot_bombard(temp_db):
    # troop_transport isn't in BOMBARD_CLASSES.
    assert "troop_transport" not in BOMBARD_CLASSES
    game, cm, planet = _world(attacker_ships=["troop_transport"])
    assert not can_bombard(cm, planet, 1)


def test_fleet_power_counts_base_attack(temp_db):
    game, cm, planet = _world(attacker_ships=["cruiser", "cruiser"])
    star = cm.get_component(planet, Orbiting).star_entity
    # cruiser base attack 3 → 2 cruisers = 6.
    assert fleet_bombard_power(cm, star, 1) == 6


def test_bombard_kills_pop(temp_db):
    game, cm, planet = _world(defender_pop=10,
                              attacker_ships=["dreadnought"])  # attack 12
    r = bombard_planet(game, planet, 1, random.Random(0))
    assert r["success"] and r["pop_lost"] > 0
    pop = cm.get_component(planet, Population)
    assert pop.current == 10 - r["pop_lost"]


def test_planetary_defense_absorbs(temp_db):
    # star_base (+8 defense) vs a frigate (attack 1) → repelled.
    game, cm, planet = _world(defense_buildings=["star_base"],
                              attacker_ships=["frigate"])
    r = bombard_planet(game, planet, 1, random.Random(0))
    assert r["effective"] == 0 and r["pop_lost"] == 0
    assert cm.get_component(planet, Population).current == 10


def test_once_per_turn(temp_db):
    game, cm, planet = _world(attacker_ships=["dreadnought"])
    r1 = bombard_planet(game, planet, 1, random.Random(0))
    assert r1["success"]
    r2 = bombard_planet(game, planet, 1, random.Random(0))
    assert not r2["success"] and r2["reason"] == "already_bombarded_this_turn"


def test_bombard_to_destruction_clears_colony(temp_db):
    # Tiny pop, massive fleet → colony destroyed, ownership cleared.
    game, cm, planet = _world(defender_pop=1,
                              attacker_ships=["doom_star"])  # attack 34
    r = bombard_planet(game, planet, 1, random.Random(0))
    assert r["colony_destroyed"] is True
    assert cm.get_component(planet, Owner) is None
    assert cm.get_component(planet, Population) is None

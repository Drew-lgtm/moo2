"""Orbital blockade: a hostile fleet over a colony severs its trade
(cuts BC) until driven off. Distinct from bombardment (no pop loss)."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting, StarRef,
    Ship, ShipOwner, ShipAt,
)
from ecs.blockade import is_blockaded


def _war(at_war=True):
    return SimpleNamespace(at_war=lambda a, b: at_war)


def _cm_with_colony(owner_id=1):
    em = EntityManager()
    cm = ComponentManager()
    star = em.create_entity()
    cm.add_component(star, StarRef(db_id=1))
    planet = em.create_entity()
    cm.add_component(planet, Planet(id=1, planet_type="Terran", size="Medium",
                                    colonizable=True))
    cm.add_component(planet, Owner(empire_id=owner_id))
    cm.add_component(planet, Orbiting(star_entity=star))
    return em, cm, star, planet


def _add_ship(em, cm, star, empire_id, ship_class="cruiser"):
    e = em.create_entity()
    cm.add_component(e, Ship(id=abs(hash((empire_id, ship_class, star))) % 100000,
                             ship_class=ship_class))
    cm.add_component(e, ShipOwner(empire_id=empire_id))
    cm.add_component(e, ShipAt(star_entity=star))
    return e


# ---- is_blockaded ------------------------------------------------------

def test_enemy_warship_at_war_blockades():
    em, cm, star, planet = _cm_with_colony(owner_id=1)
    _add_ship(em, cm, star, empire_id=2, ship_class="cruiser")
    assert is_blockaded(cm, planet, _war(True)) is True


def test_not_at_war_no_blockade():
    em, cm, star, planet = _cm_with_colony(owner_id=1)
    _add_ship(em, cm, star, empire_id=2, ship_class="cruiser")
    assert is_blockaded(cm, planet, _war(False)) is False


def test_own_ship_no_blockade():
    em, cm, star, planet = _cm_with_colony(owner_id=1)
    _add_ship(em, cm, star, empire_id=1, ship_class="cruiser")
    assert is_blockaded(cm, planet, _war(True)) is False


def test_non_warship_no_blockade():
    em, cm, star, planet = _cm_with_colony(owner_id=1)
    _add_ship(em, cm, star, empire_id=2, ship_class="colony_ship")
    assert is_blockaded(cm, planet, _war(True)) is False


def test_pseudo_empire_does_not_blockade():
    from ecs.monsters import MONSTER_EMPIRE_ID
    em, cm, star, planet = _cm_with_colony(owner_id=1)
    _add_ship(em, cm, star, empire_id=MONSTER_EMPIRE_ID, ship_class="battleship")
    assert is_blockaded(cm, planet, _war(True)) is False


def test_no_diplo_no_blockade():
    em, cm, star, planet = _cm_with_colony(owner_id=1)
    _add_ship(em, cm, star, empire_id=2, ship_class="cruiser")
    assert is_blockaded(cm, planet, None) is False


# ---- economy integration ----------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blockade.db")
    db.init_db()
    yield


def _game_with_blockade(blockaded: bool):
    """Player colony (Alkari, 5 workers = 5 industry = 5 BC when idle) and
    an enemy (id 2) at war. If blockaded, an enemy cruiser sits at the
    colony's star. Returns (game, player_empire)."""
    from ecs.db import get_connection, insert_star, insert_empire
    from ecs.diplomacy import Diplomacy
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        insert_empire(conn, "P", "Alkari", "blue", 1, 0)
        insert_empire(conn, "E", "Alkari", "red", 1, 0)
        conn.commit()
    em = EntityManager()
    cm = ComponentManager()
    player = Empire(id=1, name="P", race_type="Alkari", color="blue",
                    tech_level=0, home_star_id=1, bc=0, research_points=0,
                    is_player=True)
    cm.add_component(em.create_entity(), player)
    cm.add_component(next(e for e, c in cm.get_all(Empire)),
                     TechState(empire_id=1, unlocked=[]))
    enemy = Empire(id=2, name="E", race_type="Alkari", color="red",
                   tech_level=0, home_star_id=1, bc=0, research_points=0,
                   is_player=False)
    cm.add_component(em.create_entity(), enemy)

    star = em.create_entity()
    cm.add_component(star, StarRef(db_id=1))
    planet = em.create_entity()
    cm.add_component(planet, Planet(id=1, planet_type="Terran", size="Medium",
                                    colonizable=True, richness="Abundant"))
    cm.add_component(planet, Owner(empire_id=1))
    cm.add_component(planet, Population(current=5, max=12, workers=5))
    cm.add_component(planet, Orbiting(star_entity=star))
    cm.add_component(planet, BuildState(current_project=None))

    diplo = Diplomacy()
    diplo._pair(1, 2)["at_war"] = True
    if blockaded:
        se = em.create_entity()
        cm.add_component(se, Ship(id=1, ship_class="cruiser"))
        cm.add_component(se, ShipOwner(empire_id=2))
        cm.add_component(se, ShipAt(star_entity=star))

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, ship_designs=None,
                           leaders=None, diplomacy=diplo, turn_log=None,
                           galaxy=SimpleNamespace(difficulty="normal"))
    return game, player


def test_blockade_zeroes_colony_bc(temp_db):
    from ecs.economy import production_tick
    game, player = _game_with_blockade(blockaded=True)
    production_tick(game, new_turn=2)
    assert player.bc == 0          # trade cut by the blockade


def test_unblockaded_colony_earns_bc(temp_db):
    from ecs.economy import production_tick
    game, player = _game_with_blockade(blockaded=False)
    production_tick(game, new_turn=2)
    assert player.bc == 5          # 5 idle industry -> 5 BC, no blockade


def test_hud_projection_reflects_blockade(temp_db):
    from ecs.economy import empire_per_turn
    game, _player = _game_with_blockade(blockaded=True)
    cm = game.component_mgr
    # Without diplo the HUD can't know about the blockade -> projects 5.
    assert empire_per_turn(cm, 1)["bc"] == 5
    # With diplo it matches the tick: blockaded trade is cut -> 0.
    assert empire_per_turn(cm, 1, None, game.diplomacy)["bc"] == 0

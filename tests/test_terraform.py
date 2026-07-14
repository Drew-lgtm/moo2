"""Terraforming upgrades a planet's biome, not just a flat max-pop bump.

Completing the Terraforming project reshapes the world toward Terran
(Gaia Transformation goes one better). Output is derived from the biome
live, so the population cap follows the new type and the change is
persisted to the planets table. Never downgrades a world.
"""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting, StarRef,
)
from ecs.economy import (
    production_tick, compute_max_population, _is_biome_upgrade,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "terra.db")
    db.init_db()
    yield


def _world(project, planet_type="Tundra", size="Medium"):
    """One player colony running ``project`` (funded to completion this
    tick). Returns (game, cm, planet_e, planet_db_id)."""
    from ecs.db import (get_connection, insert_star, insert_empire,
                        insert_planet)
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)     # id 1
        insert_empire(conn, "P", "Alkari", "blue", 1, 0)      # id 1
        pid = insert_planet(conn, 1, planet_type, size, 1, owner_empire_id=1,
                            population=5, max_population=compute_max_population(
                                planet_type, size), workers=5)
        conn.commit()

    em = EntityManager()
    cm = ComponentManager()
    emp_e = em.create_entity()
    cm.add_component(emp_e, Empire(id=1, name="P", race_type="Alkari",
                                   color="blue", tech_level=0, home_star_id=1,
                                   is_player=True))
    cm.add_component(emp_e, TechState(empire_id=1, unlocked=[]))
    star_e = em.create_entity()
    cm.add_component(star_e, StarRef(db_id=1))
    planet_e = em.create_entity()
    cm.add_component(planet_e, Planet(id=pid, planet_type=planet_type, size=size,
                                      colonizable=True, richness="Abundant"))
    cm.add_component(planet_e, Owner(empire_id=1))
    cm.add_component(planet_e, Population(
        current=5, max=compute_max_population(planet_type, size), workers=5))
    cm.add_component(planet_e, Orbiting(star_entity=star_e))
    # Funded to completion: progress already at the project cost.
    from ecs.projects import PROJECTS
    cm.add_component(planet_e, BuildState(current_project=project,
                                          progress=PROJECTS[project]["cost"]))

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, ship_designs=None,
                           leaders=None, diplomacy=None, turn_log=None,
                           galaxy=SimpleNamespace(difficulty="normal"))
    return game, cm, planet_e, pid


# ---- _is_biome_upgrade -------------------------------------------------

def test_biome_upgrade_ranking():
    assert _is_biome_upgrade("Tundra", "Terran")
    assert _is_biome_upgrade("Terran", "Gaia")
    assert not _is_biome_upgrade("Terran", "Terran")   # equal, no-op
    assert not _is_biome_upgrade("Gaia", "Terran")     # never downgrade
    assert not _is_biome_upgrade("Ocean", "Terran")    # equal cap mult


# ---- terraforming completion ------------------------------------------

def test_terraforming_upgrades_biome_and_cap(temp_db):
    game, cm, planet_e, pid = _world("terraforming", planet_type="Tundra")
    before = cm.get_component(planet_e, Population).max
    production_tick(game, new_turn=2)
    planet = cm.get_component(planet_e, Planet)
    pop = cm.get_component(planet_e, Population)
    assert planet.planet_type == "Terran"
    # Medium: Tundra cap 9 -> Terran cap 12 (delta 3) + flat +3 effect.
    assert pop.max == before + 3 + 3


def test_terraforming_persists_type_to_db(temp_db):
    game, cm, planet_e, pid = _world("terraforming", planet_type="Desert")
    production_tick(game, new_turn=2)
    from ecs.db import get_connection
    with get_connection() as conn:
        row = conn.execute("SELECT type FROM planets WHERE id = ?",
                           (pid,)).fetchone()
    assert row["type"] == "Terran"


def test_terraforming_never_downgrades(temp_db):
    # Already Gaia: Terraforming (targets Terran) must NOT downgrade it,
    # though the flat +3 max_pop still applies.
    game, cm, planet_e, pid = _world("terraforming", planet_type="Gaia")
    before = cm.get_component(planet_e, Population).max
    production_tick(game, new_turn=2)
    planet = cm.get_component(planet_e, Planet)
    pop = cm.get_component(planet_e, Population)
    assert planet.planet_type == "Gaia"          # unchanged
    assert pop.max == before + 3                  # only the flat bonus


def test_gaia_transformation_reaches_gaia(temp_db):
    game, cm, planet_e, pid = _world("gaia_transformation_b", planet_type="Terran")
    production_tick(game, new_turn=2)
    planet = cm.get_component(planet_e, Planet)
    assert planet.planet_type == "Gaia"


def test_terraforming_completes_once(temp_db):
    game, cm, planet_e, pid = _world("terraforming", planet_type="Tundra")
    production_tick(game, new_turn=2)
    bs = cm.get_component(planet_e, BuildState)
    assert "terraforming" in bs.completed          # one-shot building
    assert bs.current_project is None

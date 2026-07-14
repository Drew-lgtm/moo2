"""Perpetual "mode" build orders: Trade Goods and Housing.

Both are zero-cost orders that never complete. While one is a colony's
current project, that colony's whole industry output is redirected:
Trade Goods -> empire BC, Housing -> population growth. Set-mode /
toggle-off behaviour lives in the build scene; the economic effect is
tested here against ``production_tick``.
"""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting, StarRef,
)
from ecs.economy import (
    production_tick, empire_per_turn, HOUSING_GROWTH_PER_INDUSTRY,
)
from ecs.projects import PROJECTS


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "modes.db")
    db.init_db()
    yield


def _world(current_project, pop_current=5, pop_max=12, workers=5):
    """A single player colony (Medium Terran, Abundant) with all pop as
    workers so industry == workers. Returns (game, cm, empire, planet_e)."""
    # Alkari have no planet-output race traits (only ship bonuses), so a
    # colony's BC/industry maths stays clean: industry == workers and the
    # racial trade bonus is zero — isolating the mode's own effect.
    from ecs.db import get_connection, insert_star, insert_empire
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "star.png", 30)   # id 1
        insert_empire(conn, "P", "Alkari", "blue", 1, 0)       # id 1
        conn.commit()

    em = EntityManager()
    cm = ComponentManager()
    emp = Empire(id=1, name="P", race_type="Alkari", color="blue",
                 tech_level=0, home_star_id=1, bc=0, research_points=0,
                 is_player=True)
    emp_e = em.create_entity()
    cm.add_component(emp_e, emp)
    cm.add_component(emp_e, TechState(empire_id=1, unlocked=[]))

    star_e = em.create_entity()
    cm.add_component(star_e, StarRef(db_id=1))

    planet_e = em.create_entity()
    cm.add_component(planet_e, Planet(id=1, planet_type="Terran", size="Medium",
                                      colonizable=True, richness="Abundant"))
    cm.add_component(planet_e, Owner(empire_id=1))
    cm.add_component(planet_e, Population(current=pop_current, max=pop_max,
                                          workers=workers))
    cm.add_component(planet_e, Orbiting(star_entity=star_e))
    cm.add_component(planet_e, BuildState(current_project=current_project,
                                          progress=0))

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, ship_designs=None,
                           leaders=None, diplomacy=None, turn_log=None,
                           galaxy=SimpleNamespace(difficulty="normal"))
    return game, cm, emp, planet_e


# ---- catalogue ---------------------------------------------------------

def test_modes_are_registered_zero_cost():
    for pid in ("trade_goods", "housing"):
        assert PROJECTS[pid]["type"] == "mode"
        assert PROJECTS[pid]["cost"] == 0
        assert PROJECTS[pid]["category"] == "economy"


# ---- Trade Goods -------------------------------------------------------

def test_trade_goods_converts_industry_to_bc(temp_db):
    game, cm, emp, _p = _world("trade_goods", workers=5)
    production_tick(game, new_turn=2)
    # 5 workers * industry 1 (Abundant Terran) = 5 BC.
    assert emp.bc == 5


def test_trade_goods_never_completes(temp_db):
    game, cm, emp, planet_e = _world("trade_goods", workers=5)
    production_tick(game, new_turn=2)
    bs = cm.get_component(planet_e, BuildState)
    assert bs.current_project == "trade_goods"      # still active
    assert "trade_goods" not in bs.completed
    assert bs.progress == 0                           # never accrues


# ---- Housing -----------------------------------------------------------

def test_housing_converts_industry_to_growth(temp_db):
    game, cm, emp, planet_e = _world("housing", pop_current=5, pop_max=12,
                                     workers=5)
    production_tick(game, new_turn=2)
    pop = cm.get_component(planet_e, Population)
    # 5 industry * rate -> growth_progress, and NO BC from the colony.
    assert pop.growth_progress == pytest.approx(5 * HOUSING_GROWTH_PER_INDUSTRY)
    assert emp.bc == 0


def test_housing_noop_on_full_colony(temp_db):
    game, cm, emp, planet_e = _world("housing", pop_current=12, pop_max=12,
                                     workers=12)
    production_tick(game, new_turn=2)
    pop = cm.get_component(planet_e, Population)
    assert pop.growth_progress == 0.0    # nowhere to grow
    assert emp.bc == 0                    # housing doesn't bank cash either


def test_housing_never_completes(temp_db):
    game, cm, emp, planet_e = _world("housing", workers=5)
    production_tick(game, new_turn=2)
    bs = cm.get_component(planet_e, BuildState)
    assert bs.current_project == "housing"
    assert "housing" not in bs.completed


# ---- HUD projection matches the tick -----------------------------------

def test_hud_counts_trade_goods_as_bc(temp_db):
    game, cm, _emp, _p = _world("trade_goods", workers=5)
    assert empire_per_turn(cm, 1)["bc"] == 5   # industry shows as BC


def test_hud_excludes_housing_from_bc(temp_db):
    game, cm, _emp, _p = _world("housing", workers=5)
    assert empire_per_turn(cm, 1)["bc"] == 0   # industry goes to growth

"""Government types + colony morale.

Governments are empire-wide policies unlocked by tech; morale is a
per-colony level (set by the government + conquest state) that scales
industry / research / trade output. Food is never affected.
"""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting, StarRef,
)
from ecs.government import (
    government_of, available_governments, government_pct, colony_morale,
    morale_output_mult, ai_preferred_government, DEFAULT_GOVERNMENT,
    MORALE_BASE,
)


# ---- engine ------------------------------------------------------------

def test_available_governments():
    assert available_governments([]) == ["dictatorship"]
    a = available_governments(["governance"])
    assert "democracy" in a and "imperium" not in a
    a2 = available_governments(["governance", "galactic_unification"])
    assert "democracy" in a2 and "imperium" in a2


def test_government_of_defaults_and_validates():
    e = Empire(id=1, name="x", race_type="Humans", color="blue",
               tech_level=0, home_star_id=1)
    assert government_of(e) == DEFAULT_GOVERNMENT
    e.government = "democracy"
    assert government_of(e) == "democracy"
    e.government = "nonsense"
    assert government_of(e) == DEFAULT_GOVERNMENT   # invalid -> default


def test_government_pct():
    assert government_pct("democracy") == (20, 10)
    assert government_pct("dictatorship") == (0, 0)
    assert government_pct("imperium") == (0, 0)


def test_morale_output_mult_endpoints():
    assert morale_output_mult(MORALE_BASE) == pytest.approx(1.0)
    assert morale_output_mult(100) == pytest.approx(1.25)
    assert morale_output_mult(0) == pytest.approx(0.75)


def _planet(conquered=False):
    p = Planet(id=1, planet_type="Terran", size="Medium", colonizable=True)
    if conquered:
        p.assimilation_progress = 50   # still assimilating
    return p


def test_colony_morale_native():
    assert colony_morale("dictatorship", _planet()) == 50
    assert colony_morale("democracy", _planet()) == 55
    assert colony_morale("imperium", _planet()) == 70


def test_colony_morale_conquered():
    # base 50 + gov morale + (-20 conquered + gov conquered_morale)
    assert colony_morale("dictatorship", _planet(conquered=True)) == 30
    assert colony_morale("democracy", _planet(conquered=True)) == 10
    assert colony_morale("imperium", _planet(conquered=True)) == 60


def test_ai_preferred_government():
    assert ai_preferred_government([]) == "dictatorship"
    assert ai_preferred_government(["governance"]) == "democracy"
    assert ai_preferred_government(
        ["governance", "galactic_unification"]) == "imperium"


# ---- economy integration ----------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "gov.db")
    db.init_db()
    yield


def _world(government="dictatorship", workers=0, scientists=0, conquered=False):
    """Player colony (Alkari — no output traits). Returns (game, emp, cm)."""
    from ecs.db import get_connection, insert_star, insert_empire
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        insert_empire(conn, "P", "Alkari", "blue", 1, 0)
        conn.commit()
    em = EntityManager()
    cm = ComponentManager()
    emp = Empire(id=1, name="P", race_type="Alkari", color="blue", tech_level=0,
                 home_star_id=1, bc=0, research_points=0, is_player=True,
                 government=government)
    cm.add_component(em.create_entity(), emp)
    cm.add_component(next(e for e, c in cm.get_all(Empire)),
                     TechState(empire_id=1, unlocked=[]))
    star = em.create_entity()
    cm.add_component(star, StarRef(db_id=1))
    planet = em.create_entity()
    p = Planet(id=1, planet_type="Terran", size="Medium", colonizable=True,
               richness="Abundant")
    if conquered:
        p.assimilation_progress = 50
    cm.add_component(planet, p)
    cm.add_component(planet, Owner(empire_id=1))
    cm.add_component(planet, Population(current=max(1, workers + scientists),
                                        max=20, workers=workers,
                                        scientists=scientists))
    cm.add_component(planet, Orbiting(star_entity=star))
    cm.add_component(planet, BuildState(current_project=None))
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, ship_designs=None,
                           leaders=None, diplomacy=None, turn_log=None,
                           galaxy=SimpleNamespace(difficulty="normal"))
    return game, emp, cm


def test_imperium_morale_boosts_output(temp_db):
    from ecs.economy import production_tick
    # 10 workers -> 10 industry -> BC when idle. Imperium morale 70 -> 1.1x.
    dg, demp, _ = _world(government="dictatorship", workers=10)
    production_tick(dg, new_turn=2)
    ig, iemp, _ = _world(government="imperium", workers=10)
    production_tick(ig, new_turn=2)
    assert demp.bc == 10            # morale 50 -> 1.0x
    assert iemp.bc == 11            # morale 70 -> 1.1x (10*1.1=11)


def test_democracy_research_and_bc_pct(temp_db):
    from ecs.economy import production_tick
    # 6 scientists -> 6 research. Democracy: morale 55 (~1.025x) then +20%.
    dg, demp, _ = _world(government="dictatorship", scientists=6)
    production_tick(dg, new_turn=2)
    eg, eemp, _ = _world(government="democracy", scientists=6)
    production_tick(eg, new_turn=2)
    assert demp.research_points == 6
    assert eemp.research_points == 7   # 6 * 1.2 = 7.2 -> 7


def test_hud_projection_matches_tick_under_government(temp_db):
    """REGRESSION: empire_per_turn (HUD) must fold in morale + government
    %s so the displayed per-turn numbers match what production_tick banks."""
    from ecs.economy import empire_per_turn, production_tick
    # Imperium: 10 workers, morale 70 -> 1.1x -> 11 BC.
    g, emp, cm = _world(government="imperium", workers=10)
    proj = empire_per_turn(cm, 1)
    production_tick(g, new_turn=2)
    assert proj["bc"] == emp.bc == 11
    # Democracy: 6 scientists, morale 1.025x then +20% -> 7 research.
    g2, emp2, cm2 = _world(government="democracy", scientists=6)
    proj2 = empire_per_turn(cm2, 1)
    production_tick(g2, new_turn=2)
    assert proj2["research"] == emp2.research_points == 7


def test_conquered_colony_morale_penalty(temp_db):
    from ecs.economy import production_tick
    # Dictatorship, conquered colony: morale 30 -> 0.9x on 10 industry.
    g, emp, _ = _world(government="dictatorship", workers=10, conquered=True)
    production_tick(g, new_turn=2)
    assert emp.bc == 9             # round(10 * 0.9)


# ---- persistence -------------------------------------------------------

def test_government_persists(temp_db):
    from ecs.db import (get_connection, insert_star, insert_empire,
                        update_empire_government, get_empires)
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        eid = insert_empire(conn, "P", "Humans", "blue", 1, 0)
        conn.commit()
    with get_connection() as conn:
        update_empire_government(conn, eid, "imperium")
        conn.commit()
    row = next(r for r in get_empires() if r["id"] == eid)
    assert row["government"] == "imperium"


def test_new_empire_defaults_to_dictatorship(temp_db):
    from ecs.db import (get_connection, insert_star, insert_empire,
                        get_empires)
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        eid = insert_empire(conn, "P", "Humans", "blue", 1, 0)
        conn.commit()
    row = next(r for r in get_empires() if r["id"] == eid)
    assert row["government"] == "dictatorship"

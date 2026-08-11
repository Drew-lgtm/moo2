"""Research queue: line up several techs; the next still-valid one
becomes the target automatically when the current research completes."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting, StarRef,
)
from ecs.techs import TECHS


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rq.db")
    db.init_db()
    yield


def _world(target, queue, scientists=200, unlocked=None):
    """Player colony with a huge science output so research completes in
    one tick. Returns (game, tech_state)."""
    from ecs.db import get_connection, insert_star, insert_empire
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        insert_empire(conn, "P", "Alkari", "blue", 1, 0)
        conn.commit()
    em = EntityManager(); cm = ComponentManager()
    emp_e = em.create_entity()
    cm.add_component(emp_e, Empire(id=1, name="P", race_type="Alkari",
                                   color="blue", tech_level=0, home_star_id=1,
                                   bc=0, research_points=0, is_player=True))
    ts = TechState(empire_id=1, current_target=target, progress=0,
                   unlocked=list(unlocked or []), queue=list(queue))
    cm.add_component(emp_e, ts)
    star = em.create_entity(); cm.add_component(star, StarRef(db_id=1))
    planet = em.create_entity()
    cm.add_component(planet, Planet(id=1, planet_type="Terran", size="Medium",
                                    colonizable=True, richness="Abundant"))
    cm.add_component(planet, Owner(empire_id=1))
    cm.add_component(planet, Population(current=scientists, max=500,
                                        scientists=scientists))
    cm.add_component(planet, Orbiting(star_entity=star))
    cm.add_component(planet, BuildState(current_project=None))
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, ship_designs=None,
                           leaders=None, diplomacy=None, turn_log=None,
                           galaxy=SimpleNamespace(difficulty="normal"))
    return game, ts


def test_queue_advances_on_completion(temp_db):
    from ecs.economy import production_tick
    # Different tier groups, so completing one doesn't lock out the other.
    game, ts = _world("laser_cannons", ["anti_missile_rockets"])
    production_tick(game, new_turn=2)
    assert "laser_cannons" in ts.unlocked
    assert ts.current_target == "anti_missile_rockets"   # pulled off the queue
    assert ts.queue == []


def test_queue_skips_entries_invalidated_by_the_unlock(temp_db):
    """MOO2's tier-choice rule locks out the alternatives of whatever you
    just researched. A queued entry that gets locked out must be skipped,
    not left as a dead target that stalls research."""
    from ecs.economy import production_tick
    # death_ray is an alternative of laser_cannons -> locked out on unlock.
    game, ts = _world("laser_cannons", ["death_ray", "anti_missile_rockets"])
    production_tick(game, new_turn=2)
    assert "death_ray" in ts.locked_out
    assert ts.current_target == "anti_missile_rockets"


def test_queue_skips_already_unlocked_entries(temp_db):
    from ecs.economy import production_tick
    game, ts = _world("laser_cannons", ["titanium_armor", "anti_missile_rockets"],
                      unlocked=["titanium_armor"])
    production_tick(game, new_turn=2)
    assert ts.current_target == "anti_missile_rockets"


def test_queue_persists(temp_db):
    from ecs.db import (get_connection, save_empire_tech_queue,
                        get_empire_tech_queue)
    with get_connection() as conn:
        save_empire_tech_queue(conn, 1, ["death_ray", "phasors"])
        conn.commit()
    with get_connection() as conn:
        assert get_empire_tech_queue(conn, 1) == ["death_ray", "phasors"]
    # Re-saving replaces rather than appends.
    with get_connection() as conn:
        save_empire_tech_queue(conn, 1, ["phasors"])
        conn.commit()
    with get_connection() as conn:
        assert get_empire_tech_queue(conn, 1) == ["phasors"]


def test_empty_queue_leaves_research_idle(temp_db):
    from ecs.economy import production_tick
    game, ts = _world("laser_cannons", [])
    production_tick(game, new_turn=2)
    assert "laser_cannons" in ts.unlocked
    assert ts.current_target is None


# ---- UI click behaviour ------------------------------------------------

def _scene(ts):
    """An InfoScene wired to a fake game exposing this tech state."""
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    pygame.init()
    from ecs.scenes.panels import InfoScene
    cm = ComponentManager(); em = EntityManager()
    e = em.create_entity()
    cm.add_component(e, Empire(id=1, name="P", race_type="Humans", color="blue",
                               tech_level=0, home_star_id=1, is_player=True))
    cm.add_component(e, ts)
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em,
                           screen_width=1200, screen_height=800)
    game.player_empire = lambda: next(x for _i, x in cm.get_all(Empire))
    scene = InfoScene.__new__(InfoScene)     # skip heavy __init__
    scene.game = game
    return scene


def test_click_queues_when_something_is_researching(temp_db):
    ts = TechState(empire_id=1, current_target="laser_cannons")
    s = _scene(ts)
    s._set_tech_target(ts, "death_ray")
    assert ts.current_target == "laser_cannons"
    assert ts.queue == ["death_ray"]


def test_click_sets_target_when_idle(temp_db):
    ts = TechState(empire_id=1, current_target=None)
    s = _scene(ts)
    s._set_tech_target(ts, "death_ray")
    assert ts.current_target == "death_ray" and ts.queue == []


def test_repeat_click_unqueues(temp_db):
    ts = TechState(empire_id=1, current_target="laser_cannons",
                   queue=["death_ray"])
    s = _scene(ts)
    s._set_tech_target(ts, "death_ray")
    assert ts.queue == []


def test_cancelling_target_promotes_the_queue(temp_db):
    ts = TechState(empire_id=1, current_target="laser_cannons",
                   queue=["death_ray", "phasors"])
    s = _scene(ts)
    s._set_tech_target(ts, "laser_cannons")     # click the active one
    assert ts.current_target == "death_ray"
    assert ts.queue == ["phasors"]

"""AI strategic depth: blockading rival colonies, chasing point-defense
when rivals field missiles, and taking its own shot at Antares."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting,
    Ship, ShipOwner, ShipAt, ShipInTransit, StarRef, Position,
)
from ecs.ai import (
    _ai_blockade, _rivals_field_missiles, _ai_wants_portal,
    _ai_maybe_assault_antares, AI_BLOCKADE_MIN_FLEET, AI_ANTARES_MIN_FLEET,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ais.db")
    db.init_db()
    yield


def _war(at_war=True):
    return SimpleNamespace(at_war=lambda a, b: at_war)


def _base():
    em = EntityManager(); cm = ComponentManager()
    for eid, col in ((1, "green"), (2, "red")):
        e = em.create_entity()
        cm.add_component(e, Empire(id=eid, name=str(eid), race_type="Humans",
                                   color=col, tech_level=0, home_star_id=1,
                                   is_player=False))
    return em, cm


def _star(em, cm, db_id, x):
    s = em.create_entity()
    cm.add_component(s, StarRef(db_id=db_id))
    cm.add_component(s, Position(x=x, y=0))
    return s


def _colony(em, cm, star, owner_id, pid=1):
    p = em.create_entity()
    cm.add_component(p, Planet(id=pid, planet_type="Terran", size="Medium",
                               colonizable=True))
    cm.add_component(p, Owner(empire_id=owner_id))
    cm.add_component(p, Population(current=8, max=12, workers=8))
    cm.add_component(p, Orbiting(star_entity=star))
    cm.add_component(p, BuildState(current_project=None))
    return p


def _fleet(em, cm, star, empire_id, n, cls="cruiser", **kw):
    out = []
    for i in range(n):
        e = em.create_entity()
        cm.add_component(e, Ship(id=len(out) + i + 1 + empire_id * 100,
                                 ship_class=cls, **kw))
        cm.add_component(e, ShipOwner(empire_id=empire_id))
        cm.add_component(e, ShipAt(star_entity=star))
        out.append(e)
    return out


def _empire(cm, eid=1):
    return next(e for _x, e in cm.get_all(Empire) if e.id == eid)


# ---- blockade ----------------------------------------------------------

def test_ai_blockades_an_enemy_colony(temp_db):
    em, cm = _base()
    home = _star(em, cm, 1, 0)
    enemy = _star(em, cm, 2, 80)
    _colony(em, cm, enemy, owner_id=2)
    ships = _fleet(em, cm, home, 1, AI_BLOCKADE_MIN_FLEET * 2)
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, diplomacy=_war(True))
    _ai_blockade(game, _empire(cm), None)
    sent = [s for s in ships if cm.get_component(s, ShipInTransit) is not None]
    assert sent, "a detachment should head for the enemy colony"
    assert all(cm.get_component(s, ShipInTransit).to_star_entity == enemy
               for s in sent)
    # It keeps a reserve at home rather than committing everything.
    assert any(cm.get_component(s, ShipAt) is not None for s in ships)


def test_no_blockade_when_at_peace(temp_db):
    em, cm = _base()
    home = _star(em, cm, 1, 0)
    enemy = _star(em, cm, 2, 80)
    _colony(em, cm, enemy, owner_id=2)
    ships = _fleet(em, cm, home, 1, AI_BLOCKADE_MIN_FLEET * 2)
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, diplomacy=_war(False))
    _ai_blockade(game, _empire(cm), None)
    assert all(cm.get_component(s, ShipInTransit) is None for s in ships)


def test_no_blockade_without_a_real_detachment(temp_db):
    em, cm = _base()
    home = _star(em, cm, 1, 0)
    enemy = _star(em, cm, 2, 80)
    _colony(em, cm, enemy, owner_id=2)
    ships = _fleet(em, cm, home, 1, AI_BLOCKADE_MIN_FLEET - 1)
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, diplomacy=_war(True))
    _ai_blockade(game, _empire(cm), None)
    assert all(cm.get_component(s, ShipInTransit) is None for s in ships)


def test_does_not_re_blockade_a_colony_it_already_holds(temp_db):
    em, cm = _base()
    enemy = _star(em, cm, 2, 80)
    _colony(em, cm, enemy, owner_id=2)
    ships = _fleet(em, cm, enemy, 1, AI_BLOCKADE_MIN_FLEET * 2)  # already there
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, diplomacy=_war(True))
    _ai_blockade(game, _empire(cm), None)
    assert all(cm.get_component(s, ShipInTransit) is None for s in ships)


# ---- counter-design cue ------------------------------------------------

def test_detects_a_rival_missile_threat():
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    _fleet(em, cm, star, 2, 1, cls="cruiser",
           weapon_tech="nuclear_missile", weapon_count=2)
    assert _rivals_field_missiles(cm, 1) is True


def test_detects_a_rival_carrier_threat():
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    _fleet(em, cm, star, 2, 1, cls="carrier")     # hull fighter_attack
    assert _rivals_field_missiles(cm, 1) is True


def test_beam_only_rivals_are_not_a_missile_threat():
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    _fleet(em, cm, star, 2, 1, cls="cruiser",
           weapon_tech="laser_cannons", weapon_count=2)
    assert _rivals_field_missiles(cm, 1) is False


def test_own_missile_ships_are_not_a_threat_to_self():
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    _fleet(em, cm, star, 1, 1, cls="cruiser",
           weapon_tech="nuclear_missile", weapon_count=2)
    assert _rivals_field_missiles(cm, 1) is False


def test_point_defense_tech_is_prioritised_under_missile_threat():
    from ecs.ai import _score_tech
    from ecs.personalities import get as get_personality
    p = get_personality("balanced")
    e = _base()[1]
    empire = next(x for _i, x in e.get_all(Empire))
    empire._ai_missile_threat = False
    calm = _score_tech("anti_missile_rockets", empire, p, [], None, set())
    empire._ai_missile_threat = True
    alarmed = _score_tech("anti_missile_rockets", empire, p, [], None, set())
    assert alarmed > calm


# ---- Dimensional Portal ------------------------------------------------

def test_wants_a_portal_once_the_tech_lands():
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    p = _colony(em, cm, star, owner_id=1)
    assert _ai_wants_portal(cm, _empire(cm), set(), [p]) is False
    assert _ai_wants_portal(cm, _empire(cm), {"dimensional_portal"}, [p]) is True


def test_stops_wanting_one_after_it_is_built():
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    p = _colony(em, cm, star, owner_id=1)
    cm.get_component(p, BuildState).completed.append("dimensional_portal")
    assert _ai_wants_portal(cm, _empire(cm), {"dimensional_portal"}, [p]) is False


def test_ai_holds_back_the_assault_without_a_fleet(temp_db):
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    p = _colony(em, cm, star, owner_id=1)
    cm.get_component(p, BuildState).completed.append("dimensional_portal")
    _fleet(em, cm, star, 1, 2)          # far short of AI_ANTARES_MIN_FLEET
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           pending_endgame=None,
                           galaxy=SimpleNamespace(turn=200))
    game.player_empire = lambda: None
    _ai_maybe_assault_antares(game, _empire(cm), {"dimensional_portal"})
    assert game.pending_endgame is None      # didn't throw its fleet away


def test_ai_launches_the_assault_with_a_real_fleet(temp_db):
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    p = _colony(em, cm, star, owner_id=1)
    cm.get_component(p, BuildState).completed.append("dimensional_portal")
    _fleet(em, cm, star, 1, AI_ANTARES_MIN_FLEET, cls="doom_star",
           weapon_tech="death_ray", weapon_count=4, weapon_mount="heavy")
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           pending_endgame=None, leaders=None,
                           galaxy=SimpleNamespace(turn=200))
    game.player_empire = lambda: None
    _ai_maybe_assault_antares(game, _empire(cm), {"dimensional_portal"})
    # It committed: either it won (endgame stamped) or lost ships trying.
    launched = (game.pending_endgame is not None
                or sum(1 for _e, o in cm.get_all(ShipOwner)
                       if o.empire_id == 1) < AI_ANTARES_MIN_FLEET)
    assert launched


# ---- review-hardening --------------------------------------------------

def test_only_one_colony_builds_the_portal(temp_db):
    """REGRESSION: _ai_wants_portal only checked COMPLETED portals, so
    every idle colony started its own 1200-industry copy."""
    em, cm = _base()
    star = _star(em, cm, 1, 0)
    a = _colony(em, cm, star, owner_id=1, pid=1)
    b = _colony(em, cm, star, owner_id=1, pid=2)
    unlocked = {"dimensional_portal"}
    assert _ai_wants_portal(cm, _empire(cm), unlocked, [a, b]) is True
    # One colony starts building it -> the empire no longer wants another.
    cm.get_component(a, BuildState).current_project = "dimensional_portal"
    assert _ai_wants_portal(cm, _empire(cm), unlocked, [a, b]) is False
    # Same when it's merely queued.
    cm.get_component(a, BuildState).current_project = None
    cm.get_component(a, BuildState).queue.append("dimensional_portal")
    assert _ai_wants_portal(cm, _empire(cm), unlocked, [a, b]) is False


def test_blockaders_are_not_re_tasked_away(temp_db):
    """REGRESSION: _ai_dispatch_ships pulled the siege off an enemy colony
    the turn after _ai_blockade put it there."""
    from ecs.ai import _ai_dispatch_ships
    em, cm = _base()
    enemy_colony = _star(em, cm, 2, 80)
    _colony(em, cm, enemy_colony, owner_id=2)
    # Player homeworld (empire 2 is the "player" target here is irrelevant —
    # what matters is the blockaders stay put).
    ships = _fleet(em, cm, enemy_colony, 1, 4)
    _ai_dispatch_ships(cm, _empire(cm), None, diplo=_war(True))
    for s in ships:
        assert cm.get_component(s, ShipInTransit) is None

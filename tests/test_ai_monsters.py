"""AI strategic depth: expansionist AIs clear space-monster guardians to
open rich systems, but only commit a fleet big enough to have a chance."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, Ship, ShipOwner, ShipAt, ShipInTransit, StarRef, Position,
    Planet, Orbiting,
)
from ecs.ai import _ai_clear_monsters, AI_MONSTER_CLEAR_MIN_FLEET
from ecs.monsters import MONSTER_EMPIRE_ID


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "aimon.db")
    db.init_db()
    yield


def _world(n_warships, with_monster=True):
    em = EntityManager(); cm = ComponentManager()
    cm.add_component(em.create_entity(),
                     Empire(id=1, name="AI", race_type="Humans", color="green",
                            tech_level=0, home_star_id=1, is_player=False))
    home = em.create_entity()
    cm.add_component(home, StarRef(db_id=1)); cm.add_component(home, Position(x=0, y=0))
    guarded = em.create_entity()
    cm.add_component(guarded, StarRef(db_id=2))
    cm.add_component(guarded, Position(x=120, y=0))
    planet = em.create_entity()
    cm.add_component(planet, Planet(id=1, planet_type="Terran", size="Medium",
                                    colonizable=True))
    cm.add_component(planet, Orbiting(star_entity=guarded))
    if with_monster:
        mon = em.create_entity()
        cm.add_component(mon, Ship(id=-8000, ship_class="battleship"))
        cm.add_component(mon, ShipOwner(empire_id=MONSTER_EMPIRE_ID))
        cm.add_component(mon, ShipAt(star_entity=guarded))
    warships = []
    for i in range(n_warships):
        e = em.create_entity()
        cm.add_component(e, Ship(id=i + 1, ship_class="cruiser"))
        cm.add_component(e, ShipOwner(empire_id=1))
        cm.add_component(e, ShipAt(star_entity=home))
        warships.append(e)
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em)
    return game, cm, home, guarded, warships


def _empire(cm):
    return next(e for _x, e in cm.get_all(Empire))


def test_strong_fleet_storms_the_guardian(temp_db):
    game, cm, home, guarded, warships = _world(AI_MONSTER_CLEAR_MIN_FLEET)
    _ai_clear_monsters(game, _empire(cm), None)
    for e in warships:
        t = cm.get_component(e, ShipInTransit)
        assert t is not None and t.to_star_entity == guarded


def test_small_fleet_stays_home(temp_db):
    game, cm, home, guarded, warships = _world(AI_MONSTER_CLEAR_MIN_FLEET - 1)
    _ai_clear_monsters(game, _empire(cm), None)
    for e in warships:
        assert cm.get_component(e, ShipInTransit) is None
        assert cm.get_component(e, ShipAt) is not None


def test_no_guardian_no_dispatch(temp_db):
    game, cm, home, guarded, warships = _world(AI_MONSTER_CLEAR_MIN_FLEET,
                                               with_monster=False)
    _ai_clear_monsters(game, _empire(cm), None)
    for e in warships:
        assert cm.get_component(e, ShipInTransit) is None


def test_unreachable_guardian_not_targeted(temp_db):
    game, cm, home, guarded, warships = _world(AI_MONSTER_CLEAR_MIN_FLEET)
    _ai_clear_monsters(game, _empire(cm), reachable=set())  # nothing reachable
    for e in warships:
        assert cm.get_component(e, ShipInTransit) is None

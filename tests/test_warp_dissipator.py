"""Warp Dissipator: a hostile fielding it pins enemy fleets in-system —
they must fight or die rather than jumping away."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Ship, ShipOwner, ShipAt, ShipInTransit, StarRef, Position, TechState,
)
from ecs.fleet import start_fleet_movement, warp_dissipator_blocks, WARP_DISSIPATOR


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "wd.db")
    db.init_db()
    yield


def _war(at_war=True):
    return SimpleNamespace(at_war=lambda a, b: at_war)


def _world(enemy_has_tech=True, enemy_class="cruiser", enemy_present=True):
    """Player fleet (empire 1) at star A; enemy (empire 2) optionally
    present there with the Warp Dissipator. Returns (cm, em, A, B, ships)."""
    em = EntityManager(); cm = ComponentManager()
    a = em.create_entity()
    cm.add_component(a, StarRef(db_id=1)); cm.add_component(a, Position(x=0, y=0))
    b = em.create_entity()
    cm.add_component(b, StarRef(db_id=2)); cm.add_component(b, Position(x=60, y=0))
    # Tech state for both empires.
    e1 = em.create_entity()
    cm.add_component(e1, TechState(empire_id=1, unlocked=[]))
    e2 = em.create_entity()
    cm.add_component(e2, TechState(empire_id=2,
                                   unlocked=[WARP_DISSIPATOR] if enemy_has_tech else []))
    ships = []
    for i in range(2):
        s = em.create_entity()
        cm.add_component(s, Ship(id=i + 1, ship_class="cruiser"))
        cm.add_component(s, ShipOwner(empire_id=1))
        cm.add_component(s, ShipAt(star_entity=a))
        ships.append(s)
    if enemy_present:
        e = em.create_entity()
        cm.add_component(e, Ship(id=99, ship_class=enemy_class))
        cm.add_component(e, ShipOwner(empire_id=2))
        cm.add_component(e, ShipAt(star_entity=a))
    return cm, em, a, b, ships


# ---- the predicate -----------------------------------------------------

def test_hostile_with_tech_pins():
    cm, _em, a, _b, _s = _world()
    assert warp_dissipator_blocks(cm, a, 1, _war(True)) is True


def test_no_tech_no_pin():
    cm, _em, a, _b, _s = _world(enemy_has_tech=False)
    assert warp_dissipator_blocks(cm, a, 1, _war(True)) is False


def test_at_peace_no_pin():
    cm, _em, a, _b, _s = _world()
    assert warp_dissipator_blocks(cm, a, 1, _war(False)) is False


def test_civilian_hull_cannot_pin():
    cm, _em, a, _b, _s = _world(enemy_class="colony_ship")
    assert warp_dissipator_blocks(cm, a, 1, _war(True)) is False


def test_no_enemy_present_no_pin():
    cm, _em, a, _b, _s = _world(enemy_present=False)
    assert warp_dissipator_blocks(cm, a, 1, _war(True)) is False


def test_without_diplomacy_nothing_is_pinned():
    """Old saves / headless callers pass no diplomacy — movement must
    behave exactly as before."""
    cm, _em, a, _b, _s = _world()
    assert warp_dissipator_blocks(cm, a, 1, None) is False


# ---- movement gate -----------------------------------------------------

def test_pinned_fleet_cannot_depart(temp_db):
    cm, _em, a, b, ships = _world()
    moved = start_fleet_movement(cm, ships, a, b, diplo=_war(True))
    assert moved is False
    for s in ships:
        assert cm.get_component(s, ShipInTransit) is None
        assert cm.get_component(s, ShipAt).star_entity == a


def test_unpinned_fleet_departs(temp_db):
    cm, _em, a, b, ships = _world(enemy_has_tech=False)
    moved = start_fleet_movement(cm, ships, a, b, diplo=_war(True))
    assert moved is True
    for s in ships:
        assert cm.get_component(s, ShipInTransit) is not None


def test_movement_without_diplo_is_unchanged(temp_db):
    cm, _em, a, b, ships = _world()      # enemy HAS the tech
    assert start_fleet_movement(cm, ships, a, b) is True   # no diplo -> no gate


def test_tech_is_no_longer_a_stub():
    from ecs.techs import TECHS
    assert not TECHS[WARP_DISSIPATOR].get("effect_stub")

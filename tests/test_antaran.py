"""Antaran raiders: faction identity, raid scheduling/targeting,
despawn, and that raiders are hostile to a defending empire in combat."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, Owner, Population, Orbiting, StarRef, Name, Ship, ShipOwner, ShipAt,
)
from ecs.antaran import (
    is_antaran, ensure_antaran_empire, antaran_tick, _raid_ship_count,
    ANTARAN_EMPIRE_ID, RAID_FIRST_TURN, RAID_INTERVAL, RAID_DURATION,
    RAID_MAX_SHIPS,
)


def _fake_game(colonies):
    """colonies: list of (owner_id, pop). Builds a star per colony."""
    em = EntityManager()
    cm = ComponentManager()
    owners = {o for o, _ in colonies}
    for oid in owners:
        e = em.create_entity()
        cm.add_component(e, Empire(id=oid, name=f"E{oid}", race_type="Humans",
                                   color="blue", tech_level=0, home_star_id=1,
                                   is_player=(oid == 1)))
    stars = []
    for i, (oid, pop) in enumerate(colonies):
        star = em.create_entity()
        cm.add_component(star, StarRef(db_id=i + 1))
        cm.add_component(star, Name(f"Star{i}"))
        planet = em.create_entity()
        cm.add_component(planet, Owner(empire_id=oid))
        cm.add_component(planet, Population(current=pop, max=20, workers=pop))
        cm.add_component(planet, Orbiting(star_entity=star))
        stars.append(star)
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           antaran_raid=None,
                           galaxy=SimpleNamespace(turn=RAID_FIRST_TURN))
    game.player_empire = lambda: next(
        (e for _x, e in cm.get_all(Empire) if e.is_player), None)
    return game, cm, stars


# ---- identity ----------------------------------------------------------

def test_is_antaran():
    assert is_antaran(ANTARAN_EMPIRE_ID)
    assert not is_antaran(1)


def test_ensure_creates_single_empire():
    game, cm, _ = _fake_game([(1, 5)])
    ensure_antaran_empire(game)
    ensure_antaran_empire(game)  # idempotent
    ants = [e for _x, e in cm.get_all(Empire) if e.id == ANTARAN_EMPIRE_ID]
    assert len(ants) == 1
    assert ants[0].race_type == "Antaran"


# ---- scheduling + scaling ----------------------------------------------

def test_raid_ship_count_scales_and_caps():
    assert _raid_ship_count(0) >= 2
    assert _raid_ship_count(400) == RAID_MAX_SHIPS  # capped
    assert _raid_ship_count(80) >= _raid_ship_count(40)


def test_no_raid_before_first_turn():
    game, cm, _ = _fake_game([(1, 10)])
    antaran_tick(game, RAID_FIRST_TURN - 1)
    assert game.antaran_raid is None


def test_raid_spawns_on_schedule_at_strongest_colony():
    # Two colonies; the bigger one (empire 2, pop 15) is the target.
    game, cm, stars = _fake_game([(1, 5), (2, 15)])
    antaran_tick(game, RAID_FIRST_TURN)
    assert game.antaran_raid is not None
    raid = game.antaran_raid
    assert raid["star"] == stars[1]  # the pop-15 colony
    # Raider ships exist, Antaran-owned, at the target star.
    raiders = [e for e, owner in cm.get_all(ShipOwner)
               if owner.empire_id == ANTARAN_EMPIRE_ID]
    assert len(raiders) == _raid_ship_count(RAID_FIRST_TURN)
    for e in raiders:
        at = cm.get_component(e, ShipAt)
        assert at.star_entity == stars[1]


def test_raid_despawns_after_window():
    game, cm, _ = _fake_game([(1, 10)])
    antaran_tick(game, RAID_FIRST_TURN)
    assert game.antaran_raid is not None
    # After the duration, the raid retreats.
    antaran_tick(game, RAID_FIRST_TURN + RAID_DURATION)
    assert game.antaran_raid is None
    assert not any(owner.empire_id == ANTARAN_EMPIRE_ID
                   for _e, owner in cm.get_all(ShipOwner))


def test_raid_despawns_when_all_raiders_dead():
    game, cm, _ = _fake_game([(1, 10)])
    antaran_tick(game, RAID_FIRST_TURN)
    # Simulate the defender wiping the fleet: strip all raider ships.
    for e in list(game.antaran_raid["entities"]):
        cm.remove_component(e, Ship)
    antaran_tick(game, RAID_FIRST_TURN + 1)  # still within window
    assert game.antaran_raid is None


# ---- combat hostility (integration) ------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ant.db")
    db.init_db()
    yield


def test_raiders_destroy_a_defending_ai_ship(temp_db):
    """A raid over an AI colony defended by a single weak frigate: the
    Antaran fleet is hostile and destroys the defender in the strategic
    resolver (no player ships → no tactical hand-off)."""
    from ecs.db import get_connection, insert_star, insert_empire, insert_ship
    from ecs.combat import combat_tick
    with get_connection() as conn:
        insert_star(conn, "Vega", 0, 0, "G", "s.png", 30)   # id 1
        insert_empire(conn, "AI", "Humans", "green", 1, 0)   # id 1 (defender)
        conn.commit()

    em = EntityManager()
    cm = ComponentManager()
    # Defender empire (NOT the player, so combat auto-resolves).
    de = em.create_entity()
    cm.add_component(de, Empire(id=1, name="AI", race_type="Humans",
                               color="green", tech_level=0, home_star_id=1,
                               is_player=False))
    star = em.create_entity()
    cm.add_component(star, StarRef(db_id=1))
    cm.add_component(star, Name("Vega"))
    planet = em.create_entity()
    cm.add_component(planet, Owner(empire_id=1))
    cm.add_component(planet, Population(current=8, max=12, workers=8))
    cm.add_component(planet, Orbiting(star_entity=star))
    # One weak defending frigate.
    fe = em.create_entity()
    with get_connection() as conn:
        sid = insert_ship(conn, 1, "frigate", 1)
        conn.commit()
    cm.add_component(fe, Ship(id=sid, ship_class="frigate"))
    cm.add_component(fe, ShipOwner(empire_id=1))
    cm.add_component(fe, ShipAt(star_entity=star))

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           antaran_raid=None, diplomacy=None, leaders=None,
                           last_combats=[], pending_combat_reports=None,
                           pending_engagements=None,
                           galaxy=SimpleNamespace(turn=RAID_FIRST_TURN))
    game.player_empire = lambda: None

    antaran_tick(game, RAID_FIRST_TURN)      # raiders arrive at Vega
    combat_tick(game, RAID_FIRST_TURN)       # fight resolves

    # The lone frigate is destroyed by the Antaran battleships.
    assert cm.get_component(fe, Ship) is None

"""Space-monster system guardians: spawn on rich unowned systems, block
colonisation, persist across save/load, and pay a bounty when cleared.
Also pins the endgame fix that must NOT scrap pseudo-empire fleets."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, Owner, Planet, Population, Orbiting, StarRef, Name,
    Ship, ShipOwner, ShipAt,
)
from ecs.monsters import (
    is_monster, is_pseudo_empire, spawn_guardians, load_guardians, monster_tick,
    monster_at_star, reconcile_kills, ensure_monster_empire,
    MONSTER_EMPIRE_ID, GUARDIAN_SHIPS_PER, KILL_REWARD_BC, KILL_REWARD_RESEARCH,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "monsters.db")
    db.init_db()
    yield


def _world(n_unowned=2):
    """A player empire (id 1) with a home system (star 0, owned planet)
    plus ``n_unowned`` unowned systems each with one colonisable planet.
    Returns (game, cm, [star_entity...])."""
    em = EntityManager()
    cm = ComponentManager()
    emp = Empire(id=1, name="P", race_type="Humans", color="blue",
                 tech_level=0, home_star_id=1, bc=0, research_points=0,
                 is_player=True)
    cm.add_component(em.create_entity(), emp)

    stars = []
    pid = 1
    total = n_unowned + 1
    for i in range(total):
        star = em.create_entity()
        cm.add_component(star, StarRef(db_id=i + 1))
        cm.add_component(star, Name(f"Star{i}"))
        planet = em.create_entity()
        cm.add_component(planet, Planet(id=pid, planet_type="Terran",
                                        size="Medium", colonizable=True))
        cm.add_component(planet, Orbiting(star_entity=star))
        if i == 0:
            # Home system: owned → excluded from guardian candidates.
            cm.add_component(planet, Owner(empire_id=1))
            cm.add_component(planet, Population(current=6, max=12, workers=6))
        pid += 1
        stars.append(star)

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           space_monsters=[],
                           galaxy=SimpleNamespace(turn=1))
    game.player_empire = lambda: next(
        (e for _x, e in cm.get_all(Empire) if e.is_player), None)
    return game, cm, stars


# ---- identity ----------------------------------------------------------

def test_is_monster():
    assert is_monster(MONSTER_EMPIRE_ID)
    assert not is_monster(1)


def test_is_pseudo_empire():
    from ecs.antaran import ANTARAN_EMPIRE_ID
    assert is_pseudo_empire(MONSTER_EMPIRE_ID)
    assert is_pseudo_empire(ANTARAN_EMPIRE_ID)
    assert not is_pseudo_empire(1)


# ---- spawn -------------------------------------------------------------

def test_spawn_places_guardian_on_unowned_system(temp_db):
    game, cm, stars = _world(n_unowned=2)
    spawn_guardians(game)
    assert len(game.space_monsters) == 1          # 3 systems -> 1 guardian
    g = game.space_monsters[0]
    assert g["star_entity"] in (stars[1], stars[2])   # never the home star
    assert g["star_entity"] != stars[0]
    # Guardian ships exist, monster-owned, at the target star.
    raiders = [e for e, o in cm.get_all(ShipOwner)
               if o.empire_id == MONSTER_EMPIRE_ID]
    assert len(raiders) == GUARDIAN_SHIPS_PER
    for e in raiders:
        assert cm.get_component(e, ShipAt).star_entity == g["star_entity"]


def test_spawn_records_to_db(temp_db):
    game, cm, stars = _world(n_unowned=2)
    spawn_guardians(game)
    from ecs.db import get_space_monsters
    rows = get_space_monsters(alive_only=True)
    assert len(rows) == 1
    assert rows[0]["monster_type"]


# ---- colonisation gate -------------------------------------------------

def test_guardian_blocks_colonisation(temp_db):
    from ecs.colonization import can_colonize
    from ecs.db import get_connection, insert_ship
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    g = game.space_monsters[0]
    star = g["star_entity"]
    planet_e = next(pe for pe, orb in cm.get_all(Orbiting)
                    if orb.star_entity == star)
    # Park a player colony ship at the guarded star.
    from ecs.colonization import COLONY_SHIP_CLASS
    se = game.entity_mgr.create_entity()
    cm.add_component(se, Ship(id=1, ship_class=COLONY_SHIP_CLASS))
    cm.add_component(se, ShipOwner(empire_id=1))
    cm.add_component(se, ShipAt(star_entity=star))
    assert monster_at_star(cm, star)
    assert can_colonize(cm, planet_e, 1) is False   # blocked by guardian
    # Remove the guardian → now colonisable.
    for e in list(g["entities"]):
        cm.remove_component(e, Ship)
        cm.remove_component(e, ShipOwner)
        cm.remove_component(e, ShipAt)
    assert not monster_at_star(cm, star)
    assert can_colonize(cm, planet_e, 1) is True


# ---- kill detection + reward ------------------------------------------

def test_monster_tick_marks_dead_and_rewards_victor(temp_db):
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    g = game.space_monsters[0]
    star = g["star_entity"]
    # Player warship present = the victor (ECS-only; the reward's DB
    # write is a harmless no-op UPDATE since this empire isn't persisted).
    we = game.entity_mgr.create_entity()
    cm.add_component(we, Ship(id=1, ship_class="battleship"))
    cm.add_component(we, ShipOwner(empire_id=1))
    cm.add_component(we, ShipAt(star_entity=star))
    # Simulate combat wiping the guardian ships.
    for e in list(g["entities"]):
        cm.remove_component(e, Ship)
    monster_tick(game, turn=2)
    # Guardian gone from the active list, DB row marked dead.
    assert game.space_monsters == []
    from ecs.db import get_space_monsters
    assert get_space_monsters(alive_only=True) == []
    # Reward paid to the player.
    player = game.player_empire()
    assert player.bc == KILL_REWARD_BC
    assert player.research_points == KILL_REWARD_RESEARCH


def test_monster_tick_survives_partial_losses(temp_db):
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    g = game.space_monsters[0]
    # Destroy only one of the guardian's ships.
    cm.remove_component(g["entities"][0], Ship)
    monster_tick(game, turn=2)
    assert len(game.space_monsters) == 1                 # still alive
    assert len(game.space_monsters[0]["entities"]) == GUARDIAN_SHIPS_PER - 1


# ---- persistence round-trip -------------------------------------------

def test_load_recreates_living_guardians(temp_db):
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    assert len(game.space_monsters) == 1
    # Fresh ECS (simulating a reload) sharing the same DB + star db_ids.
    game2, cm2, _stars2 = _world(n_unowned=1)
    load_guardians(game2)
    assert len(game2.space_monsters) == 1
    monsters = [e for e, o in cm2.get_all(ShipOwner)
                if o.empire_id == MONSTER_EMPIRE_ID]
    assert len(monsters) == GUARDIAN_SHIPS_PER


def test_partial_loss_persists_across_reload(temp_db):
    """REGRESSION: destroying part of a guardian's pack must persist, so
    a reload restores only the survivors, not the full pack."""
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    g = game.space_monsters[0]
    cm.remove_component(g["entities"][0], Ship)   # kill one of the pack
    reconcile_kills(game)
    assert len(game.space_monsters[0]["entities"]) == GUARDIAN_SHIPS_PER - 1
    # Reload: only the surviving hull(s) come back.
    game2, cm2, _s2 = _world(n_unowned=1)
    load_guardians(game2)
    monsters = [e for e, o in cm2.get_all(ShipOwner)
                if o.empire_id == MONSTER_EMPIRE_ID]
    assert len(monsters) == GUARDIAN_SHIPS_PER - 1


def test_reconcile_persists_kill_immediately(temp_db):
    """REGRESSION: a guardian cleared in a player's tactical battle
    (resolved AFTER advance_turn) must be marked dead at once via
    reconcile_kills — not left alive until the next monster_tick, which
    would resurrect it if the player saved in between."""
    from ecs.db import get_space_monsters
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    for e in list(game.space_monsters[0]["entities"]):
        cm.remove_component(e, Ship)
    reconcile_kills(game)                         # NOT waiting for the tick
    assert get_space_monsters(alive_only=True) == []


def test_guardian_blocks_outpost(temp_db):
    from ecs.colonization import can_plant_outpost, OUTPOST_SHIP_CLASS
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    g = game.space_monsters[0]
    star = g["star_entity"]
    se = game.entity_mgr.create_entity()
    cm.add_component(se, Ship(id=1, ship_class=OUTPOST_SHIP_CLASS))
    cm.add_component(se, ShipOwner(empire_id=1))
    cm.add_component(se, ShipAt(star_entity=star))
    assert can_plant_outpost(cm, star, 1) is False   # guardian blocks it
    for e in list(g["entities"]):
        cm.remove_component(e, Ship)
        cm.remove_component(e, ShipOwner)
        cm.remove_component(e, ShipAt)
    assert can_plant_outpost(cm, star, 1) is True    # freed


def test_dead_guardian_not_recreated_on_load(temp_db):
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    g = game.space_monsters[0]
    for e in list(g["entities"]):
        cm.remove_component(e, Ship)
    monster_tick(game, turn=2)   # marks the DB row dead
    game2, cm2, _s2 = _world(n_unowned=1)
    load_guardians(game2)
    assert game2.space_monsters == []
    assert not any(o.empire_id == MONSTER_EMPIRE_ID
                   for _e, o in cm2.get_all(ShipOwner))


# ---- endgame must not scrap pseudo-empire fleets ----------------------

def test_load_path_recreates_missing_table(temp_db):
    """REGRESSION: loading a save whose DB predates the space_monsters
    table must NOT crash. load_game runs init_db() first, which recreates
    the table (idempotent, no data loss)."""
    from ecs.db import get_connection, get_space_monsters, init_db
    with get_connection() as conn:               # simulate a pre-feature DB
        conn.execute("DROP TABLE space_monsters")
        conn.commit()
    init_db()                                    # what load_game now does
    assert get_space_monsters(alive_only=True) == []   # no OperationalError


def test_ships_column_migration_backfills_full_pack(temp_db):
    """REGRESSION: a save with the table but no 'ships' column (the
    intermediate schema) must migrate cleanly, backfilling legacy
    guardians to a full pack rather than crashing or half-strength."""
    from ecs.db import get_connection, get_space_monsters, init_db
    with get_connection() as conn:               # intermediate schema
        conn.execute("DROP TABLE space_monsters")
        conn.execute("CREATE TABLE space_monsters (id INTEGER PRIMARY KEY, "
                     "star_id INTEGER NOT NULL, monster_type TEXT NOT NULL, "
                     "alive INTEGER DEFAULT 1)")
        conn.execute("INSERT INTO space_monsters (star_id, monster_type, alive) "
                     "VALUES (5, 'Space Dragon', 1)")
        conn.commit()
    init_db()                                    # _migrate_space_monsters adds col
    rows = get_space_monsters(alive_only=True)
    assert len(rows) == 1
    assert rows[0]["ships"] == GUARDIAN_SHIPS_PER   # legacy -> full pack


def test_events_never_target_pseudo_empire(temp_db):
    """REGRESSION: diplomatic-incident / cultural-exchange events must
    never pick the monster (or Antaran) pseudo-empire as the player's
    counterpart."""
    import random
    from ecs.events import _pick_diplomatic_target
    game, cm, stars = _world(n_unowned=1)          # player id 1
    cm.add_component(game.entity_mgr.create_entity(),
                     Empire(id=2, name="AI", race_type="Humans", color="green",
                            tech_level=0, home_star_id=1, is_player=False))
    spawn_guardians(game)                          # creates monster empire 9002
    for seed in range(40):
        t = _pick_diplomatic_target(game, random.Random(seed))
        assert t is None or not is_pseudo_empire(t.id)
    # It still picks the real rival.
    picks = {_pick_diplomatic_target(game, random.Random(s)).id
             for s in range(20)}
    assert picks == {2}


def test_endgame_does_not_scrap_guardians(temp_db):
    """REGRESSION: check_endgame scraps colony-less empires' fleets; it
    must SKIP the monster (and Antaran) pseudo-empires."""
    from ecs.endgame import check_endgame
    from ecs.db import get_connection, insert_star, insert_empire
    with get_connection() as conn:
        insert_star(conn, "Home", 0, 0, "G", "s.png", 30)   # id 1
        insert_empire(conn, "P", "Humans", "blue", 1, 0)     # id 1
        conn.commit()
    game, cm, stars = _world(n_unowned=1)
    spawn_guardians(game)
    before = len([e for e, o in cm.get_all(ShipOwner)
                  if o.empire_id == MONSTER_EMPIRE_ID])
    assert before == GUARDIAN_SHIPS_PER
    check_endgame(game)
    after = len([e for e, o in cm.get_all(ShipOwner)
                 if o.empire_id == MONSTER_EMPIRE_ID])
    assert after == before      # guardians untouched

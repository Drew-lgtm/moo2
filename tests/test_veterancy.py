"""Ship veterancy — experience, ranks, combat bonuses, and XP awards."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import Empire, Ship, ShipOwner, ShipAt, StarRef
from ecs.veterancy import (
    rank_index, rank_name, attack_bonus, hull_bonus, battle_xp,
    grant_combat_xp, ship_experience, XP_PER_BATTLE, XP_PER_KILL,
)


# ---- engine ------------------------------------------------------------

def test_rank_ladder():
    assert rank_index(0) == 0 and rank_name(0) == "Green"
    assert rank_index(99) == 0
    assert rank_index(100) == 1 and rank_name(100) == "Regular"
    assert rank_index(300) == 2 and rank_name(300) == "Veteran"
    assert rank_index(700) == 3 and rank_name(700) == "Elite"
    assert rank_index(1500) == 4 and rank_name(1500) == "Ultra-Elite"
    assert rank_index(999999) == 4         # caps at top rank


def test_bonuses_scale_with_rank():
    assert attack_bonus(0) == 0 and hull_bonus(0) == 0
    assert attack_bonus(300) == 2 and hull_bonus(300) == 4
    assert attack_bonus(1500) == 4 and hull_bonus(1500) == 8


def test_battle_xp_formula():
    assert battle_xp(0) == XP_PER_BATTLE
    assert battle_xp(3) == XP_PER_BATTLE + 3 * XP_PER_KILL


# ---- grant_combat_xp ---------------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "vet.db")
    db.init_db()
    yield


def test_grant_persists_experience(temp_db):
    from ecs.db import get_connection, insert_star, insert_empire, insert_ship, get_ships
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)
        insert_empire(conn, "P", "Humans", "blue", 1, 0)
        sid = insert_ship(conn, 1, "cruiser", 1)
        conn.commit()
    em = EntityManager(); cm = ComponentManager()
    e = em.create_entity()
    cm.add_component(e, Ship(id=sid, ship_class="cruiser"))
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em)
    grant_combat_xp(game, [e], enemies_killed=2)
    assert cm.get_component(e, Ship).experience == battle_xp(2)
    with get_connection() as conn:
        row = next(r for r in get_ships(conn) if r["id"] == sid)
    assert row["experience"] == battle_xp(2)


def test_grant_skips_ecs_only_ships(temp_db):
    # Negative id = ECS-only pseudo-empire ship (raider/monster): no XP.
    em = EntityManager(); cm = ComponentManager()
    e = em.create_entity()
    cm.add_component(e, Ship(id=-8000, ship_class="battleship"))
    game = SimpleNamespace(component_mgr=cm, entity_mgr=em)
    grant_combat_xp(game, [e], enemies_killed=5)
    assert cm.get_component(e, Ship).experience == 0


# ---- veterancy in combat ----------------------------------------------

def test_build_combatants_applies_veterancy_bonus():
    import ecs.combat as combat

    class FakeCM:
        def __init__(self, xp):
            self._ship = Ship(id=1, ship_class="cruiser", weapon_tech=None,
                              weapon_count=0, specials=[], experience=xp)

        def get_all(self, comp):
            return []

        def get_component(self, entity, comp):
            return self._ship if comp is Ship else None

    def bonuses(_eid):
        return (0, 0)

    def stats_full(_e):
        return {"attack": 0, "missile_attack": 0, "point_defense": 0,
                "hull": 0, "defense": 0, "shield_capacity": 0, "shield_regen": 0}

    def build(xp):
        cm = FakeCM(xp)
        rosters, _ = combat._build_combatants(
            cm, {1: [10]}, bonuses, {}, lambda eid, e: 0, stats_full)
        return rosters[1][0]

    green = build(0)
    elite = build(700)     # rank 3 -> +3 attack, +6 hull
    assert elite.attack == green.attack + 3
    assert elite.hull_max == green.hull_max + 6


def test_combat_tick_awards_xp_to_survivors(temp_db):
    """A winning fleet's surviving ships bank XP scaled by kills."""
    from ecs.db import get_connection, insert_star, insert_empire, insert_ship
    from ecs.combat import combat_tick
    with get_connection() as conn:
        insert_star(conn, "Vega", 0, 0, "G", "s.png", 30)      # id 1
        insert_empire(conn, "A", "Humans", "green", 1, 0)       # id 1 winner
        insert_empire(conn, "B", "Humans", "red", 1, 0)         # id 2 loser
        conn.commit()
    em = EntityManager(); cm = ComponentManager()
    for eid, name, col in ((1, "A", "green"), (2, "B", "red")):
        e = em.create_entity()
        cm.add_component(e, Empire(id=eid, name=name, race_type="Humans",
                                   color=col, tech_level=0, home_star_id=1,
                                   is_player=False))
    star = em.create_entity()
    cm.add_component(star, StarRef(db_id=1))
    from ecs.components import Name
    cm.add_component(star, Name("Vega"))
    # Empire 1: a strong battleship squadron. Empire 2: one weak frigate.
    winners = []
    for _ in range(4):
        with get_connection() as conn:
            sid = insert_ship(conn, 1, "battleship", 1, weapon_tech="death_ray",
                              weapon_count=4, weapon_mount="heavy")
            conn.commit()
        s = em.create_entity()
        cm.add_component(s, Ship(id=sid, ship_class="battleship",
                                 weapon_tech="death_ray", weapon_count=4,
                                 weapon_mount="heavy"))
        cm.add_component(s, ShipOwner(empire_id=1))
        cm.add_component(s, ShipAt(star_entity=star))
        winners.append(s)
    with get_connection() as conn:
        fid = insert_ship(conn, 2, "frigate", 1)
        conn.commit()
    fe = em.create_entity()
    cm.add_component(fe, Ship(id=fid, ship_class="frigate"))
    cm.add_component(fe, ShipOwner(empire_id=2))
    cm.add_component(fe, ShipAt(star_entity=star))

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           diplomacy=None, leaders=None, last_combats=[],
                           pending_combat_reports=None, pending_engagements=None,
                           galaxy=SimpleNamespace(turn=5))
    game.player_empire = lambda: None
    combat_tick(game, 5)

    # The frigate died; surviving battleships each earned XP for 1 kill.
    assert cm.get_component(fe, Ship) is None
    alive = [s for s in winners if cm.get_component(s, Ship) is not None]
    assert alive, "the battleships should have won"
    for s in alive:
        assert cm.get_component(s, Ship).experience == battle_xp(1)

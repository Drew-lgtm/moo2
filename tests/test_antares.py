"""Dimensional Portal — the strike back at Antares.

Covers portal detection, the can-launch gate, and the assault itself:
a strong staging fleet wins (Antaran victory stamped on the game), a
token fleet loses (attackers destroyed, no victory), and the loss of
individual ships is applied to the survivors.
"""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, Owner, Planet, Population, BuildState, Orbiting, StarRef, Name,
    Ship, ShipOwner, ShipAt,
)
from ecs.antares import (
    has_portal, can_launch_assault, launch_assault, has_local_assault_fleet,
    _make_combatant, PORTAL_BUILDING, ANTARES_DEFENDER_COUNT, _ANTARES_PROTO,
)
from ecs.antaran import ANTARAN_EMPIRE_ID


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "antares.db")
    db.init_db()
    yield


def _world(with_portal=True, fleet=0, fleet_loadout=None):
    """Player empire (id 1) with one colony. Optionally give the colony a
    completed Dimensional Portal and stage ``fleet`` warships at its
    star. Returns (game, cm, star_entity, [ship_entity...])."""
    from ecs.db import get_connection, insert_star, insert_empire, insert_ship
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "s.png", 30)   # id 1
        insert_empire(conn, "P", "Humans", "blue", 1, 0)    # id 1
        conn.commit()

    em = EntityManager()
    cm = ComponentManager()
    emp_e = em.create_entity()
    cm.add_component(emp_e, Empire(id=1, name="P", race_type="Humans",
                                   color="blue", tech_level=0, home_star_id=1,
                                   is_player=True))
    star_e = em.create_entity()
    cm.add_component(star_e, StarRef(db_id=1))
    cm.add_component(star_e, Name("Sol"))

    planet_e = em.create_entity()
    cm.add_component(planet_e, Planet(id=1, planet_type="Terran", size="Medium",
                                      colonizable=True))
    cm.add_component(planet_e, Owner(empire_id=1))
    cm.add_component(planet_e, Population(current=8, max=12, workers=8))
    cm.add_component(planet_e, Orbiting(star_entity=star_e))
    completed = [PORTAL_BUILDING] if with_portal else []
    cm.add_component(planet_e, BuildState(current_project=None,
                                          completed=completed))

    loadout = fleet_loadout or dict(
        armor_tech="xentronium_armor", shield_tech="class_vii_shield",
        weapon_tech="death_ray", weapon_count=4, weapon_mount="heavy")
    ships = []
    for _i in range(fleet):
        with get_connection() as conn:
            sid = insert_ship(conn, 1, loadout.get("ship_class", "doom_star"), 1,
                              armor_tech=loadout.get("armor_tech"),
                              shield_tech=loadout.get("shield_tech"),
                              weapon_tech=loadout.get("weapon_tech"),
                              weapon_count=loadout.get("weapon_count", 0),
                              weapon_mount=loadout.get("weapon_mount", "normal"))
            conn.commit()
        se = em.create_entity()
        cm.add_component(se, Ship(id=sid,
                                  ship_class=loadout.get("ship_class", "doom_star"),
                                  armor_tech=loadout.get("armor_tech"),
                                  shield_tech=loadout.get("shield_tech"),
                                  weapon_tech=loadout.get("weapon_tech"),
                                  weapon_count=loadout.get("weapon_count", 0),
                                  weapon_mount=loadout.get("weapon_mount", "normal")))
        cm.add_component(se, ShipOwner(empire_id=1))
        cm.add_component(se, ShipAt(star_entity=star_e))
        ships.append(se)

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           pending_endgame=None,
                           galaxy=SimpleNamespace(turn=200))
    game.player_empire = lambda: next(
        (e for _x, e in cm.get_all(Empire) if e.is_player), None)
    return game, cm, star_e, ships


# ---- detection + gate --------------------------------------------------

def test_has_portal(temp_db):
    game, cm, _s, _f = _world(with_portal=True)
    assert has_portal(cm, 1)
    game2, cm2, _s2, _f2 = _world(with_portal=False)
    assert not has_portal(cm2, 1)


def test_cannot_launch_without_portal(temp_db):
    game, cm, _s, _f = _world(with_portal=False, fleet=5)
    ok, reason = can_launch_assault(game, 1)
    assert not ok and reason == "no_portal"


def test_cannot_launch_without_fleet(temp_db):
    game, cm, _s, _f = _world(with_portal=True, fleet=0)
    ok, reason = can_launch_assault(game, 1)
    assert not ok and reason == "no_fleet"


def test_can_launch_with_portal_and_fleet(temp_db):
    game, cm, _s, _f = _world(with_portal=True, fleet=3)
    ok, reason = can_launch_assault(game, 1)
    assert ok and reason == "ok"


# ---- assault -----------------------------------------------------------

def test_launch_blocked_returns_not_launched(temp_db):
    game, cm, _s, _f = _world(with_portal=False, fleet=0)
    import random
    res = launch_assault(game, 1, rng=random.Random(1))
    assert res["launched"] is False
    assert game.pending_endgame is None


def test_overwhelming_fleet_wins_and_ends_game(temp_db):
    # 3x the defenders, identical apex loadout -> reliable victory.
    game, cm, _s, ships = _world(with_portal=True,
                                 fleet=ANTARES_DEFENDER_COUNT * 3)
    import random
    res = launch_assault(game, 1, rng=random.Random(7))
    assert res["launched"] and res["victory"]
    assert res["defenders"] == ANTARES_DEFENDER_COUNT
    assert game.pending_endgame == {
        "result": "victory", "mode": "Antaran", "winner_id": 1}
    # At least some attackers survive to hold the field.
    survivors = [e for e, _o in cm.get_all(ShipOwner)]
    assert len(survivors) == res["sent"] - res["lost"]
    assert res["lost"] < res["sent"]


def test_token_fleet_loses_and_is_destroyed(temp_db):
    game, cm, _s, ships = _world(
        with_portal=True, fleet=1,
        fleet_loadout={"ship_class": "frigate", "weapon_tech": "laser_cannon",
                       "weapon_count": 1, "weapon_mount": "normal"})
    import random
    res = launch_assault(game, 1, rng=random.Random(3))
    assert res["launched"] and not res["victory"]
    assert game.pending_endgame is None
    # The lone frigate is wiped out.
    assert res["lost"] == 1
    assert not any(o.empire_id == 1 for _e, o in cm.get_all(ShipOwner))


# ---- review fixes ------------------------------------------------------

def test_make_combatant_applies_empire_bonuses():
    """REGRESSION: the assault fleet must carry the same empire-wide
    bonuses (race traits, Energy Absorber shields, ship leaders) it has
    in every normal battle — otherwise it fights weaker at Antares."""
    s = Ship(id=7, ship_class="battleship", weapon_tech="death_ray",
             weapon_count=2, weapon_mount="heavy")
    base = _make_combatant(s, 1, 7)
    boosted = _make_combatant(s, 1, 7, atk_bonus=3, hull_bonus=4,
                              shield_bonus=20, leader_map={7: (5, 6)})
    assert boosted.attack == base.attack + 3 + 5      # atk_bonus + leader atk
    assert boosted.hull_max == base.hull_max + 4 + 6  # hull_bonus + leader hull
    assert boosted.shield_max == base.shield_max + 20 # Energy Absorber


def test_has_local_assault_fleet_is_per_star(temp_db):
    game, cm, star, ships = _world(with_portal=True, fleet=2)
    assert has_local_assault_fleet(game, 1, star)
    other = game.entity_mgr.create_entity()
    cm.add_component(other, StarRef(db_id=99))
    assert not has_local_assault_fleet(game, 1, other)   # no fleet there


def test_launch_from_fleetless_star_is_no_fleet(temp_db):
    import random
    game, cm, star, ships = _world(with_portal=True, fleet=2)
    other = game.entity_mgr.create_entity()
    cm.add_component(other, StarRef(db_id=99))
    res = launch_assault(game, 1, rng=random.Random(1), star_entity=other)
    assert res["launched"] is False and res["reason"] == "no_fleet"

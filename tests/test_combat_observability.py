"""Combat observability: the resolver reports a fire breakdown (beam vs
missile vs point-defense interception) and the engagement record carries
it plus veteran ranks, so the player can see what actually happened."""
import random
from types import SimpleNamespace

import pytest

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.battle import Combatant, resolve_auto
from ecs.components import Empire, Name, Ship, ShipOwner, ShipAt, StarRef


def _hostile(a, b):
    return a != b


# ---- resolver stats ----------------------------------------------------

def test_resolver_reports_beam_and_missile_fire():
    atk = [Combatant(key="a", empire_id=1, attack=10, hull=100, hull_max=100,
                     missile_attack=20)]
    dfn = [Combatant(key="d", empire_id=2, attack=0, hull=5000, hull_max=5000)]
    stats: dict = {}
    resolve_auto({1: atk, 2: dfn}, {}, _hostile, random.Random(1),
                 max_rounds=1, stats=stats)
    assert stats[1]["beam"] > 0
    assert stats[1]["missile"] > 0
    assert stats[1]["intercepted"] == 0        # attacker intercepted nothing


def test_resolver_reports_interception_on_the_defender():
    atk = [Combatant(key="a", empire_id=1, attack=0, hull=100, hull_max=100,
                     missile_attack=40)]
    dfn = [Combatant(key="d", empire_id=2, attack=0, hull=5000, hull_max=5000,
                     point_defense=15)]
    stats: dict = {}
    resolve_auto({1: atk, 2: dfn}, {}, _hostile, random.Random(1),
                 max_rounds=1, stats=stats)
    # The DEFENDER's PD is credited with what it shot down, capped by the
    # incoming volley.
    assert stats[2]["intercepted"] == min(15, stats[1]["missile"])


def test_interception_never_exceeds_incoming():
    atk = [Combatant(key="a", empire_id=1, attack=0, hull=100, hull_max=100,
                     missile_attack=2)]
    dfn = [Combatant(key="d", empire_id=2, attack=0, hull=500, hull_max=500,
                     point_defense=999)]
    stats: dict = {}
    resolve_auto({1: atk, 2: dfn}, {}, _hostile, random.Random(2),
                 max_rounds=1, stats=stats)
    assert stats[2]["intercepted"] == stats[1]["missile"]


def test_neutral_bystander_is_not_credited_with_fire():
    """REGRESSION: a co-located neutral used to have its pool rolled and
    tallied, so the report showed a bystander as dealing damage."""
    a = [Combatant(key="a", empire_id=1, attack=30, hull=200, hull_max=200)]
    b = [Combatant(key="b", empire_id=2, attack=30, hull=200, hull_max=200)]
    c = [Combatant(key="c", empire_id=3, attack=99, hull=200, hull_max=200)]

    def hostile(x, y):          # 1 v 2 at war; 3 neutral to both
        return {x, y} == {1, 2}

    stats: dict = {}
    resolve_auto({1: a, 2: b, 3: c}, {}, hostile, random.Random(1),
                 max_rounds=2, stats=stats)
    assert 3 not in stats or stats[3] == {"beam": 0, "missile": 0,
                                          "intercepted": 0}
    assert not c[0].destroyed          # and it takes no damage either


def test_tactical_report_carries_the_fire_breakdown():
    """REGRESSION: the tactical path's battle_report omitted the new keys,
    so battles the PLAYER fought showed no breakdown at all."""
    from ecs.tactical import TacticalShip, TacticalBattle, battle_report
    a = TacticalShip(entity_id=1, empire_id=1, ship_class="cruiser", name="A",
                     col=0, row=0, hull=100, max_hull=100, attack=0,
                     missile_attack=30, veteran_rank="Veteran")
    d = TacticalShip(entity_id=2, empire_id=2, ship_class="frigate", name="D",
                     col=1, row=0, hull=100, max_hull=100, attack=5,
                     point_defense=8)
    b = TacticalBattle(star_entity=1, star_name="X", turn=1, player_id=1)
    b.ships = [a, d]
    b.attack(a, d, random.Random(1))
    rep = battle_report(b, {1: 30, 2: 5})
    sides = {s["empire_id"]: s for s in rep["sides"]}
    assert sides[1]["missile_fired"] > 0
    assert sides[2]["intercepted"] == 8          # defender's PD budget
    assert sides[1]["veterans"] == {"Veteran": 1}
    for s in sides.values():
        for key in ("beam_fired", "missile_fired", "intercepted", "veterans"):
            assert key in s


def test_stats_optional_is_backwards_compatible():
    atk = [Combatant(key="a", empire_id=1, attack=5, hull=50, hull_max=50)]
    dfn = [Combatant(key="d", empire_id=2, attack=5, hull=50, hull_max=50)]
    resolve_auto({1: atk, 2: dfn}, {}, _hostile, random.Random(1))  # no stats


# ---- engagement record -------------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "obs.db")
    db.init_db()
    yield


def test_engagement_record_carries_fire_and_veterans(temp_db):
    """combat_tick's report must include the fire breakdown + the ranks the
    fleets fought at (pre-battle, not inflated by this battle's XP)."""
    from ecs.db import get_connection, insert_star, insert_empire, insert_ship
    from ecs.combat import combat_tick
    from ecs.veterancy import RANK_THRESHOLDS
    with get_connection() as conn:
        insert_star(conn, "Vega", 0, 0, "G", "s.png", 30)
        insert_empire(conn, "A", "Humans", "green", 1, 0)   # 1
        insert_empire(conn, "B", "Humans", "red", 1, 0)     # 2
        conn.commit()
    em = EntityManager(); cm = ComponentManager()
    for eid, col in ((1, "green"), (2, "red")):
        e = em.create_entity()
        cm.add_component(e, Empire(id=eid, name=str(eid), race_type="Humans",
                                   color=col, tech_level=0, home_star_id=1,
                                   is_player=False))
    star = em.create_entity()
    cm.add_component(star, StarRef(db_id=1)); cm.add_component(star, Name("Vega"))

    def _mk(eid, cls, xp=0, **kw):
        with get_connection() as conn:
            sid = insert_ship(conn, eid, cls, 1, **kw); conn.commit()
        s = em.create_entity()
        cm.add_component(s, Ship(id=sid, ship_class=cls, experience=xp, **kw))
        cm.add_component(s, ShipOwner(empire_id=eid))
        cm.add_component(s, ShipAt(star_entity=star))
        return s
    # Empire 1: a Veteran-ranked missile cruiser squadron.
    veteran_xp = RANK_THRESHOLDS[2]
    for _ in range(4):
        _mk(1, "cruiser", xp=veteran_xp, weapon_tech="nuclear_missile",
            weapon_count=3)
    # Empire 2: a green frigate with point-defense rockets.
    _mk(2, "frigate", specials="anti_missile_rockets")

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em, turn_log=None,
                           diplomacy=None, leaders=None, last_combats=[],
                           pending_combat_reports=None, pending_engagements=None,
                           galaxy=SimpleNamespace(turn=3))
    game.player_empire = lambda: None
    combat_tick(game, 3)

    assert game.last_combats, "an engagement should have been recorded"
    sides = {s["empire_id"]: s for s in game.last_combats[-1]["sides"]}
    # Missile fire is reported for the attacker.
    assert sides[1]["missile_fired"] > 0
    # Ranks are the PRE-battle ones (Veteran), not post-XP.
    assert sides[1]["veterans"].get("Veteran") == 4
    assert sides[2]["veterans"].get("Green") == 1
    # Every side dict exposes the new keys.
    for s in sides.values():
        for key in ("beam_fired", "missile_fired", "intercepted", "veterans"):
            assert key in s

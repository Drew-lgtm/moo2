"""Point-defense interception in tactical (hex) battles — the same
side-pooled missile-vs-PD model the strategic resolver uses."""
import random

from ecs.tactical import TacticalShip, TacticalBattle


def _ship(eid, col, **kw):
    kw.setdefault("hull", 500)
    kw.setdefault("max_hull", 500)
    kw.setdefault("attack", 0)
    return TacticalShip(entity_id=eid, empire_id=eid, ship_class="cruiser",
                        name=f"S{eid}", col=col, row=0, **kw)


def _battle(a, d):
    b = TacticalBattle(star_entity=1, star_name="X", turn=1, player_id=1)
    b.ships = [a, d]
    return b


def _damage_done(defender_pd, missile=40, beam=0, seed=1):
    a = _ship(1, 0, attack=beam, missile_attack=missile)
    d = _ship(2, 1, point_defense=defender_pd)
    b = _battle(a, d)
    before = d.hull
    b.attack(a, d, random.Random(seed))
    return before - d.hull


def test_point_defense_reduces_missile_damage():
    assert _damage_done(defender_pd=0) > _damage_done(defender_pd=15)


def test_point_defense_does_not_stop_beams():
    assert _damage_done(defender_pd=20, missile=0, beam=40) == \
           _damage_done(defender_pd=0, missile=0, beam=40)


def test_result_reports_interception():
    a = _ship(1, 0, missile_attack=30)
    d = _ship(2, 1, point_defense=10)
    b = _battle(a, d)
    res = b.attack(a, d, random.Random(3))
    assert res["intercepted"] == 10
    assert b.pd_pool[d.empire_id] == 0          # side screen spent


def test_pd_budget_is_per_round_and_rearms():
    a = _ship(1, 0, missile_attack=30)
    a2 = _ship(3, 0, missile_attack=30)
    d = _ship(2, 1, point_defense=10)
    b = TacticalBattle(star_entity=1, star_name="X", turn=1, player_id=1)
    b.ships = [a, a2, d]
    b.attack(a, d, random.Random(1))
    assert b.pd_pool[d.empire_id] == 0
    # Second attacker the SAME round faces no interception left.
    res2 = b.attack(a2, d, random.Random(1))
    assert res2["intercepted"] == 0
    b.end_round()
    assert b.pd_pool == {}                      # rearms lazily next shot


def test_overwhelming_pd_blocks_a_small_volley():
    a = _ship(1, 0, missile_attack=2)
    d = _ship(2, 1, point_defense=999)
    before = d.hull
    b = _battle(a, d)
    res = b.attack(a, d, random.Random(5))
    assert res["damage"] == 0 and d.hull == before


def test_auto_resolve_carries_missiles_and_pd():
    """The tactical auto-resolve path must not silently drop missile fire
    or interception when it bridges to the shared resolver."""
    from ecs.tactical import auto_resolve, _combatant_view
    s = _ship(1, 0, missile_attack=12, point_defense=7)
    view = _combatant_view(s)
    assert view.missile_attack == 12 and view.point_defense == 7
    # A missile-only attacker still kills a defenceless target.
    a = _ship(1, 0, missile_attack=60)
    d = _ship(2, 1, hull=10, max_hull=10)
    b = _battle(a, d)
    auto_resolve(b, random.Random(2))
    assert d.destroyed

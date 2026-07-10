"""Tests for the tactical layer: hex math, per-shot fire (now routed
through the canonical ecs.battle model), movement points, stations, and
the shared auto-resolver."""
import random

from ecs.tactical import (
    TacticalBattle, TacticalShip, auto_resolve, weapon_range_mult,
    hex_distance, hex_to_pixel, pixel_to_hex,
    SHORT_RANGE, LONG_RANGE, LONG_RANGE_MULT,
)


def _ship(eid, empire, col, row, **kw):
    base = dict(ship_class="cruiser", name=f"S{eid}", hull=10, max_hull=10,
                attack=4, speed=5, moves_left=5, shield_max=0,
                shield_current=0, shield_regen=0, armor=0)
    base.update(kw)
    return TacticalShip(entity_id=eid, empire_id=empire, col=col, row=row, **base)


def _battle(*ships):
    b = TacticalBattle(star_entity=1, star_name="Sol", turn=1, player_id=1)
    b.ships.extend(ships)
    return b


# ---- hex math ----------------------------------------------------------

def test_hex_pixel_roundtrip():
    for c in range(0, 14, 3):
        for r in range(0, 7, 2):
            px, py = hex_to_pixel(c, r, 20, 70)
            assert pixel_to_hex(px, py, 20, 70) == (c, r)


def test_hex_distance_symmetric():
    assert hex_distance(0, 0, 3, 2) == hex_distance(3, 2, 0, 0)


# ---- range bands -------------------------------------------------------

def test_range_full_then_falloff_then_out():
    assert weapon_range_mult(1) == 1.0
    assert weapon_range_mult(SHORT_RANGE) == 1.0
    assert weapon_range_mult(SHORT_RANGE + 1) == LONG_RANGE_MULT
    assert weapon_range_mult(LONG_RANGE) == LONG_RANGE_MULT
    assert weapon_range_mult(LONG_RANGE + 1) == 0.0


# ---- per-shot fire -----------------------------------------------------

def test_fire_out_of_range_refused():
    a = _ship(1, 1, 0, 0, attack=5)
    t = _ship(2, 2, 13, 6, hull=10)
    b = _battle(a, t)
    r = b.attack(a, t, random.Random(0))
    assert r["fired"] is False and r["reason"] == "out of range"
    assert t.hull == 10


def test_fire_layered_shield_then_hull():
    a = _ship(1, 1, 0, 0, attack=8)
    t = _ship(2, 2, 1, 0, hull=10, shield_max=4, shield_current=4)
    b = _battle(a, t)
    r = b.attack(a, t, random.Random(0))
    assert r["fired"]
    assert r["to_shield"] + r["to_hull"] == r["damage"]
    assert t.shield_current == 4 - r["to_shield"]


def test_fire_once_per_round():
    a = _ship(1, 1, 0, 0, attack=4)
    t = _ship(2, 2, 1, 0, hull=50)
    b = _battle(a, t)
    assert b.attack(a, t, random.Random(0))["fired"]
    second = b.attack(a, t, random.Random(0))
    assert second["fired"] is False and "already fired" in second["reason"]


# ---- movement ----------------------------------------------------------

def test_move_costs_ap_and_blocks_when_short():
    s = _ship(1, 1, 0, 0, speed=3, moves_left=3)
    b = _battle(s)
    assert b.move_ship(s, 3, 0) is True   # distance 3, exactly affordable
    assert s.moves_left == 0
    assert b.move_ship(s, 4, 0) is False  # no AP left


def test_move_blocked_by_occupied_hex():
    a = _ship(1, 1, 0, 0)
    other = _ship(2, 1, 2, 0)
    b = _battle(a, other)
    assert b.move_ship(a, 2, 0) is False


def test_station_cannot_move():
    st = _ship(1, 1, 0, 0, is_station=True, speed=0, moves_left=0)
    b = _battle(st)
    assert b.move_ship(st, 1, 0) is False


# ---- auto-resolve ------------------------------------------------------

def test_auto_resolve_stronger_wins_and_finishes():
    p = _ship(10, 1, 0, 2, hull=25, attack=12)
    e = _ship(20, 2, 13, 2, hull=4, attack=2)
    b = _battle(p, e)
    auto_resolve(b, random.Random(1))
    assert b.finished
    assert b.winner_id == 1
    assert 20 in b.destroyed_entity_ids()


def test_auto_resolve_deterministic_seed():
    def build():
        return _battle(_ship(1, 1, 0, 2, hull=12, attack=6, shield_max=6,
                             shield_current=6, shield_regen=2),
                       _ship(2, 2, 5, 2, hull=12, attack=6, shield_max=6,
                             shield_current=6, shield_regen=2))
    b1 = build(); auto_resolve(b1, random.Random(7))
    b2 = build(); auto_resolve(b2, random.Random(7))
    assert [s.hull for s in b1.ships] == [s.hull for s in b2.ships]
    assert b1.winner_id == b2.winner_id

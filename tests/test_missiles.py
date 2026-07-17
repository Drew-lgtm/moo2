"""Missiles, fighters, and point-defense interception.

Missile weapons + carrier fighters fire interceptable ordnance; a
target's point-defense shoots it down each round (beams get through).
"""
import random

from ecs.battle import Combatant, resolve_auto
from ecs.components import Ship
from ecs.ship_design import stats_from_ship, PD_INTERCEPT_PER_GUN
from ecs.ships import SHIPS


def _hostile(a, b):
    return a != b


# ---- resolver interception --------------------------------------------

def _one_round(attacker_missile=0, attacker_beam=0, defender_pd=0):
    """One combat round: a lone attacker vs a big-hulled defender with
    ``defender_pd`` point-defense. Returns damage dealt to the defender."""
    atk = [Combatant(key="a", empire_id=1, attack=attacker_beam, hull=200,
                     hull_max=200, missile_attack=attacker_missile)]
    dfn = [Combatant(key="d", empire_id=2, attack=0, hull=5000, hull_max=5000,
                     point_defense=defender_pd)]
    resolve_auto({1: atk, 2: dfn}, {}, _hostile, random.Random(1), max_rounds=1)
    return 5000 - dfn[0].hull


def test_point_defense_reduces_missile_damage():
    no_pd = _one_round(attacker_missile=60, defender_pd=0)
    with_pd = _one_round(attacker_missile=60, defender_pd=25)
    assert no_pd > 0
    assert with_pd == no_pd - 25          # PD shoots down exactly its budget


def test_point_defense_does_not_stop_beams():
    no_pd = _one_round(attacker_beam=60, defender_pd=0)
    with_pd = _one_round(attacker_beam=60, defender_pd=25)
    assert with_pd == no_pd                # beams are never intercepted


def test_overwhelming_pd_negates_missiles():
    # PD budget exceeds the missile pool -> no missile damage lands.
    assert _one_round(attacker_missile=20, defender_pd=1000) == 0


# ---- stats routing -----------------------------------------------------

def _ship(**kw):
    kw.setdefault("id", 1)
    kw.setdefault("ship_class", "cruiser")
    return Ship(**kw)


def test_missile_weapon_routes_to_missile_attack():
    s = stats_from_ship(_ship(weapon_tech="nuclear_missile", weapon_count=3))
    assert s["missile_attack"] == 9        # attack 3 x count 3 (normal mount)
    assert s["attack"] == 0


def test_beam_weapon_routes_to_attack():
    s = stats_from_ship(_ship(weapon_tech="laser_cannons", weapon_count=3))
    assert s["attack"] == 3
    assert s["missile_attack"] == 0


def test_proton_torpedo_is_a_missile():
    s = stats_from_ship(_ship(weapon_tech="proton_torpedo", weapon_count=2))
    assert s["missile_attack"] > 0 and s["attack"] == 0


def test_pd_mount_provides_interception():
    s = stats_from_ship(_ship(weapon_tech="laser_cannons", weapon_count=2,
                              weapon_mount="point_defense"))
    assert s["point_defense"] == 2 * PD_INTERCEPT_PER_GUN
    assert s["defense"] == 2                # keeps a little flat armor too


def test_anti_missile_rockets_special_gives_pd():
    s = stats_from_ship(_ship(specials=["anti_missile_rockets"]))
    assert s["point_defense"] == 3


# ---- carrier fighters (combat build path) -----------------------------

def test_carrier_fighter_attack_is_interceptable():
    """A carrier's fighter complement becomes missile_attack (PD-vulnerable)
    when snapshotted into a Combatant."""
    import ecs.combat as combat

    class FakeCM:
        def __init__(self, ship_class):
            self._ship = Ship(id=1, ship_class=ship_class, weapon_tech=None,
                              weapon_count=0, specials=[])

        def get_all(self, comp):
            return []

        def get_component(self, entity, comp):
            return self._ship if comp is Ship else None

    def bonuses(_eid):
        return (0, 0)

    def stats_full(_e):
        return {"attack": 2, "missile_attack": 0, "point_defense": 0,
                "hull": 0, "defense": 0, "shield_capacity": 0, "shield_regen": 0}

    cm = FakeCM("carrier")
    # loadout_atk 0 -> beam attack is just the carrier hull's base (2).
    rosters, _intact = combat._build_combatants(
        cm, {1: [10]}, bonuses, {}, lambda eid, e: 0, stats_full)
    c = rosters[1][0]
    assert c.missile_attack == SHIPS["carrier"]["fighter_attack"]  # 6
    assert c.attack == SHIPS["carrier"]["attack"]   # 2, beam only

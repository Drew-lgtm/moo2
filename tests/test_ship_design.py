"""Golden + invariant tests for ship loadout maths.

``stats_from_ship`` decodes a frozen loadout into combat numbers and is
read by BOTH the strategic and tactical resolvers — so it's the single
most safety-critical pure function in the combat pipeline. Pin it hard.

``compute_loadout`` (the auto-designer) is tested by invariant rather
than exact fit, since the fitting heuristic is expected to evolve; the
invariants (never over-budget, civilians unarmed) must always hold.
"""
from ecs.components import Ship
from ecs.ship_design import stats_from_ship, compute_loadout


def _ship(armor=None, shield=None, weapon=None, weapon_count=0, specials=None):
    return Ship(id=1, ship_class="frigate", armor_tech=armor,
                shield_tech=shield, weapon_tech=weapon,
                weapon_count=weapon_count, specials=specials or [])


# ---- stats_from_ship (golden) -----------------------------------------

def test_stats_empty_ship_is_zero():
    s = stats_from_ship(_ship())
    assert s == {"attack": 0, "hull": 0, "defense": 0,
                 "shield_capacity": 0, "shield_regen": 0}


def test_stats_full_loadout_decodes():
    # heavy_armor hull 2, class_i_shield cap 8 regen 2,
    # laser_cannons attack 1 x3, inertial_stabilizer defense 2
    s = stats_from_ship(_ship(
        armor="heavy_armor", shield="class_i_shield",
        weapon="laser_cannons", weapon_count=3,
        specials=["inertial_stabilizer"],
    ))
    assert s["attack"] == 3          # 1 * 3
    assert s["hull"] == 2
    assert s["shield_capacity"] == 8
    assert s["shield_regen"] == 2
    assert s["defense"] == 2


def test_stats_weapon_count_scales_attack():
    one = stats_from_ship(_ship(weapon="phasors", weapon_count=1))["attack"]
    four = stats_from_ship(_ship(weapon="phasors", weapon_count=4))["attack"]
    assert four == one * 4
    assert one == 2  # phasors attack 2


def test_stats_special_hull_adds_to_armor_hull():
    # neutronium_armor hull 10; no special hull here, just confirm armor.
    s = stats_from_ship(_ship(armor="neutronium_armor"))
    assert s["hull"] == 10


def test_stats_unknown_tech_ids_are_ignored():
    s = stats_from_ship(_ship(armor="nonexistent", weapon="also_fake",
                              weapon_count=5))
    assert s == {"attack": 0, "hull": 0, "defense": 0,
                 "shield_capacity": 0, "shield_regen": 0}


# ---- compute_loadout (invariants) -------------------------------------

def test_loadout_never_exceeds_budget():
    for cls in ("frigate", "cruiser", "battleship", "dreadnought"):
        lo = compute_loadout(cls, {
            "laser_cannons", "phasors", "heavy_armor", "class_i_shield",
            "inertial_stabilizer", "battle_pods",
        })
        st = lo["stats"]
        assert st["space_used"] <= st["space_total"], cls


def test_loadout_civilian_never_armed():
    for cls in ("colony_ship", "outpost_ship", "freighter", "scout"):
        lo = compute_loadout(cls, {"laser_cannons", "phasors", "death_ray"})
        assert lo["weapon"] is None, cls
        assert lo["weapon_count"] == 0, cls


def test_loadout_no_tech_is_safe():
    # A military hull with zero unlocked techs: no weapon, no crash,
    # everything zeroed, still within budget.
    lo = compute_loadout("frigate", set())
    assert lo["weapon"] is None
    assert lo["stats"]["attack"] == 0
    assert lo["stats"]["space_used"] <= lo["stats"]["space_total"]


def test_loadout_military_arms_when_weapon_available():
    lo = compute_loadout("dreadnought", {"laser_cannons"})
    assert lo["weapon"] == "laser_cannons"
    assert lo["weapon_count"] >= 1
    assert lo["stats"]["attack"] >= 1

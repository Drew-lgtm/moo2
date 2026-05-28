"""Auto ship loadouts — each ship picks the best researched equipment
that fits its hull's space budget.

Designs are derived live from the empire's unlocked techs; you don't
maintain a saved blueprint. Research a better armor/weapon/shield and
*every* new hull of every class instantly uses it.

Each ship class in ``ecs.ships.SHIPS`` carries a ``space`` field — the
total equipment budget. Each weapon/armor/shield/special tech carries
an ``equipment`` dict with ``size`` (space cost) and stat fields
(attack / hull / defense / cloak / space_bonus).

Fitting order, per ship:

1. Best armor (one) — bigger ships can fit heavier armor (size 1-3).
2. Best shield (one) — usually optional, fits if room remains.
3. Up to 2 best specials (defense, attack, cloak, jammer, etc.).
4. Fill *all* remaining space with copies of the best weapon.

Battle Pods (a special) grants ``space_bonus`` extra room — it acts as
a force multiplier for bigger hulls.
"""
from __future__ import annotations

from ecs.ships import SHIPS
from ecs.techs import TECHS


# Specials are sorted to prefer combat-stat ones before flavour ones.
# (A higher number means "fit me sooner". Cloaks and ones with no
# direct stat go last.)
def _special_priority(spec: dict) -> int:
    eq = spec.get("equipment", {})
    return (
        eq.get("space_bonus", 0) * 10        # battle pods first — multiplies budget
        + eq.get("attack", 0) * 3
        + eq.get("defense", 0) * 3
        + (1 if eq.get("cloak") else 0)
    )


def _equip_specs(unlocked, slot: str) -> list[dict]:
    """Equipment-bearing techs of a given slot that the empire has unlocked."""
    out = []
    unlocked_set = set(unlocked)
    for tid, spec in TECHS.items():
        if tid not in unlocked_set:
            continue
        eq = spec.get("equipment")
        if eq and eq.get("slot") == slot:
            out.append(spec)
    return out


def _best_armor(unlocked) -> dict | None:
    items = _equip_specs(unlocked, "armor")
    if not items:
        return None
    return max(items, key=lambda s: s["equipment"].get("hull", 0))


def _best_shield(unlocked) -> dict | None:
    items = _equip_specs(unlocked, "shield")
    if not items:
        return None
    return max(items, key=lambda s: s["equipment"].get("capacity", 0))


def _best_weapon(unlocked) -> dict | None:
    items = _equip_specs(unlocked, "weapon")
    if not items:
        return None
    # Pick the weapon with the best attack-per-space ratio. Tied? prefer
    # the higher raw attack so end-game weapons aren't squeezed out by
    # cheap missiles.
    def score(s):
        eq = s["equipment"]
        sz = max(1, eq.get("size", 1))
        return (eq.get("attack", 0) / sz, eq.get("attack", 0))
    return max(items, key=score)


def _useful_specials(unlocked) -> list[dict]:
    """Specials that give a real stat, sorted by priority."""
    items = _equip_specs(unlocked, "special")
    items = [s for s in items if _special_priority(s) > 0]
    items.sort(key=_special_priority, reverse=True)
    return items


def compute_loadout(ship_class: str, unlocked) -> dict:
    """Return the auto-design for a ship of ``ship_class`` given the
    empire's unlocked techs:

    {
        "armor": tech_id | None,
        "shield": tech_id | None,
        "specials": [tech_id, ...],
        "weapon": tech_id | None,
        "weapon_count": int,
        "stats": {"attack": A, "hull": H, "defense": D,
                  "shield_capacity": C, "shield_regen": R,
                  "space_used": U, "space_total": T},
    }

    Shields are an absorptive HP pool that regenerates between combat
    rounds — see ``ecs.combat``. ``defense`` here only counts flat
    bonuses from specials (Inertial Stabilizer etc.), not shields.

    Civilian hulls and non-combat ships don't fit weapons.
    """
    spec = SHIPS.get(ship_class, {})
    total_space = spec.get("space", 0)
    is_military = spec.get("ship_class_kind", "military") == "military"

    armor = _best_armor(unlocked)
    shield = _best_shield(unlocked)
    specials_pool = _useful_specials(unlocked)
    weapon = _best_weapon(unlocked) if is_military else None

    used = 0
    fitted_specials: list[dict] = []
    extra_space = 0  # from Battle Pods etc.

    # Battle Pods first — it expands the budget for everything that follows.
    bp = next((s for s in specials_pool
               if s["equipment"].get("space_bonus", 0) > 0), None)
    if bp is not None:
        bp_size = bp["equipment"].get("size", 1)
        if used + bp_size <= total_space:
            used += bp_size
            extra_space += bp["equipment"]["space_bonus"]
            fitted_specials.append(bp)

    budget = total_space + extra_space

    fitted_armor = None
    if armor is not None and used + armor["equipment"].get("size", 1) <= budget:
        used += armor["equipment"].get("size", 1)
        fitted_armor = armor

    fitted_shield = None
    if shield is not None and used + shield["equipment"].get("size", 1) <= budget:
        used += shield["equipment"].get("size", 1)
        fitted_shield = shield

    # Up to 2 more useful specials (combat ones), skipping Battle Pods (already fitted).
    for sp in specials_pool:
        if sp is bp:
            continue
        if len([s for s in fitted_specials if s is not bp]) >= 2:
            break
        sz = sp["equipment"].get("size", 1)
        if used + sz <= budget:
            used += sz
            fitted_specials.append(sp)

    # Fill the rest with copies of the best weapon.
    weapon_count = 0
    if weapon is not None:
        wsz = max(1, weapon["equipment"].get("size", 1))
        while used + wsz <= budget:
            used += wsz
            weapon_count += 1

    # Stats from the fitted equipment.
    atk = (weapon["equipment"].get("attack", 0) * weapon_count) if weapon else 0
    hull = fitted_armor["equipment"].get("hull", 0) if fitted_armor else 0
    defense = 0  # flat evasion-style bonus from specials only
    shield_capacity = fitted_shield["equipment"].get("capacity", 0) if fitted_shield else 0
    shield_regen = fitted_shield["equipment"].get("regen", 0) if fitted_shield else 0
    for sp in fitted_specials:
        eq = sp["equipment"]
        atk += eq.get("attack", 0)
        hull += eq.get("hull", 0)
        defense += eq.get("defense", 0)

    return {
        "armor": fitted_armor["id"] if fitted_armor else None,
        "shield": fitted_shield["id"] if fitted_shield else None,
        "specials": [s["id"] for s in fitted_specials],
        "weapon": weapon["id"] if weapon else None,
        "weapon_count": weapon_count,
        "stats": {
            "attack": atk,
            "hull": hull,
            "shield_capacity": shield_capacity,
            "shield_regen": shield_regen,
            "defense": defense,
            "space_used": used,
            "space_total": budget,
        },
    }


def stats_from_ship(ship) -> dict:
    """Decode a Ship component's frozen loadout into combat stats.

    Returns ``attack``, ``hull`` (armor + special hull contribution),
    ``defense`` (flat evasion-style bonuses from specials only),
    ``shield_capacity`` (HP pool the shield can absorb before failing),
    and ``shield_regen`` (HP restored at the end of each combat round).

    A ship with no stored loadout (built before this system, or freshly
    migrated from an older save) returns zeros — its base ship-class
    hull/attack still applies, but it gets no equipment bonuses until
    it's replaced.
    """
    atk = hull = defense = 0
    shield_capacity = shield_regen = 0
    armor = TECHS.get(ship.armor_tech, {}) if ship.armor_tech else {}
    shield = TECHS.get(ship.shield_tech, {}) if ship.shield_tech else {}
    weapon = TECHS.get(ship.weapon_tech, {}) if ship.weapon_tech else {}
    if armor.get("equipment"):
        hull += armor["equipment"].get("hull", 0)
    if shield.get("equipment"):
        shield_capacity += shield["equipment"].get("capacity", 0)
        shield_regen += shield["equipment"].get("regen", 0)
    if weapon.get("equipment"):
        atk += weapon["equipment"].get("attack", 0) * (ship.weapon_count or 0)
    for sp_id in (ship.specials or []):
        eq = TECHS.get(sp_id, {}).get("equipment", {})
        atk += eq.get("attack", 0)
        hull += eq.get("hull", 0)
        defense += eq.get("defense", 0)
    return {
        "attack": atk, "hull": hull, "defense": defense,
        "shield_capacity": shield_capacity, "shield_regen": shield_regen,
    }


def loadout_to_ship_fields(loadout: dict) -> dict:
    """Convert a computed loadout dict into kwargs accepted by
    ``insert_ship`` / used to seed a Ship component."""
    return {
        "armor_tech": loadout.get("armor"),
        "shield_tech": loadout.get("shield"),
        "weapon_tech": loadout.get("weapon"),
        "weapon_count": loadout.get("weapon_count", 0),
        "specials": loadout.get("specials", []),
    }


def loadout_summary(ship_class: str, unlocked) -> str:
    """One-line text describing what a ship of this class will carry."""
    lo = compute_loadout(ship_class, unlocked)
    parts: list[str] = []
    if lo["armor"]:
        parts.append(TECHS[lo["armor"]]["name"])
    if lo["shield"]:
        parts.append(TECHS[lo["shield"]]["name"])
    if lo["weapon"] and lo["weapon_count"]:
        parts.append(f"{lo['weapon_count']}× {TECHS[lo['weapon']]['name']}")
    for sp in lo["specials"]:
        parts.append(TECHS[sp]["name"])
    if not parts:
        return "(no equipment — research armor / weapons / shields)"
    s = lo["stats"]
    shield_part = ""
    if s.get("shield_capacity"):
        shield_part = f" / shield {s['shield_capacity']}↺{s['shield_regen']}"
    return (" · ".join(parts)
            + f"   [{s['space_used']}/{s['space_total']} space, "
              f"+{s['attack']} atk / +{s['hull']} hull{shield_part}]")


def stored_loadout_summary(ship) -> str:
    """One-line description of an actual ship's frozen loadout."""
    parts: list[str] = []
    if ship.armor_tech:
        parts.append(TECHS.get(ship.armor_tech, {}).get("name", ship.armor_tech))
    if ship.shield_tech:
        parts.append(TECHS.get(ship.shield_tech, {}).get("name", ship.shield_tech))
    if ship.weapon_tech and ship.weapon_count:
        wname = TECHS.get(ship.weapon_tech, {}).get("name", ship.weapon_tech)
        parts.append(f"{ship.weapon_count}× {wname}")
    for sp_id in (ship.specials or []):
        parts.append(TECHS.get(sp_id, {}).get("name", sp_id))
    if not parts:
        return "(unequipped — built before refit tech)"
    return " · ".join(parts)

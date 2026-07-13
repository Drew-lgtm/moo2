"""Refit shipyard — pay BC to bring an existing hull up to current tech.

Ships freeze their loadout at construction (see ``ecs.ship_design``).
That means an early-game frigate keeps its lasers and titanium armor
forever, even if you've since researched Plasma Cannons and Neutronium.
The refit shipyard is the close-the-loop option: pay BC at a friendly
colony to swap in the current best gear instead of building a fresh
hull from scratch.

- Refit is offered for **every player ship parked at the colony's star**.
- Cost per ship is 40% of the ship class's build cost — much cheaper
  than rebuilding, but not free.
- Ships that already match the empire's current best loadout are
  skipped (no charge).
- The whole fleet refits in one transaction or none (if BC is short).
"""
from __future__ import annotations

from ecs.components import (
    Empire, TechState, Ship, ShipOwner, ShipAt,
)
from ecs.ships import SHIPS
from ecs.ship_design import compute_loadout
from ecs.db import get_connection, update_empire_economy


# Fraction of build cost charged to bring a hull up to current tech.
REFIT_COST_FRACTION = 0.4


def _empire_unlocked(cm, empire_id: int) -> set[str]:
    for _e, ts in cm.get_all(TechState):
        if ts.empire_id == empire_id:
            return set(ts.unlocked)
    return set()


def _empire_for(cm, empire_id: int):
    for _e, emp in cm.get_all(Empire):
        if emp.id == empire_id:
            return emp
    return None


def ships_at_star(cm, star_entity: int, empire_id: int) -> list[int]:
    """Player's ships currently parked at the given star."""
    out: list[int] = []
    for ship_entity, at in cm.get_all(ShipAt):
        owner = cm.get_component(ship_entity, ShipOwner)
        if owner is None or owner.empire_id != empire_id:
            continue
        if at.star_entity == star_entity:
            out.append(ship_entity)
    return out


def _loadout_matches(ship: Ship, target: dict) -> bool:
    return (ship.armor_tech == target.get("armor")
            and ship.shield_tech == target.get("shield")
            and ship.weapon_tech == target.get("weapon")
            and (ship.weapon_count or 0) == (target.get("weapon_count") or 0)
            and getattr(ship, "weapon_mount", "normal") == target.get("weapon_mount", "normal")
            and set(ship.specials or []) == set(target.get("specials") or []))


def _target_for_ship(ship: Ship, unlocked: set, designs_mgr, empire_id: int) -> dict:
    """The loadout a refit brings this hull up to. Prefers the empire's
    newest saved design for the ship's class (so refit honours your
    blueprints, mounts and all); falls back to the auto best-tech
    loadout when no design exists for that class. Returns a uniform dict
    with keys armor / shield / weapon / weapon_count / weapon_mount /
    specials."""
    if designs_mgr is not None:
        matches = designs_mgr.for_empire_class(empire_id, ship.ship_class)
        if matches:
            d = max(matches, key=lambda x: x.id)  # newest design wins
            return {
                "armor": d.armor_tech, "shield": d.shield_tech,
                "weapon": d.weapon_tech, "weapon_count": d.weapon_count,
                "weapon_mount": d.weapon_mount, "specials": list(d.specials),
            }
    lo = compute_loadout(ship.ship_class, unlocked)
    return {
        "armor": lo.get("armor"), "shield": lo.get("shield"),
        "weapon": lo.get("weapon"), "weapon_count": lo.get("weapon_count", 0),
        "weapon_mount": "normal", "specials": list(lo.get("specials") or []),
    }


def refit_cost(ship: Ship) -> int:
    """BC charged to refit this hull. Floor of 10."""
    base = SHIPS.get(ship.ship_class, {}).get("cost", 50)
    return max(10, int(round(base * REFIT_COST_FRACTION)))


def plan_refit(cm, star_entity: int, empire_id: int, designs_mgr=None) -> dict:
    """Inspect every player ship at this star and figure out which ones
    need refitting + the total cost. Each ship's target is its class's
    newest saved design (if any) else the auto best-tech loadout. No
    side effects."""
    unlocked = _empire_unlocked(cm, empire_id)
    entries = []
    total_cost = 0
    skipped = 0
    for se in ships_at_star(cm, star_entity, empire_id):
        ship = cm.get_component(se, Ship)
        if ship is None:
            continue
        target = _target_for_ship(ship, unlocked, designs_mgr, empire_id)
        if _loadout_matches(ship, target):
            skipped += 1
            continue
        cost = refit_cost(ship)
        entries.append({"entity": se, "ship": ship, "target": target, "cost": cost})
        total_cost += cost
    return {
        "entries": entries,
        "total_cost": total_cost,
        "skipped": skipped,
        "to_refit": len(entries),
    }


def refit_ships_at_star(game, star_entity: int, empire_id: int) -> dict:
    """Atomically refit every outdated player ship at the colony's star.
    Returns a result dict with ``status`` in {"ok", "unaffordable",
    "nothing"} plus counts so the UI can banner the outcome.
    """
    cm = game.component_mgr
    empire = _empire_for(cm, empire_id)
    if empire is None:
        return {"status": "nothing", "refitted": 0, "spent": 0, "cost": 0}

    plan = plan_refit(cm, star_entity, empire_id,
                      getattr(game, "ship_designs", None))
    if not plan["entries"]:
        return {"status": "nothing", "refitted": 0, "spent": 0,
                "cost": 0, "skipped": plan["skipped"]}
    if empire.bc < plan["total_cost"]:
        return {"status": "unaffordable", "refitted": 0, "spent": 0,
                "cost": plan["total_cost"], "bc": empire.bc}

    with get_connection() as conn:
        for entry in plan["entries"]:
            ship: Ship = entry["ship"]
            target = entry["target"]
            ship.armor_tech = target.get("armor")
            ship.shield_tech = target.get("shield")
            ship.weapon_tech = target.get("weapon")
            ship.weapon_count = target.get("weapon_count", 0)
            ship.weapon_mount = target.get("weapon_mount", "normal")
            ship.specials = list(target.get("specials") or [])
            conn.execute(
                "UPDATE ships SET armor_tech=?, shield_tech=?, weapon_tech=?, "
                "weapon_count=?, specials=?, weapon_mount=? WHERE id=?",
                (ship.armor_tech, ship.shield_tech, ship.weapon_tech,
                 ship.weapon_count, ",".join(ship.specials),
                 ship.weapon_mount, ship.id),
            )
        empire.bc -= plan["total_cost"]
        update_empire_economy(conn, empire.id, empire.bc,
                              empire.research_points)
        conn.commit()
    return {
        "status": "ok",
        "refitted": plan["to_refit"],
        "spent": plan["total_cost"],
        "cost": plan["total_cost"],
        "skipped": plan["skipped"],
    }

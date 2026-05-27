"""Ship fuel range — limits how far fleets can operate from supply.

A fleet can only move to a star within its empire's *fuel range* of a
**supply star**. Supply stars are systems with a colony belonging to:

- the empire itself, or
- an empire it has an **Open Borders** or **Alliance** treaty with
  (refuelling rights) — this is the "use allied planets to refuel and
  explore further" agreement.

Fuel range grows with drive tech (``techs.empire_fuel_range``). Without
a closer supply point, the only way to project power further is to
colonise/conquer forward or sign a refuelling treaty with a neighbour
whose worlds are out where you want to go.
"""
from __future__ import annotations

import math

from ecs.components import Position, Owner, Orbiting, TechState, Empire
from ecs.techs import empire_fuel_range, BASE_FUEL_RANGE
from ecs.fleet import PIXELS_PER_PARSEC
from ecs.diplomacy import OPEN_BORDERS, ALLIANCE


def empire_fuel_range_px(component_mgr, empire_id: int) -> float:
    """Fuel range in pixels for this empire's best drive tech."""
    rng = BASE_FUEL_RANGE
    for _eid, tech in component_mgr.get_all(TechState):
        if tech.empire_id == empire_id:
            rng = empire_fuel_range(tech.unlocked)
            break
    return rng * PIXELS_PER_PARSEC


def _refuelling_empires(game, empire_id: int) -> set[int]:
    """Empires whose colonies will refuel ``empire_id``: itself plus any
    Open-Borders / Alliance partner."""
    refuelers = {empire_id}
    diplo = getattr(game, "diplomacy", None)
    if diplo is None:
        return refuelers
    for _eid, emp in game.component_mgr.get_all(Empire):
        if emp.id == empire_id:
            continue
        if (diplo.has_treaty(empire_id, emp.id, OPEN_BORDERS)
                or diplo.has_treaty(empire_id, emp.id, ALLIANCE)):
            refuelers.add(emp.id)
    return refuelers


def supply_stars(game, empire_id: int) -> set[int]:
    """Star entities that can refuel ``empire_id`` (own + allied
    colonies)."""
    cm = game.component_mgr
    refuelers = _refuelling_empires(game, empire_id)
    stars: set[int] = set()
    for planet_entity, owner in cm.get_all(Owner):
        if owner.empire_id not in refuelers:
            continue
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is not None:
            stars.add(orbit.star_entity)
    return stars


def in_fuel_range(game, empire_id: int, dest_star_entity: int,
                  supply: set[int] | None = None) -> bool:
    """True if ``dest_star_entity`` is within fuel range of any supply
    star. ``supply`` can be passed in to avoid recomputing it per call."""
    cm = game.component_mgr
    if supply is None:
        supply = supply_stars(game, empire_id)
    if not supply:
        return False
    if dest_star_entity in supply:
        return True  # refuel on arrival
    dest_pos = cm.get_component(dest_star_entity, Position)
    if dest_pos is None:
        return False
    rng = empire_fuel_range_px(cm, empire_id)
    for s in supply:
        spos = cm.get_component(s, Position)
        if spos is None:
            continue
        if math.hypot(dest_pos.x - spos.x, dest_pos.y - spos.y) <= rng:
            return True
    return False


def reachable_stars(game, empire_id: int) -> set[int]:
    """All star entities the empire's fleets can currently reach."""
    cm = game.component_mgr
    supply = supply_stars(game, empire_id)
    if not supply:
        return set()
    rng = empire_fuel_range_px(cm, empire_id)
    out: set[int] = set(supply)
    # Pre-fetch supply positions.
    supply_pos = [cm.get_component(s, Position) for s in supply]
    supply_pos = [p for p in supply_pos if p is not None]
    from ecs.components import StarRef
    for star_entity, _ref in cm.get_all(StarRef):
        if star_entity in out:
            continue
        pos = cm.get_component(star_entity, Position)
        if pos is None:
            continue
        for spos in supply_pos:
            if math.hypot(pos.x - spos.x, pos.y - spos.y) <= rng:
                out.add(star_entity)
                break
    return out

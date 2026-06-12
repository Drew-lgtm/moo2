"""Fleet detection (sensors / radar).

An empire detects enemy ships that come within *sensor range* of any of
its detection sources — its colonies and its own ships. Sensor range
starts small and jumps once Tachyon Scanner (or better) is researched,
so investing in scanners reveals incoming attacks earlier.

Used by the galaxy view: enemy / neutral fleets in transit are only
drawn when detected; your own fleets are always visible.
"""
from __future__ import annotations

import math

from ecs.components import (
    Position, Owner, Orbiting, TechState, ShipAt, ShipOwner, ShipInTransit, Ship,
    Outpost,
)
from ecs.techs import empire_sensor_range, BASE_SENSOR_RANGE
from ecs.fleet import PIXELS_PER_PARSEC


def empire_sensor_range_px(component_mgr, empire_id: int) -> float:
    rng = BASE_SENSOR_RANGE
    for _eid, tech in component_mgr.get_all(TechState):
        if tech.empire_id == empire_id:
            rng = empire_sensor_range(tech.unlocked)
            break
    return rng * PIXELS_PER_PARSEC


def sensor_points(game, empire_id: int) -> list[tuple[float, float]]:
    """Positions that project the empire's sensors: its colonies, its
    parked ships, and its in-transit ships (interpolated)."""
    cm = game.component_mgr
    pts: list[tuple[float, float]] = []

    # Colonies.
    for planet_entity, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is None:
            continue
        pos = cm.get_component(orbit.star_entity, Position)
        if pos is not None:
            pts.append((pos.x, pos.y))

    # Outposts — claim the system, project sensors from the star itself.
    for star_entity, op in cm.get_all(Outpost):
        if op.empire_id != empire_id:
            continue
        pos = cm.get_component(star_entity, Position)
        if pos is not None:
            pts.append((pos.x, pos.y))

    # Parked ships.
    for ship_entity, at in cm.get_all(ShipAt):
        sowner = cm.get_component(ship_entity, ShipOwner)
        if sowner is None or sowner.empire_id != empire_id:
            continue
        pos = cm.get_component(at.star_entity, Position)
        if pos is not None:
            pts.append((pos.x, pos.y))

    # In-transit ships (current interpolated position).
    for ship_entity, transit in cm.get_all(ShipInTransit):
        sowner = cm.get_component(ship_entity, ShipOwner)
        if sowner is None or sowner.empire_id != empire_id:
            continue
        fp = cm.get_component(transit.from_star_entity, Position)
        tp = cm.get_component(transit.to_star_entity, Position)
        if fp is None or tp is None:
            continue
        total = max(1, transit.total_turns)
        progress = max(0.0, min(1.0, 1.0 - transit.turns_remaining / total))
        pts.append((fp.x + (tp.x - fp.x) * progress, fp.y + (tp.y - fp.y) * progress))

    return pts


def is_detected(x: float, y: float, points: list[tuple[float, float]], range_px: float) -> bool:
    r2 = range_px * range_px
    for (px, py) in points:
        if (x - px) ** 2 + (y - py) ** 2 <= r2:
            return True
    return False

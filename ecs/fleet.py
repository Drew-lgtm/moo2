"""Fleet movement.

Player or AI issues a move via ``start_fleet_movement`` which switches
the involved ship entities from ShipAt to ShipInTransit, computes the
number of turns based on ship speed + parsec distance, and writes
through to ``ships``. ``fleet_tick`` decrements turns_remaining each
turn and, on arrival, swaps the component back to ShipAt at the
destination.
"""
from __future__ import annotations

import math

from ecs.components import (
    Position, Ship, ShipAt, ShipInTransit, ShipOwner, StarRef,
)
from ecs.ships import SHIPS
from ecs.db import get_connection, update_ship_transit


# Tunable: 50 px = 1 parsec. With our 1200x800 galaxy stars are roughly
# 1-4 parsecs apart, so a Frigate (speed 3) covers most of the map in
# 1-2 turns and a Dreadnought (speed 1) takes 1-4 turns.
PIXELS_PER_PARSEC = 50.0


def _distance_parsecs(pos_a, pos_b) -> float:
    dx = pos_a.x - pos_b.x
    dy = pos_a.y - pos_b.y
    return math.hypot(dx, dy) / PIXELS_PER_PARSEC


def turns_for(ship_class: str, from_pos, to_pos) -> int:
    parsecs = _distance_parsecs(from_pos, to_pos)
    speed = SHIPS.get(ship_class, {}).get("speed", 1)
    return max(1, math.ceil(parsecs / max(speed, 1)))


def start_fleet_movement(component_mgr, ship_entities, from_star_entity, to_star_entity):
    """Move the given ship entities from one star to another.

    Same source star is assumed; each ship's individual speed determines
    its own arrival turn (slower ships take longer than faster ones on
    the same route). Persists the new transit state.
    """
    if not ship_entities or from_star_entity == to_star_entity:
        return
    from_pos = component_mgr.get_component(from_star_entity, Position)
    to_pos = component_mgr.get_component(to_star_entity, Position)
    from_ref = component_mgr.get_component(from_star_entity, StarRef)
    to_ref = component_mgr.get_component(to_star_entity, StarRef)
    if from_pos is None or to_pos is None or from_ref is None or to_ref is None:
        return

    with get_connection() as conn:
        for ship_entity in ship_entities:
            ship = component_mgr.get_component(ship_entity, Ship)
            if ship is None:
                continue
            component_mgr.remove_component(ship_entity, ShipAt)
            turns = turns_for(ship.ship_class, from_pos, to_pos)
            component_mgr.add_component(
                ship_entity,
                ShipInTransit(
                    from_star_entity=from_star_entity,
                    to_star_entity=to_star_entity,
                    turns_remaining=turns,
                    total_turns=turns,
                ),
            )
            update_ship_transit(conn, ship.id, from_ref.db_id, to_ref.db_id, turns)
        conn.commit()


def fleet_tick(game, new_turn: int):
    """advance_turn callback. Decrement in-transit timers; on arrival,
    swap ShipInTransit -> ShipAt(dest) and clear the DB transit fields."""
    cm = game.component_mgr
    arrivals: list[tuple[int, int]] = []  # (ship_entity, dest_star_entity)
    transit_updates: list[tuple[int, int, int | None, int, int]] = []
    # (ship_id, current_star_db_id, dest_star_db_id_or_None, turns_remaining, ship_entity)

    for ship_entity, transit in cm.get_all(ShipInTransit):
        transit.turns_remaining -= 1
        ship = cm.get_component(ship_entity, Ship)
        if ship is None:
            continue
        if transit.turns_remaining <= 0:
            arrivals.append((ship_entity, transit.to_star_entity))
            dest_ref = cm.get_component(transit.to_star_entity, StarRef)
            if dest_ref is not None:
                transit_updates.append((ship.id, dest_ref.db_id, None, 0, ship_entity))
        else:
            # Still moving; persist the new turns_remaining.
            from_ref = cm.get_component(transit.from_star_entity, StarRef)
            to_ref = cm.get_component(transit.to_star_entity, StarRef)
            if from_ref is not None and to_ref is not None:
                transit_updates.append(
                    (ship.id, from_ref.db_id, to_ref.db_id, transit.turns_remaining, ship_entity)
                )

    # Apply ECS arrivals.
    for ship_entity, dest_entity in arrivals:
        cm.remove_component(ship_entity, ShipInTransit)
        cm.add_component(ship_entity, ShipAt(star_entity=dest_entity))

    if not transit_updates:
        return
    with get_connection() as conn:
        for ship_id, cur, dest, turns, _eid in transit_updates:
            update_ship_transit(conn, ship_id, cur, dest, turns)
        conn.commit()

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
    Position, Ship, ShipAt, ShipInTransit, ShipOwner, StarRef, TechState,
)
from ecs.ships import SHIPS
from ecs.techs import empire_speed_bonus as _empire_speed_bonus
from ecs.db import get_connection, update_ship_transit


# Galaxy scale: 25 px per parsec puts the 1200x744 play area at ~70
# parsecs across the diagonal. Combined with the current ship-class
# base speeds (Frigate 3, Carrier/Cruiser 2, Battleship/Dreadnought 1),
# nearest neighbours are 2-5 parsec hops (1-2 turns even for a Drednought)
# while a cross-galaxy trip is ~20 turns for a Frigate and 50-70 turns
# for a Dreadnought — early-game expansion has real friction. The
# tighter scale exists so the future engine-tech upgrade has somewhere
# to shrink travel toward MOO2-style 1-2 turn end-game jumps; bumping
# this constant is the entire knob for "shrink the galaxy". Don't
# rebalance ship speeds for now — those move via the tech tree.
PIXELS_PER_PARSEC = 25.0


def _distance_parsecs(pos_a, pos_b) -> float:
    dx = pos_a.x - pos_b.x
    dy = pos_a.y - pos_b.y
    return math.hypot(dx, dy) / PIXELS_PER_PARSEC


def turns_for(ship_class: str, from_pos, to_pos, speed_bonus: int = 0) -> int:
    """Turns for one ship of ``ship_class`` to cross from->to.

    ``speed_bonus`` comes from the owning empire's best drive tech and
    is added flat to the ship class's base speed before dividing.
    """
    parsecs = _distance_parsecs(from_pos, to_pos)
    base = SHIPS.get(ship_class, {}).get("speed", 1)
    speed = max(1, base + speed_bonus)
    return max(1, math.ceil(parsecs / speed))


def empire_speed_bonus(component_mgr, empire_id: int) -> int:
    """Look up the empire's best drive bonus from its TechState."""
    for _eid, tech in component_mgr.get_all(TechState):
        if tech.empire_id == empire_id:
            return _empire_speed_bonus(tech.unlocked)
    return 0


def start_fleet_movement(component_mgr, ship_entities, from_star_entity, to_star_entity):
    """Move the given ship entities from one star to another as a fleet.

    The whole fleet travels at the slowest member's speed, so a mixed
    Frigate + Dreadnought fleet arrives together rather than getting
    spread across multiple turns. Persists the new transit state.
    """
    if not ship_entities or from_star_entity == to_star_entity:
        return
    from_pos = component_mgr.get_component(from_star_entity, Position)
    to_pos = component_mgr.get_component(to_star_entity, Position)
    from_ref = component_mgr.get_component(from_star_entity, StarRef)
    to_ref = component_mgr.get_component(to_star_entity, StarRef)
    if from_pos is None or to_pos is None or from_ref is None or to_ref is None:
        return

    # Owner's drive tech contributes a flat speed bonus to every ship
    # in the fleet. Assume same-owner fleet — read from the first ship.
    bonus = 0
    first_owner = component_mgr.get_component(ship_entities[0], ShipOwner)
    if first_owner is not None:
        bonus = empire_speed_bonus(component_mgr, first_owner.empire_id)

    # Pass 1: find the slowest ship's turn count for this leg.
    fleet_turns = 0
    for ship_entity in ship_entities:
        ship = component_mgr.get_component(ship_entity, Ship)
        if ship is None:
            continue
        fleet_turns = max(fleet_turns, turns_for(ship.ship_class, from_pos, to_pos, bonus))
    if fleet_turns < 1:
        fleet_turns = 1

    # Pass 2: stamp the same turns_remaining onto every ship so they
    # arrive together.
    with get_connection() as conn:
        for ship_entity in ship_entities:
            ship = component_mgr.get_component(ship_entity, Ship)
            if ship is None:
                continue
            component_mgr.remove_component(ship_entity, ShipAt)
            component_mgr.add_component(
                ship_entity,
                ShipInTransit(
                    from_star_entity=from_star_entity,
                    to_star_entity=to_star_entity,
                    turns_remaining=fleet_turns,
                    total_turns=fleet_turns,
                ),
            )
            update_ship_transit(conn, ship.id, from_ref.db_id, to_ref.db_id, fleet_turns)
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

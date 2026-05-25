"""Star-system combat.

When two or more empires have parked ships at the same star at the end
of a turn, combat resolves. The model is intentionally simple for now:

- Each side's "attack power" = sum of attack across its ships.
- Each side absorbs damage equal to the sum of every OTHER side's
  attack — so 3-way standoffs are brutal but rare.
- Damage destroys cheapest (lowest hull) ships first; ships are
  all-or-nothing (no partial damage carried).

A combat log entry is appended to ``game.last_combats`` so future UI
can surface what happened. For now players will see fleet badges
change.
"""
from __future__ import annotations

from ecs.components import Ship, ShipOwner, ShipAt, ShipInTransit
from ecs.ships import SHIPS
from ecs.db import get_connection, delete_ship


def _attack_of(component_mgr, ship_entity: int) -> int:
    ship = component_mgr.get_component(ship_entity, Ship)
    if ship is None:
        return 0
    return SHIPS.get(ship.ship_class, {}).get("attack", 0)


def _hull_of(component_mgr, ship_entity: int) -> int:
    ship = component_mgr.get_component(ship_entity, Ship)
    if ship is None:
        return 0
    return SHIPS.get(ship.ship_class, {}).get("hull", 0)


def _compute_losses(component_mgr, ships: list[int], damage: int) -> list[int]:
    """Return ship entities destroyed. Cheapest hull dies first; no
    partial-damage carry between turns."""
    if damage <= 0 or not ships:
        return []
    sorted_ships = sorted(ships, key=lambda e: _hull_of(component_mgr, e))
    losses: list[int] = []
    remaining = damage
    for ship_entity in sorted_ships:
        hull = _hull_of(component_mgr, ship_entity)
        if hull <= 0:
            continue
        if remaining >= hull:
            losses.append(ship_entity)
            remaining -= hull
        else:
            break
    return losses


def _destroy_ship(game, ship_entity: int):
    cm = game.component_mgr
    for comp_type in (Ship, ShipOwner, ShipAt, ShipInTransit):
        cm.remove_component(ship_entity, comp_type)
    game.entity_mgr.destroy_entity(ship_entity)


def combat_tick(game, new_turn: int):
    """Resolve combat at every star where two or more empires have ships."""
    cm = game.component_mgr
    # star_entity -> {empire_id: [ship_entity]}
    by_star: dict[int, dict[int, list[int]]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        owner = cm.get_component(ship_entity, ShipOwner)
        if owner is None:
            continue
        by_star.setdefault(at.star_entity, {}).setdefault(owner.empire_id, []).append(ship_entity)

    log: list[dict] = []
    destroyed_ids: list[int] = []
    destroyed_entities: list[int] = []

    for star_entity, by_owner in by_star.items():
        if len(by_owner) < 2:
            continue

        side_attack = {
            empire_id: sum(_attack_of(cm, e) for e in ships)
            for empire_id, ships in by_owner.items()
        }
        side_losses: dict[int, list[int]] = {}
        for empire_id, ships in by_owner.items():
            damage = sum(side_attack[other] for other in by_owner if other != empire_id)
            side_losses[empire_id] = _compute_losses(cm, ships, damage)

        # Record the engagement before mutating.
        log_entry = {
            "turn": new_turn,
            "star_entity": star_entity,
            "losses_by_empire": {
                eid: len(losses) for eid, losses in side_losses.items() if losses
            },
            "attack_by_empire": dict(side_attack),
        }
        if log_entry["losses_by_empire"]:
            log.append(log_entry)

        for empire_id, losses in side_losses.items():
            for ship_entity in losses:
                ship = cm.get_component(ship_entity, Ship)
                if ship is None:
                    continue
                destroyed_ids.append(ship.id)
                destroyed_entities.append(ship_entity)

    if destroyed_entities:
        with get_connection() as conn:
            for ship_id in destroyed_ids:
                delete_ship(conn, ship_id)
            conn.commit()
        for ship_entity in destroyed_entities:
            _destroy_ship(game, ship_entity)

    # Append to a rolling log on Game for future UI surfacing.
    if log:
        existing = getattr(game, "last_combats", [])
        # Keep at most the 20 most recent engagements.
        game.last_combats = (existing + log)[-20:]

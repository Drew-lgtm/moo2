"""Scrapping ships — decommission a hull for a partial BC refund.

Old frigates clogging a border system, a mothballed early-game fleet
made obsolete by Doom Stars — scrapping clears them and hands back a
fraction of their original build cost, mirroring MOO2's scrap option.
Cheaper than letting upkeep bleed you, and the recovered BC seeds the
next generation of ships.
"""
from __future__ import annotations

from ecs.components import Ship, ShipOwner, ShipAt, ShipInTransit, Empire
from ecs.ships import SHIPS
from ecs.db import get_connection, delete_ship, update_empire_economy


# Fraction of a hull's build cost recovered when scrapped.
SCRAP_REFUND_FRACTION = 0.25


def scrap_value(ship_class: str) -> int:
    """BC recovered from scrapping one hull of this class."""
    cost = SHIPS.get(ship_class, {}).get("cost", 0)
    return int(cost * SCRAP_REFUND_FRACTION)


def scrap_ships(game, ship_entities: list[int]) -> dict:
    """Scrap the given ships: remove them (ECS + DB) and refund a
    fraction of their build cost to the owning empire's treasury.

    Returns ``{"scrapped": int, "refund": int}``. Ships owned by
    different empires are each refunded to their own owner (in practice
    the caller passes one empire's ships)."""
    cm = game.component_mgr
    refunds: dict[int, int] = {}   # empire_id -> BC
    db_ids: list[int] = []
    scrapped = 0
    for e in ship_entities:
        ship = cm.get_component(e, Ship)
        owner = cm.get_component(e, ShipOwner)
        if ship is None or owner is None:
            continue
        refunds[owner.empire_id] = refunds.get(owner.empire_id, 0) + scrap_value(
            ship.ship_class)
        if ship.id is not None:
            db_ids.append(ship.id)
        for comp in (Ship, ShipOwner, ShipAt, ShipInTransit):
            cm.remove_component(e, comp)
        game.entity_mgr.destroy_entity(e)
        scrapped += 1

    if scrapped == 0:
        return {"scrapped": 0, "refund": 0}

    # Credit refunds to each owner's ECS Empire, then persist ships +
    # economy in one transaction.
    total_refund = 0
    emp_by_id = {emp.id: emp for _x, emp in cm.get_all(Empire)}
    for empire_id, bc in refunds.items():
        emp = emp_by_id.get(empire_id)
        if emp is not None:
            emp.bc += bc
            total_refund += bc

    with get_connection() as conn:
        for sid in db_ids:
            delete_ship(conn, sid)
        for empire_id, _bc in refunds.items():
            emp = emp_by_id.get(empire_id)
            if emp is not None:
                update_empire_economy(conn, empire_id, emp.bc, emp.research_points)
        conn.commit()

    return {"scrapped": scrapped, "refund": total_refund}

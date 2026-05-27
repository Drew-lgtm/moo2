"""End-game conditions: conquest victory, elimination, scoring.

Checked after each turn's systems resolve. An empire with no colonies
left is eliminated (its stray ships are scrapped). Outcomes, from the
*player's* perspective:

- Player is the sole surviving empire    → Conquest victory.
- Player has lost their last colony      → Defeat (eliminated).

Diplomatic victory is handled separately by the Galactic Council, which
routes through the same end screen + hall of fame.

The score formula here is a placeholder — colonies, population, and
treasury — to be refined later.
"""
from __future__ import annotations

from ecs.components import (
    Empire, Owner, Population, Ship, ShipOwner, ShipAt, ShipInTransit,
)
from ecs.db import get_connection, delete_ship, insert_hall_of_fame


def colony_counts(component_mgr) -> dict[int, int]:
    counts: dict[int, int] = {}
    for _eid, owner in component_mgr.get_all(Owner):
        counts[owner.empire_id] = counts.get(owner.empire_id, 0) + 1
    return counts


def living_empires(component_mgr) -> list[int]:
    """Empire ids that still hold at least one colony."""
    return [eid for eid, n in colony_counts(component_mgr).items() if n > 0]


def empire_score(game, empire_id: int) -> int:
    """Placeholder score: colonies + population + a slice of treasury.
    Refine once a proper scoring model lands."""
    cm = game.component_mgr
    colonies = pop = 0
    for eid, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        colonies += 1
        p = cm.get_component(eid, Population)
        if p is not None:
            pop += p.current
    emp = next((e for _x, e in cm.get_all(Empire) if e.id == empire_id), None)
    bank = (emp.bc + emp.research_points) if emp is not None else 0
    return colonies * 1000 + pop * 100 + bank // 10


def _scrap_empire_ships(game, empire_id: int):
    """Delete every ship of an eliminated empire (ECS + DB)."""
    cm = game.component_mgr
    doomed: list[tuple[int, int]] = []  # (ship_entity, ship_db_id)
    for ship_entity, owner in cm.get_all(ShipOwner):
        if owner.empire_id != empire_id:
            continue
        ship = cm.get_component(ship_entity, Ship)
        doomed.append((ship_entity, ship.id if ship else None))
    if not doomed:
        return
    with get_connection() as conn:
        for _e, sid in doomed:
            if sid is not None:
                delete_ship(conn, sid)
        conn.commit()
    for ship_entity, _sid in doomed:
        for comp in (Ship, ShipOwner, ShipAt, ShipInTransit):
            cm.remove_component(ship_entity, comp)
        game.entity_mgr.destroy_entity(ship_entity)


def check_endgame(game) -> dict | None:
    """Return an end-game result dict (player perspective) or None.

    {"result": "victory"|"defeat", "mode": "Conquest", "winner_id": int}
    Also scraps the fleets of any empire that just lost its last colony.
    """
    cm = game.component_mgr
    player = game.player_empire()
    if player is None:
        return None

    counts = colony_counts(cm)
    all_empires = [e.id for _x, e in cm.get_all(Empire)]
    living = [eid for eid in all_empires if counts.get(eid, 0) > 0]

    # Scrap fleets of newly-eliminated empires (no colonies left).
    for eid in all_empires:
        if counts.get(eid, 0) == 0:
            _scrap_empire_ships(game, eid)

    player_alive = counts.get(player.id, 0) > 0

    if not player_alive:
        # Player wiped out — the strongest survivor is the de-facto victor.
        winner = max(living, key=lambda e: empire_score(game, e)) if living else player.id
        return {"result": "defeat", "mode": "Conquest", "winner_id": winner}

    if len(living) == 1 and living[0] == player.id:
        return {"result": "victory", "mode": "Conquest", "winner_id": player.id}

    return None


def record_result(game, winner_id: int, outcome: str):
    """Write the winning empire to the persistent hall of fame."""
    cm = game.component_mgr
    emp = next((e for _x, e in cm.get_all(Empire) if e.id == winner_id), None)
    if emp is None:
        return
    score = empire_score(game, winner_id)
    turn = getattr(game.galaxy, "turn", 0)
    with get_connection() as conn:
        insert_hall_of_fame(conn, emp.name, emp.race_type, score, outcome, turn)
        conn.commit()

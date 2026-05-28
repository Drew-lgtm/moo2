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
    Empire, Owner, Population, BuildState, TechState,
    Ship, ShipOwner, ShipAt, ShipInTransit,
)
from ecs.ships import SHIPS
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
    """Raw empire score across six MOO2-flavoured pillars.

    The components, weighted so each contributes meaningfully in mid-
    to-late game:

    - **Population**   pop × 10           — the raw size of your people
    - **Colonies**     colonies × 50      — geographic spread
    - **Tech**         techs × 80         — knowledge accumulated
    - **Buildings**    sum × 20           — built-up empire
    - **Economy**      (BC + 2*RP) // 10  — banked resources & science
    - **Military**     0.3 × Σ ship_cost  — investment in fleet

    The result here is the *raw* civic score. ``record_result`` then
    layers victory-mode bonus and a turn-speed multiplier on top before
    writing to the Hall of Fame.
    """
    cm = game.component_mgr
    colonies = pop = buildings = 0
    for eid, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        colonies += 1
        p = cm.get_component(eid, Population)
        if p is not None:
            pop += p.current
        bs = cm.get_component(eid, BuildState)
        if bs is not None:
            buildings += len(bs.completed)

    emp = next((e for _x, e in cm.get_all(Empire) if e.id == empire_id), None)
    bc = emp.bc if emp else 0
    rp = emp.research_points if emp else 0

    techs = 0
    for _x, ts in cm.get_all(TechState):
        if ts.empire_id == empire_id:
            techs = len(ts.unlocked)
            break

    fleet_value = 0
    for ship_entity, owner in cm.get_all(ShipOwner):
        if owner.empire_id != empire_id:
            continue
        ship = cm.get_component(ship_entity, Ship)
        if ship is not None:
            fleet_value += SHIPS.get(ship.ship_class, {}).get("cost", 0)

    return (
        pop * 10
        + colonies * 50
        + techs * 80
        + buildings * 20
        + (bc + rp * 2) // 10
        + int(fleet_value * 0.3)
    )


# Outcome-specific bonuses applied to the raw score in ``record_result``.
# Conquest is the hardest path so it pays best; diplomatic still rewards
# play to the end; an accepted defeat preserves the run but doesn't
# inflate it.
SCORE_OUTCOME_BONUS = {
    "Conquest":   1.5,
    "Diplomatic": 1.3,
    "Defeat":     1.0,
}


def _turn_speed_multiplier(turn: int) -> float:
    """Faster wins score higher. Linear decay from 1.0 at turn 0 down to
    a floor of 0.4 by turn 500 — so a long grind still counts."""
    return max(0.4, 1.0 - turn / 1000.0)


def final_score(game, empire_id: int, outcome: str) -> int:
    """Hall-of-Fame score = raw × outcome bonus × speed multiplier."""
    raw = empire_score(game, empire_id)
    bonus = SCORE_OUTCOME_BONUS.get(outcome, 1.0)
    speed = _turn_speed_multiplier(getattr(game.galaxy, "turn", 0))
    return int(round(raw * bonus * speed))


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
    """Write the winning empire to the persistent Hall of Fame. If the
    player lost (a non-player empire is the winner), also record the
    player's run with the "Defeat" outcome so attempts accumulate even
    when you lose."""
    cm = game.component_mgr
    turn = getattr(game.galaxy, "turn", 0)
    rows: list[tuple[Empire, str]] = []

    winner = next((e for _x, e in cm.get_all(Empire) if e.id == winner_id), None)
    if winner is not None:
        rows.append((winner, outcome))

    player = game.player_empire()
    if player is not None and (winner is None or player.id != winner.id):
        rows.append((player, "Defeat"))

    with get_connection() as conn:
        for emp, perspective in rows:
            score = final_score(game, emp.id, perspective)
            insert_hall_of_fame(conn, emp.name, emp.race_type, score, perspective, turn)
        conn.commit()

"""First-pass production model.

Stub: each owned planet contributes a flat per-turn BC and research,
determined by its size and type. There is no population, no worker
assignment, no food. Empire totals accumulate on every advance_turn.
"""
from __future__ import annotations

from ecs.components import Planet, Owner, Empire
from ecs.db import get_connection, update_empire_economy


SIZE_BASE = {
    "Tiny": 1,
    "Small": 2,
    "Medium": 4,
    "Large": 6,
    "Huge": 8,
}

BC_MULT = {
    "Terran":    1.5,
    "Gaia":      2.0,
    "Ocean":     1.3,
    "Jungle":    1.2,
    "Arid":      1.0,
    "Desert":    1.0,
    "Tundra":    0.9,
    "Steppe":    1.1,
    "Barren":    0.6,
    "Radiated":  0.5,
    "Toxic":     0.5,
    "Inferno":   0.4,
    "Volcanic":  0.6,
    "Asteroids": 0.0,
    "Gas Giant": 0.0,
}

RESEARCH_MULT = {
    "Terran":    1.0,
    "Gaia":      1.2,
    "Ocean":     0.9,
    "Jungle":    0.9,
    "Arid":      0.8,
    "Desert":    0.7,
    "Tundra":    0.7,
    "Steppe":    0.8,
    "Barren":    0.6,
    "Radiated":  0.5,
    "Toxic":     0.5,
    "Inferno":   0.4,
    "Volcanic":  0.5,
    "Asteroids": 0.0,
    "Gas Giant": 0.0,
}


def planet_output(planet) -> tuple[int, int]:
    """Return (bc, research) for one planet's per-turn output."""
    base = SIZE_BASE.get(planet.size, 0)
    bc = round(base * BC_MULT.get(planet.planet_type, 0))
    research = round(base * RESEARCH_MULT.get(planet.planet_type, 0))
    return bc, research


def _per_turn_by_empire(component_mgr) -> dict[int, tuple[int, int]]:
    """Sum (bc, research) per empire across every owned planet."""
    totals: dict[int, tuple[int, int]] = {}
    for entity_id, owner in component_mgr.get_all(Owner):
        planet = component_mgr.get_component(entity_id, Planet)
        if planet is None:
            continue
        bc, research = planet_output(planet)
        cur_bc, cur_res = totals.get(owner.empire_id, (0, 0))
        totals[owner.empire_id] = (cur_bc + bc, cur_res + research)
    return totals


def empire_per_turn(component_mgr, empire_id: int) -> tuple[int, int]:
    """Quick HUD-side lookup of one empire's per-turn output."""
    return _per_turn_by_empire(component_mgr).get(empire_id, (0, 0))


def production_tick(game, new_turn: int):
    """advance_turn callback. Adds each empire's per-turn output to its
    running BC/research totals and persists the new totals to the DB."""
    cm = game.component_mgr
    totals = _per_turn_by_empire(cm)
    if not totals:
        return

    # Update ECS components in place.
    updates: list[tuple[int, int, int]] = []  # (empire_id, bc, research)
    for _eid, empire in cm.get_all(Empire):
        bc_gain, res_gain = totals.get(empire.id, (0, 0))
        if bc_gain or res_gain:
            empire.bc += bc_gain
            empire.research_points += res_gain
        updates.append((empire.id, empire.bc, empire.research_points))

    with get_connection() as conn:
        for empire_id, bc, research in updates:
            update_empire_economy(conn, empire_id, bc, research)
        conn.commit()

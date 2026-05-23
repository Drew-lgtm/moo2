"""First-pass production model.

Stub: each owned planet contributes a flat per-turn BC and research,
determined by its size and type. There is no population, no worker
assignment, no food. Empire totals accumulate on every advance_turn.
"""
from __future__ import annotations

from ecs.components import Planet, Owner, Empire, Population
from ecs.db import get_connection, update_empire_economy, update_planet_population


SIZE_BASE = {
    "Tiny": 1,
    "Small": 2,
    "Medium": 4,
    "Large": 6,
    "Huge": 8,
}

SIZE_CAP = {
    "Tiny": 2,
    "Small": 4,
    "Medium": 8,
    "Large": 12,
    "Huge": 16,
}

TYPE_CAP_MULT = {
    "Terran":    1.0,
    "Gaia":      1.2,
    "Ocean":     0.9,
    "Jungle":    0.9,
    "Arid":      0.8,
    "Desert":    0.7,
    "Tundra":    0.7,
    "Steppe":    0.9,
    "Barren":    0.5,
    "Radiated":  0.3,
    "Toxic":     0.2,
    "Inferno":   0.2,
    "Volcanic":  0.4,
    "Asteroids": 0.0,
    "Gas Giant": 0.0,
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


def compute_max_population(planet_type: str, size: str) -> int:
    """How many pop units this planet can hold at full development."""
    cap = SIZE_CAP.get(size, 0) * TYPE_CAP_MULT.get(planet_type, 0)
    return int(round(cap))


def planet_output(planet: Planet, population: Population | None) -> tuple[int, int]:
    """Return (bc, research) for one planet's per-turn output.

    Output scales linearly with population: an uncolonized planet (no
    Population component) or one at zero pop produces nothing.
    """
    if population is None or population.current <= 0 or population.max <= 0:
        return 0, 0
    base = SIZE_BASE.get(planet.size, 0)
    bc_base = round(base * BC_MULT.get(planet.planet_type, 0))
    research_base = round(base * RESEARCH_MULT.get(planet.planet_type, 0))
    bc = bc_base * population.current // population.max
    research = research_base * population.current // population.max
    return bc, research


def _per_turn_by_empire(component_mgr) -> dict[int, tuple[int, int]]:
    """Sum (bc, research) per empire across every owned planet."""
    totals: dict[int, tuple[int, int]] = {}
    for entity_id, owner in component_mgr.get_all(Owner):
        planet = component_mgr.get_component(entity_id, Planet)
        if planet is None:
            continue
        population = component_mgr.get_component(entity_id, Population)
        bc, research = planet_output(planet, population)
        cur_bc, cur_res = totals.get(owner.empire_id, (0, 0))
        totals[owner.empire_id] = (cur_bc + bc, cur_res + research)
    return totals


def pop_growth_tick(game, new_turn: int):
    """advance_turn callback. Each colonized planet grows by +1 up to max."""
    cm = game.component_mgr
    updates: list[tuple[int, int, int]] = []
    for entity_id, pop in cm.get_all(Population):
        if pop.max <= 0:
            continue
        if pop.current < pop.max:
            pop.current += 1
        planet = cm.get_component(entity_id, Planet)
        if planet is not None:
            updates.append((planet.id, pop.current, pop.max))

    if not updates:
        return
    with get_connection() as conn:
        for planet_id, current, mx in updates:
            update_planet_population(conn, planet_id, current, mx)
        conn.commit()


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

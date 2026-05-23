"""First-pass production model.

Stub: each owned planet contributes a flat per-turn BC and research,
determined by its size and type. There is no population, no worker
assignment, no food. Empire totals accumulate on every advance_turn.
"""
from __future__ import annotations

from ecs.components import Planet, Owner, Empire, Population, BuildState
from ecs.db import (
    get_connection,
    update_empire_economy,
    update_planet_population,
    update_planet_build,
    insert_planet_building,
)
from ecs.projects import PROJECTS


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


def _building_bonus(build_state: BuildState | None) -> tuple[int, int]:
    """Sum the flat bc/research bonuses from completed buildings."""
    if build_state is None:
        return 0, 0
    bc = research = 0
    for project_id in build_state.completed:
        effects = PROJECTS.get(project_id, {}).get("effects", {})
        bc += effects.get("bc", 0)
        research += effects.get("research", 0)
    return bc, research


def planet_output(planet: Planet, population: Population | None,
                  build_state: BuildState | None = None) -> tuple[int, int]:
    """Return (bc, research) for one planet's per-turn output.

    Output scales linearly with population: an uncolonized planet (no
    Population component) or one at zero pop produces nothing. Completed
    buildings add flat bc/research on top of the scaled base.
    """
    if population is None or population.current <= 0 or population.max <= 0:
        return 0, 0
    base = SIZE_BASE.get(planet.size, 0)
    bc_base = round(base * BC_MULT.get(planet.planet_type, 0))
    research_base = round(base * RESEARCH_MULT.get(planet.planet_type, 0))
    bc = bc_base * population.current // population.max
    research = research_base * population.current // population.max
    bonus_bc, bonus_research = _building_bonus(build_state)
    return bc + bonus_bc, research + bonus_research


def _per_turn_by_empire(component_mgr) -> dict[int, tuple[int, int]]:
    """Sum (bc, research) per empire across every owned planet.

    Planets currently building a project redirect their BC to progress,
    so only research counts toward the empire HUD this turn. Research
    always flows to the empire.
    """
    totals: dict[int, tuple[int, int]] = {}
    for entity_id, owner in component_mgr.get_all(Owner):
        planet = component_mgr.get_component(entity_id, Planet)
        if planet is None:
            continue
        population = component_mgr.get_component(entity_id, Population)
        build_state = component_mgr.get_component(entity_id, BuildState)
        bc, research = planet_output(planet, population, build_state)
        if build_state and build_state.current_project:
            bc = 0  # diverted to project progress
        cur_bc, cur_res = totals.get(owner.empire_id, (0, 0))
        totals[owner.empire_id] = (cur_bc + bc, cur_res + research)
    return totals


POP_GROWTH_RATE = 0.4
"""Per-turn logistic coefficient. growth = r * pop * (max - pop) / max,
accumulated as a float in Population.growth_progress until a whole pop
unit can pop out. The curve decelerates near max."""


def pop_growth_tick(game, new_turn: int):
    """advance_turn callback. Logistic growth: faster mid-range, slower near
    cap. Accumulated fractional growth is kept in growth_progress."""
    cm = game.component_mgr
    updates: list[tuple[int, int, int, float]] = []
    for entity_id, pop in cm.get_all(Population):
        if pop.max <= 0:
            continue
        if pop.current < pop.max:
            increment = POP_GROWTH_RATE * pop.current * (pop.max - pop.current) / pop.max
            pop.growth_progress += increment
            while pop.growth_progress >= 1.0 and pop.current < pop.max:
                pop.current += 1
                pop.growth_progress -= 1.0
            if pop.current >= pop.max:
                pop.growth_progress = 0.0
        planet = cm.get_component(entity_id, Planet)
        if planet is not None:
            updates.append((planet.id, pop.current, pop.max, pop.growth_progress))

    if not updates:
        return
    with get_connection() as conn:
        for planet_id, current, mx, growth in updates:
            update_planet_population(conn, planet_id, current, mx, growth)
        conn.commit()


def empire_per_turn(component_mgr, empire_id: int) -> tuple[int, int]:
    """Quick HUD-side lookup of one empire's per-turn output."""
    return _per_turn_by_empire(component_mgr).get(empire_id, (0, 0))


def production_tick(game, new_turn: int):
    """advance_turn callback. Runs every owned planet's economy:

    - If a project is active, the planet's BC goes to project progress.
      On completion: the project moves to `completed`, flat effects
      (bc/research) start applying next turn via planet_output; one-off
      effects (max_pop) apply immediately.
    - Otherwise the planet's BC flows to the empire.
    - Research always flows to the empire regardless of build state.

    Mutates ECS components and persists to DB in one transaction.
    """
    cm = game.component_mgr

    empire_gains: dict[int, tuple[int, int]] = {}
    planet_build_updates: list[tuple[int, str | None, int]] = []  # planet_id, current_project, progress
    completed_inserts: list[tuple[int, str]] = []  # planet_id, project_id
    pop_updates: list[tuple[int, int, int, float]] = []  # planet_id, current, max, growth_progress (for hydroponics)

    for entity_id, owner in cm.get_all(Owner):
        planet = cm.get_component(entity_id, Planet)
        if planet is None:
            continue
        population = cm.get_component(entity_id, Population)
        build_state = cm.get_component(entity_id, BuildState)
        bc, research = planet_output(planet, population, build_state)

        bc_to_empire = bc
        if build_state and build_state.current_project:
            # BC diverts to project progress.
            build_state.progress += bc
            bc_to_empire = 0

            proj = PROJECTS.get(build_state.current_project)
            if proj and build_state.progress >= proj["cost"]:
                completed_id = build_state.current_project
                build_state.completed.append(completed_id)
                completed_inserts.append((planet.id, completed_id))

                # One-off effects applied at completion.
                effects = proj.get("effects", {})
                if "max_pop" in effects and population is not None:
                    population.max += effects["max_pop"]
                    pop_updates.append((planet.id, population.current, population.max, population.growth_progress))

                build_state.current_project = None
                build_state.progress = 0

            planet_build_updates.append((planet.id, build_state.current_project, build_state.progress))

        cur_bc, cur_res = empire_gains.get(owner.empire_id, (0, 0))
        empire_gains[owner.empire_id] = (cur_bc + bc_to_empire, cur_res + research)

    # Accumulate on Empire components.
    empire_updates: list[tuple[int, int, int]] = []
    for _eid, empire in cm.get_all(Empire):
        gain_bc, gain_res = empire_gains.get(empire.id, (0, 0))
        if gain_bc or gain_res:
            empire.bc += gain_bc
            empire.research_points += gain_res
        empire_updates.append((empire.id, empire.bc, empire.research_points))

    with get_connection() as conn:
        for empire_id, bc, research in empire_updates:
            update_empire_economy(conn, empire_id, bc, research)
        for planet_id, current_project, progress in planet_build_updates:
            update_planet_build(conn, planet_id, current_project, progress)
        for planet_id, project_id in completed_inserts:
            insert_planet_building(conn, planet_id, project_id)
        for planet_id, current, mx, growth in pop_updates:
            update_planet_population(conn, planet_id, current, mx, growth)
        conn.commit()

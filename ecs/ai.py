"""Per-turn AI for non-player empires.

Each tick, for every AI empire:
- Rebalance workers on each planet: enough farmers to feed it, then a
  60/40 split between workers and scientists.
- If a planet is idle (no current project, empty queue), queue the
  highest-priority building that's available (tech-gated) and not yet
  built.
- If the empire has no research target, pick the cheapest available
  tech that advances toward Capital.

Difficulty multiplies the AI's per-turn BC and research gains (applied
in economy.production_tick, not here). The behavior model is the same
across difficulties; only the cheating bonus changes.
"""
from __future__ import annotations

from ecs.components import Empire, Owner, Planet, Population, BuildState, TechState
from ecs.economy import FARMER_FOOD
from ecs.projects import PROJECTS, project_is_available
from ecs.techs import TECHS, is_available
from ecs.db import (
    get_connection,
    update_planet_workers,
    update_planet_build,
    update_empire_tech,
)
from ecs.personalities import get as get_personality


def ai_tick(game, new_turn: int):
    cm = game.component_mgr

    # Group owned entities per empire upfront.
    empire_planets: dict[int, list[int]] = {}
    for entity_id, owner in cm.get_all(Owner):
        empire_planets.setdefault(owner.empire_id, []).append(entity_id)

    tech_by_empire: dict[int, TechState] = {
        t.empire_id: t for _eid, t in cm.get_all(TechState)
    }

    pending_writes: list[tuple[str, tuple]] = []

    for _eid, empire in cm.get_all(Empire):
        if empire.is_player:
            continue
        personality = get_personality(empire.personality)
        tech_state = tech_by_empire.get(empire.id)
        unlocked = set(tech_state.unlocked) if tech_state else set()

        for entity_id in empire_planets.get(empire.id, []):
            _ai_rebalance_workers(cm, entity_id, personality["worker_pct"], pending_writes)
            _ai_queue_building(cm, entity_id, personality["build_priority"], unlocked, pending_writes)

        if tech_state is not None:
            _ai_pick_research(tech_state, personality["research_priority"], pending_writes)

    if not pending_writes:
        return
    with get_connection() as conn:
        for op, args in pending_writes:
            if op == "workers":
                update_planet_workers(conn, *args)
            elif op == "build":
                update_planet_build(conn, *args)
            elif op == "tech":
                update_empire_tech(conn, *args)
        conn.commit()


def _ai_rebalance_workers(cm, entity_id, worker_pct, pending_writes):
    """Cover food locally, then split the rest by ``worker_pct`` (0-100)
    between workers and scientists. Always reserve at least 1 worker when
    any non-farmer slot exists so early-game pop=2 still produces industry.
    """
    planet = cm.get_component(entity_id, Planet)
    pop = cm.get_component(entity_id, Population)
    if planet is None or pop is None or pop.current <= 0:
        return

    food_per_farmer = FARMER_FOOD.get(planet.planet_type, 0)
    if food_per_farmer <= 0:
        farmers = 0
    else:
        farmers = min(pop.current, (pop.current + food_per_farmer - 1) // food_per_farmer)

    remaining = pop.current - farmers
    if remaining <= 0:
        workers = 0
        scientists = 0
    else:
        workers = max(1, (remaining * worker_pct) // 100)
        scientists = remaining - workers

    # Only persist if anything actually changed — avoids touching the DB
    # on every tick when nothing moved.
    if (pop.farmers, pop.workers, pop.scientists) == (farmers, workers, scientists):
        return
    pop.farmers = farmers
    pop.workers = workers
    pop.scientists = scientists
    pending_writes.append(("workers", (planet.id, farmers, workers, scientists)))


def _ai_queue_building(cm, entity_id, build_priority, unlocked: set, pending_writes):
    build_state = cm.get_component(entity_id, BuildState)
    planet = cm.get_component(entity_id, Planet)
    if build_state is None or planet is None:
        return
    if build_state.current_project or build_state.queue:
        return

    completed = set(build_state.completed)
    for proj_id in build_priority:
        if proj_id in completed:
            continue
        if not project_is_available(proj_id, unlocked):
            continue
        build_state.current_project = proj_id
        pending_writes.append(("build", (planet.id, proj_id, build_state.progress)))
        return


def _ai_pick_research(tech_state: TechState, research_priority, pending_writes):
    if tech_state.current_target:
        return
    unlocked = set(tech_state.unlocked)
    for tech_id in research_priority:
        if tech_id in unlocked:
            continue
        if not is_available(tech_id, unlocked):
            continue
        tech_state.current_target = tech_id
        pending_writes.append((
            "tech",
            (tech_state.empire_id, tech_id, tech_state.progress),
        ))
        return

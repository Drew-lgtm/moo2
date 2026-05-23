"""Worker-based production model (MOO2-style).

Each planet's population is split into farmers, workers, and scientists.
Per-pop output depends on planet type:

- farmers produce food
- workers produce industry (which either funds a project or becomes BC)
- scientists produce research

Empire food balance = total food produced - total population. A negative
balance halts growth and starves 1 pop/turn off the biggest colony.

Completed buildings add flat per-turn bonuses to bc / research / food /
industry / max_pop / growth_rate. See ecs.projects.PROJECTS.
"""
from __future__ import annotations

from ecs.components import Planet, Owner, Empire, Population, BuildState
from ecs.db import (
    get_connection,
    update_empire_economy,
    update_planet_population,
    update_planet_build,
    update_planet_workers,
    insert_planet_building,
    save_planet_build_queue,
)
from ecs.projects import PROJECTS, building_growth_bonus


# ---- planet capacity (max population) ---------------------------------

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


# ---- per-worker outputs by planet type --------------------------------

FARMER_FOOD = {
    "Gaia":      3,
    "Terran":    2,
    "Ocean":     2,
    "Jungle":    2,
    "Steppe":    2,
    "Arid":      1,
    "Desert":    1,
    "Tundra":    1,
    "Barren":    0,
    "Radiated":  0,
    "Toxic":     0,
    "Inferno":   0,
    "Volcanic":  0,
    "Asteroids": 0,
    "Gas Giant": 0,
}

WORKER_INDUSTRY = {
    "Gaia":      1,
    "Terran":    1,
    "Ocean":     1,
    "Jungle":    1,
    "Arid":      1,
    "Desert":    1,
    "Tundra":    1,
    "Steppe":    1,
    "Barren":    1,
    "Radiated":  1,
    "Toxic":     1,
    "Inferno":   2,   # mining bonus
    "Volcanic":  2,
    "Asteroids": 2,
    "Gas Giant": 1,
}

SCIENTIST_RESEARCH = {
    "Gaia":      2,
    "Terran":    1,
    "Ocean":     1,
    "Jungle":    1,
    "Arid":      1,
    "Desert":    1,
    "Tundra":    1,
    "Steppe":    1,
    "Barren":    1,
    "Radiated":  1,
    "Toxic":     1,
    "Inferno":   1,
    "Volcanic":  1,
    "Asteroids": 1,
    "Gas Giant": 1,
}

POP_GROWTH_RATE = 0.4


# ---- capacity + default assignment ------------------------------------

def compute_max_population(planet_type: str, size: str) -> int:
    cap = SIZE_CAP.get(size, 0) * TYPE_CAP_MULT.get(planet_type, 0)
    return int(round(cap))


def default_assignment(planet_type: str, current: int) -> tuple[int, int, int]:
    """Auto-assign workers so the planet is at least self-sufficient.

    Returns (farmers, workers, scientists). Scientists start at 0 — the
    player allocates them manually.
    """
    if current <= 0:
        return 0, 0, 0
    food_per_farmer = FARMER_FOOD.get(planet_type, 0)
    if food_per_farmer <= 0:
        # Can't grow food locally; relies on empire surplus.
        return 0, current, 0
    needed_farmers = min(current, (current + food_per_farmer - 1) // food_per_farmer)
    return needed_farmers, current - needed_farmers, 0


def normalize_assignment(pop: Population):
    """Ensure farmers+workers+scientists == current. Excess goes to workers."""
    pop.farmers = max(0, pop.farmers)
    pop.workers = max(0, pop.workers)
    pop.scientists = max(0, pop.scientists)
    total = pop.farmers + pop.workers + pop.scientists
    if total == pop.current:
        return
    if total < pop.current:
        pop.workers += (pop.current - total)
    else:
        # Trim excess starting with workers, then scientists, then farmers.
        excess = total - pop.current
        for role in ("workers", "scientists", "farmers"):
            cur = getattr(pop, role)
            taken = min(cur, excess)
            setattr(pop, role, cur - taken)
            excess -= taken
            if excess == 0:
                break


# ---- per-planet output ------------------------------------------------

def _building_bonuses(build_state: BuildState | None):
    """Sum flat bonuses contributed by completed buildings."""
    food = industry = research = bc = 0
    if build_state is None:
        return food, industry, research, bc
    for project_id in build_state.completed:
        effects = PROJECTS.get(project_id, {}).get("effects", {})
        food += effects.get("food", 0)
        industry += effects.get("industry", 0)
        research += effects.get("research", 0)
        bc += effects.get("bc", 0)
    return food, industry, research, bc


def planet_output(planet: Planet, population: Population | None,
                  build_state: BuildState | None = None) -> tuple[int, int, int, int]:
    """Return (food, industry, research, bonus_bc) for one planet.

    - food / industry / research are per-pop outputs (farmers, workers,
      scientists respectively) plus building flat bonuses for the same
      stat.
    - bonus_bc is BC contributed by buildings regardless of project state
      (e.g. Marketplace's +3). Industry-as-BC happens in production_tick
      only when the planet has no active project.

    Uncolonized planets (no Population) return (0, 0, 0, 0).
    """
    if population is None or population.current <= 0:
        return 0, 0, 0, 0
    p_type = planet.planet_type
    food = population.farmers * FARMER_FOOD.get(p_type, 0)
    industry = population.workers * WORKER_INDUSTRY.get(p_type, 0)
    research = population.scientists * SCIENTIST_RESEARCH.get(p_type, 0)

    b_food, b_industry, b_research, b_bc = _building_bonuses(build_state)
    return food + b_food, industry + b_industry, research + b_research, b_bc


# ---- empire-level summaries (HUD + per-turn) --------------------------

def empire_per_turn(component_mgr, empire_id: int) -> dict[str, int]:
    """Per-turn projection for HUD display.

    Returns dict with: bc, research, food_balance, industry.
    BC = sum across planets of (industry if idle else 0) + building bonus_bc.
    Food balance = produced - pop.
    """
    bc_total = research_total = industry_total = 0
    food_produced = food_needed = 0

    for entity_id, owner in component_mgr.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        planet = component_mgr.get_component(entity_id, Planet)
        if planet is None:
            continue
        pop = component_mgr.get_component(entity_id, Population)
        build_state = component_mgr.get_component(entity_id, BuildState)
        food, industry, research, bonus_bc = planet_output(planet, pop, build_state)

        food_produced += food
        if pop is not None:
            food_needed += pop.current
        research_total += research
        industry_total += industry

        idle = not (build_state and build_state.current_project)
        bc_total += bonus_bc + (industry if idle else 0)

    return {
        "bc": bc_total,
        "research": research_total,
        "industry": industry_total,
        "food_balance": food_produced - food_needed,
    }


# ---- per-turn callbacks -----------------------------------------------

def pop_growth_tick(game, new_turn: int):
    """Logistic growth modulated by empire food balance.

    For each empire: compute food balance. If negative, no growth occurs
    for that empire's planets and 1 pop is removed from the biggest
    colony to stage the shortfall.
    """
    cm = game.component_mgr

    # Bucket per empire to compute food balance up-front.
    empire_planets: dict[int, list[int]] = {}
    for entity_id, owner in cm.get_all(Owner):
        empire_planets.setdefault(owner.empire_id, []).append(entity_id)

    pop_updates: list[tuple[int, int, int, float]] = []
    worker_updates: list[tuple[int, int, int, int]] = []

    for empire_id, entity_ids in empire_planets.items():
        food_produced = food_needed = 0
        for eid in entity_ids:
            planet = cm.get_component(eid, Planet)
            pop = cm.get_component(eid, Population)
            build_state = cm.get_component(eid, BuildState)
            if planet is None or pop is None:
                continue
            f, _i, _r, _b = planet_output(planet, pop, build_state)
            food_produced += f
            food_needed += pop.current

        food_balance = food_produced - food_needed

        if food_balance < 0:
            # Pick the planet with the most pop to absorb starvation.
            victim_eid = max(
                entity_ids,
                key=lambda e: getattr(cm.get_component(e, Population), "current", 0),
            )
            victim_pop = cm.get_component(victim_eid, Population)
            if victim_pop is not None and victim_pop.current > 0:
                victim_pop.current -= 1
                victim_pop.growth_progress = 0.0
                # Take from the role with the most slack: workers > scientists > farmers.
                for role in ("workers", "scientists", "farmers"):
                    if getattr(victim_pop, role) > 0:
                        setattr(victim_pop, role, getattr(victim_pop, role) - 1)
                        break
                victim_planet = cm.get_component(victim_eid, Planet)
                if victim_planet is not None:
                    pop_updates.append((victim_planet.id, victim_pop.current, victim_pop.max, victim_pop.growth_progress))
                    worker_updates.append((victim_planet.id, victim_pop.farmers, victim_pop.workers, victim_pop.scientists))
            continue  # No growth this turn for this empire

        # Normal logistic growth across each planet. We thread food_surplus
        # through the loop so new pop can default to farmers when food is
        # tight — saves the player from re-assigning every turn just to
        # avoid an immediate starvation tick.
        food_surplus = food_balance
        for eid in entity_ids:
            planet = cm.get_component(eid, Planet)
            pop = cm.get_component(eid, Population)
            build_state = cm.get_component(eid, BuildState)
            if planet is None or pop is None or pop.max <= 0:
                continue

            if pop.current < pop.max:
                bonus = building_growth_bonus(build_state.completed) if build_state else 0.0
                rate = POP_GROWTH_RATE + bonus
                increment = rate * pop.current * (pop.max - pop.current) / pop.max
                pop.growth_progress += increment

                grew = 0
                farmer_food = FARMER_FOOD.get(planet.planet_type, 0)
                while pop.growth_progress >= 1.0 and pop.current < pop.max:
                    pop.current += 1
                    food_surplus -= 1  # new pop consumes 1 food
                    # Prefer farmer if (a) the planet can grow food and
                    # (b) the empire surplus is now non-positive.
                    if farmer_food > 0 and food_surplus < 0:
                        pop.farmers += 1
                        food_surplus += farmer_food
                    else:
                        pop.workers += 1
                    pop.growth_progress -= 1.0
                    grew += 1
                if pop.current >= pop.max:
                    pop.growth_progress = 0.0

                pop_updates.append((planet.id, pop.current, pop.max, pop.growth_progress))
                if grew > 0:
                    worker_updates.append((planet.id, pop.farmers, pop.workers, pop.scientists))

    if not pop_updates and not worker_updates:
        return
    with get_connection() as conn:
        for planet_id, current, mx, growth in pop_updates:
            update_planet_population(conn, planet_id, current, mx, growth)
        for planet_id, f, w, s in worker_updates:
            update_planet_workers(conn, planet_id, f, w, s)
        conn.commit()


def production_tick(game, new_turn: int):
    """Apply per-planet industry/research to empires; resolve project progress."""
    cm = game.component_mgr

    empire_gains: dict[int, tuple[int, int]] = {}  # empire_id -> (bc, research)
    planet_build_updates: list[tuple[int, str | None, int]] = []
    queue_updates: list[tuple[int, list[str]]] = []
    completed_inserts: list[tuple[int, str]] = []
    pop_updates: list[tuple[int, int, int, float]] = []  # for max_pop bumps

    for entity_id, owner in cm.get_all(Owner):
        planet = cm.get_component(entity_id, Planet)
        if planet is None:
            continue
        pop = cm.get_component(entity_id, Population)
        build_state = cm.get_component(entity_id, BuildState)
        food, industry, research, bonus_bc = planet_output(planet, pop, build_state)

        bc_to_empire = bonus_bc
        if build_state and build_state.current_project:
            build_state.progress += industry
            queue_changed = False
            # Resolve as many completions as the progress allows (rare, but
            # cheap buildings + big industry can finish multiple per turn).
            while True:
                proj = PROJECTS.get(build_state.current_project) if build_state.current_project else None
                if proj is None or build_state.progress < proj["cost"]:
                    break
                completed_id = build_state.current_project
                build_state.completed.append(completed_id)
                completed_inserts.append((planet.id, completed_id))

                effects = proj.get("effects", {})
                if "max_pop" in effects and pop is not None:
                    pop.max += effects["max_pop"]
                    pop_updates.append((planet.id, pop.current, pop.max, pop.growth_progress))

                # Carry over progress overflow to the next queued item.
                overflow = build_state.progress - proj["cost"]
                if build_state.queue:
                    build_state.current_project = build_state.queue.pop(0)
                    queue_changed = True
                    build_state.progress = overflow
                else:
                    build_state.current_project = None
                    build_state.progress = 0
                    break

            planet_build_updates.append((planet.id, build_state.current_project, build_state.progress))
            if queue_changed:
                queue_updates.append((planet.id, list(build_state.queue)))
        else:
            bc_to_empire += industry  # idle planet's industry becomes BC

        cur_bc, cur_res = empire_gains.get(owner.empire_id, (0, 0))
        empire_gains[owner.empire_id] = (cur_bc + bc_to_empire, cur_res + research)

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
        for planet_id, queue in queue_updates:
            save_planet_build_queue(conn, planet_id, queue)
        for planet_id, current, mx, growth in pop_updates:
            update_planet_population(conn, planet_id, current, mx, growth)
        conn.commit()

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

from ecs.components import Planet, Owner, Empire, Population, BuildState, TechState, Ship, ShipOwner, ShipAt, Orbiting, StarRef, Name
from ecs.turn_log import CAT_BUILDING, CAT_TECH, CAT_EVENT, log as turn_log
from ecs.db import (
    get_connection,
    update_empire_economy,
    update_planet_population,
    update_planet_type,
    update_planet_build,
    update_planet_workers,
    insert_planet_building,
    delete_planet_building,
    save_planet_build_queue,
    update_empire_tech,
    insert_empire_tech,
    insert_ship,
)
from ecs.projects import PROJECTS, building_growth_bonus, project_allowed_for_traits
from ecs.designs import design_project_spec
from ecs.techs import TECHS
from ecs.difficulty import ai_output_multiplier
from ecs.races import trait_count, traits_for_empire
from ecs.planet_features import (
    RICHNESS_INDUSTRY_MULT, GRAVITY_OUTPUT_MULT, feature_bonuses,
)
from ecs.ships import empire_freighter_capacity, SHIPS
from ecs.blockade import is_blockaded
from ecs.diplomacy import empire_trade_bonus_pct, empire_research_bonus_pct
from ecs.leaders import colony_effect
from ecs.techs import (
    empire_industry_per_worker, empire_food_per_farmer, empire_research_per_scientist,
    empire_bc_pct_tech, empire_research_pct_tech,
)


def empire_tech_bonus(component_mgr, empire_id: int) -> dict[str, int]:
    """Per-worker output bonuses from the empire's unlocked Construction
    / Biology / Computers techs. MAX semantics (later tier replaces
    earlier). Keys: food, industry, research — each is added per
    farmer / worker / scientist inside ``planet_output``."""
    for _eid, tech in component_mgr.get_all(TechState):
        if tech.empire_id == empire_id:
            return {
                "food": empire_food_per_farmer(tech.unlocked),
                "industry": empire_industry_per_worker(tech.unlocked),
                "research": empire_research_per_scientist(tech.unlocked),
            }
    return {"food": 0, "industry": 0, "research": 0}


def _apply_colony_leader(leaders, planet_id, food, industry, research, bonus_bc):
    """Scale a planet's outputs by its assigned colony leader (if any).
    Returns the (possibly boosted) (food, industry, research, bonus_bc)."""
    if leaders is None:
        return food, industry, research, bonus_bc
    leader = leaders.colony_leader_for_planet(planet_id)
    if leader is None:
        return food, industry, research, bonus_bc
    fa, ia, ra, ba = colony_effect(leader)
    return (
        int(round(food * (1 + fa))),
        int(round(industry * (1 + ia))),
        int(round(research * (1 + ra))),
        int(round(bonus_bc * (1 + ba))),
    )


# ---- planet capacity (max population) ---------------------------------

# Each pop unit represents 1 million inhabitants (MOO2 convention). UIs
# render the count with an "M" suffix. Numbers below are tuned to MOO2's
# Terran reference so a Medium Terran caps at ~12 million people.
SIZE_CAP = {
    "Tiny":   4,
    "Small":  8,
    "Medium": 12,
    "Large":  16,
    "Huge":   20,
}

# Climate multiplier applied to SIZE_CAP. Friendlier biomes support more
# population; hostile worlds need terraforming / shielding (not modelled
# yet) to scale further. Asteroid belts / gas giants stay uncolonisable.
TYPE_CAP_MULT = {
    "Gaia":      1.25,
    "Terran":    1.0,
    "Ocean":     1.0,
    "Swamp":     1.0,
    "Jungle":    1.0,
    "Steppe":    0.9,
    "Arid":      0.75,
    "Tundra":    0.75,
    "Desert":    0.5,
    "Barren":    0.4,
    "Volcanic":  0.3,
    "Radiated":  0.2,
    "Toxic":     0.2,
    "Inferno":   0.15,
    "Asteroids": 0.0,
    "Gas Giant": 0.0,
}


# ---- per-worker outputs by planet type --------------------------------

# Food per farmer. Swamp / Ocean / Jungle are wet biomes — good for
# food. Desert/Arid/Tundra are marginal. Barren and worse can't farm at
# all without buildings (hydroponic farm bonuses live on the Project
# catalog and are added in _building_bonuses).
FARMER_FOOD = {
    "Gaia":      3,
    "Terran":    2,
    "Ocean":     2,
    "Swamp":     2,
    "Jungle":    2,
    "Steppe":    2,
    "Arid":      1,
    "Tundra":    1,
    "Desert":    1,
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
    "Swamp":     1,
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
    "Swamp":     1,
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

# Housing mode: fraction of a growth-point earned per unit of industry
# redirected into population. ~10 industry → +1 pop over a turn or two.
HOUSING_GROWTH_PER_INDUSTRY = 0.1

# Ship maintenance: each turn a fleet costs this fraction of its total
# build cost in BC. Keeping a big navy idle drains the treasury — the
# incentive to scrap obsolete hulls (see ecs.scrap) rather than hoard.
SHIP_UPKEEP_FRACTION = 0.03


# ---- capacity + default assignment ------------------------------------

def compute_max_population(planet_type: str, size: str) -> int:
    cap = SIZE_CAP.get(size, 0) * TYPE_CAP_MULT.get(planet_type, 0)
    return int(round(cap))


def _is_biome_upgrade(current: str, target: str) -> bool:
    """True if terraforming ``current`` into ``target`` is an improvement
    (strictly higher habitability). Ranked by the population-cap
    multiplier so we never terraform a world to a worse (or equal) biome."""
    return TYPE_CAP_MULT.get(target, 0) > TYPE_CAP_MULT.get(current, 0)


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

def _building_bonuses(build_state: BuildState | None, traits=None):
    """Sum flat bonuses contributed by completed buildings. Buildings
    forbidden by an empire's race trait (e.g. Pleasure Dome for a
    hive_mind race) contribute nothing."""
    food = industry = research = bc = 0
    if build_state is None:
        return food, industry, research, bc
    for project_id in build_state.completed:
        if traits and not project_allowed_for_traits(project_id, traits):
            continue
        effects = PROJECTS.get(project_id, {}).get("effects", {})
        food += effects.get("food", 0)
        industry += effects.get("industry", 0)
        research += effects.get("research", 0)
        bc += effects.get("bc", 0)
    return food, industry, research, bc


def planet_output(planet: Planet, population: Population | None,
                  build_state: BuildState | None = None,
                  traits=None, tech_bonus=None) -> tuple[int, int, int, int]:
    """Return (food, industry, research, bonus_bc) for one planet.

    - food / industry / research are per-pop outputs (farmers, workers,
      scientists respectively) + race trait bonuses (food_bonus,
      industry_bonus, research_bonus) + empire-wide ``tech_bonus``
      (per-worker output from Construction / Biology / Computers techs)
      + building flat bonuses for the same stat.
    - bonus_bc is BC contributed by buildings + bc_bonus race trait
      (per worker). Industry-as-BC happens in production_tick only when
      the planet has no active project.

    Uncolonized planets (no Population) return (0, 0, 0, 0).
    """
    if population is None or population.current <= 0:
        return 0, 0, 0, 0
    traits = traits or []
    tb = tech_bonus or {}
    p_type = planet.planet_type

    farm_per = (FARMER_FOOD.get(p_type, 0)
                + trait_count(traits, "food_bonus")
                + tb.get("food", 0))
    work_industry_per = max(
        0,
        WORKER_INDUSTRY.get(p_type, 0)
        + trait_count(traits, "industry_bonus")
        + trait_count(traits, "hive_mind")  # hive workers pull double
        - trait_count(traits, "weak_industry")
        + tb.get("industry", 0),
    )
    sci_per = (SCIENTIST_RESEARCH.get(p_type, 0)
               + trait_count(traits, "research_bonus")
               + trait_count(traits, "mind_link")  # telepathic collective
               + tb.get("research", 0))

    food = population.farmers * farm_per
    industry = population.workers * work_industry_per
    research = population.scientists * sci_per

    # Richness scales raw industry from the workforce. Buildings that
    # produce flat industry (factories) bypass it — they're machines,
    # not labour, so mineral abundance doesn't matter to them.
    rich_mult = RICHNESS_INDUSTRY_MULT.get(getattr(planet, "richness", "Abundant"), 1.0)
    industry = int(round(industry * rich_mult))

    # Gravity penalises per-pop output across the board. Flat building
    # bonuses are unaffected — equipment doesn't care about gravity.
    grav_mult = GRAVITY_OUTPUT_MULT.get(getattr(planet, "gravity", "Normal"), 1.0)
    if grav_mult != 1.0:
        food = int(round(food * grav_mult))
        industry = int(round(industry * grav_mult))
        research = int(round(research * grav_mult))

    b_food, b_industry, b_research, b_bc = _building_bonuses(build_state, traits)
    # Special features add a flat per-turn bonus regardless of pop —
    # artifact ruins yield research even if no scientists are assigned,
    # and deposits passively generate BC.
    feat_research, feat_bc = feature_bonuses(getattr(planet, "special", []))
    bonus_bc = b_bc + feat_bc + population.workers * trait_count(traits, "bc_bonus")
    return (
        food + b_food,
        industry + b_industry,
        research + b_research + feat_research,
        bonus_bc,
    )


# ---- empire-level summaries (HUD + per-turn) --------------------------

def fleet_upkeep(component_mgr, empire_id: int) -> int:
    """Per-turn BC maintenance for an empire's whole fleet — a fraction
    of the summed build cost of every ship it owns."""
    total_cost = 0
    for ship_entity, owner in component_mgr.get_all(ShipOwner):
        if owner.empire_id != empire_id:
            continue
        ship = component_mgr.get_component(ship_entity, Ship)
        if ship is not None:
            total_cost += SHIPS.get(ship.ship_class, {}).get("cost", 0)
    return int(total_cost * SHIP_UPKEEP_FRACTION)


def empire_per_turn(component_mgr, empire_id: int, leaders=None,
                    diplo=None) -> dict[str, int]:
    """Per-turn projection for HUD display.

    Returns dict with: bc, research, food_balance, industry.
    BC = sum across planets of (industry if idle else 0) + building bonus_bc.
    Food balance = produced - pop (halved for Tolerant races).
    ``leaders`` (optional) folds in assigned colony-leader bonuses so the
    HUD matches what production_tick will actually grant.
    """
    traits = traits_for_empire(component_mgr, empire_id)
    tech_bonus = empire_tech_bonus(component_mgr, empire_id)
    bc_total = research_total = industry_total = 0
    food_produced = pop_total = 0

    for entity_id, owner in component_mgr.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        planet = component_mgr.get_component(entity_id, Planet)
        if planet is None:
            continue
        pop = component_mgr.get_component(entity_id, Population)
        build_state = component_mgr.get_component(entity_id, BuildState)
        food, industry, research, bonus_bc = planet_output(
            planet, pop, build_state, traits, tech_bonus)
        food, industry, research, bonus_bc = _apply_colony_leader(
            leaders, planet.id, food, industry, research, bonus_bc)

        food_produced += food
        if pop is not None:
            pop_total += pop.current
        research_total += research
        industry_total += industry

        # Idle colonies (and Trade Goods mode) turn industry into BC;
        # Housing mode and active builds don't.
        cur = build_state.current_project if build_state else None
        as_bc = (cur is None) or (cur == "trade_goods")
        col_bc = bonus_bc + (industry if as_bc else 0)
        # A blockaded colony's trade is cut (matches production_tick).
        if col_bc and diplo is not None and is_blockaded(component_mgr, entity_id, diplo):
            col_bc = 0
        bc_total += col_bc

    food_needed = pop_total // 2 if "tolerant" in traits else pop_total
    upkeep = fleet_upkeep(component_mgr, empire_id)
    return {
        # Net BC banked per turn = income − fleet maintenance. Matches
        # what production_tick actually applies (which floors at 0).
        "bc": bc_total - upkeep,
        "upkeep": upkeep,
        "research": research_total,
        "industry": industry_total,
        "food_balance": food_produced - food_needed,
        "freighter_capacity": empire_freighter_capacity(component_mgr, empire_id),
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
        traits = traits_for_empire(cm, empire_id)
        tech_bonus = empire_tech_bonus(cm, empire_id)
        # Compute food production / need per planet so we can decide
        # whether freighters can move surplus to shortage colonies.
        per_planet: list[tuple[int, int, int]] = []  # (eid, produced, needed)
        food_produced = pop_total = 0
        per_pop_need = 0.5 if "tolerant" in traits else 1.0
        for eid in entity_ids:
            planet = cm.get_component(eid, Planet)
            pop = cm.get_component(eid, Population)
            build_state = cm.get_component(eid, BuildState)
            if planet is None or pop is None:
                continue
            f, _i, _r, _b = planet_output(planet, pop, build_state, traits, tech_bonus)
            need = int(pop.current * per_pop_need + 0.999)  # ceil
            per_planet.append((eid, f, need))
            food_produced += f
            pop_total += pop.current

        food_needed = pop_total // 2 if "tolerant" in traits else pop_total
        food_balance = food_produced - food_needed

        # Freighter logistics: even if the empire-wide balance is fine,
        # food can only physically move up to ``capacity`` units per
        # turn. The portion of the per-planet deficit that exceeds
        # capacity is "unmoved" — those colonies starve.
        per_planet_deficit = sum(max(0, n - f) for _, f, n in per_planet)
        capacity = empire_freighter_capacity(cm, empire_id)
        unmoved_deficit = max(0, per_planet_deficit - capacity)
        # Real shortage and unmoved deficit both starve. We pick the
        # bigger of the two — they describe different ways a planet can
        # go hungry but never compound (if there's no food at all, the
        # transport question is moot).
        starvation = max(max(0, -food_balance), unmoved_deficit)

        if starvation > 0:
            # Pick the planet with the worst local food deficit (or the
            # most pop if everyone is balanced) to absorb starvation.
            def _deficit(eid):
                p = next(((f, n) for e, f, n in per_planet if e == eid), None)
                if p is None:
                    return 0
                return p[1] - p[0]  # need - prod, positive means short
            victim_eid = max(
                entity_ids,
                key=lambda e: (
                    _deficit(e),
                    getattr(cm.get_component(e, Population), "current", 0),
                ),
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
                bonus = building_growth_bonus(build_state.completed, traits) if build_state else 0.0
                trait_growth = 0.2 * (
                    trait_count(traits, "fast_growth")
                    - trait_count(traits, "slow_growth")
                )
                rate = max(0.05, POP_GROWTH_RATE + bonus + trait_growth)
                increment = rate * pop.current * (pop.max - pop.current) / pop.max
                pop.growth_progress += increment

                grew = 0
                farmer_food = (FARMER_FOOD.get(planet.planet_type, 0)
                               + trait_count(traits, "food_bonus")
                               + tech_bonus.get("food", 0))
                pop_food_need = 0.5 if "tolerant" in traits else 1.0
                while pop.growth_progress >= 1.0 and pop.current < pop.max:
                    pop.current += 1
                    food_surplus -= pop_food_need  # new pop consumes its share
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


def _star_db_id_for_planet(component_mgr, planet_entity):
    orbit = component_mgr.get_component(planet_entity, Orbiting)
    if orbit is None:
        return None
    ref = component_mgr.get_component(orbit.star_entity, StarRef)
    return ref.db_id if ref else None


def production_tick(game, new_turn: int):
    """Apply per-planet industry/research to empires; resolve project progress."""
    cm = game.component_mgr

    # Player empire id (cached once per tick) — used to filter the
    # rolling turn_log so AI building / research churn stays out.
    player_emp = next(
        (e for _eid, e in cm.get_all(Empire) if e.is_player), None
    )
    player_id = player_emp.id if player_emp else None

    # Cache trait lists + tech bonuses per empire so we don't re-walk
    # Empire / TechState components for every planet on big maps.
    traits_by_empire: dict[int, list[str]] = {
        emp.id: traits_for_empire(cm, emp.id) for _eid, emp in cm.get_all(Empire)
    }
    tech_bonus_by_empire: dict[int, dict] = {
        emp.id: empire_tech_bonus(cm, emp.id) for _eid, emp in cm.get_all(Empire)
    }

    empire_gains: dict[int, tuple[int, int]] = {}  # empire_id -> (bc, research)
    planet_build_updates: list[tuple[int, str | None, int]] = []
    queue_updates: list[tuple[int, list[str]]] = []
    completed_inserts: list[tuple[int, str]] = []
    # (planet_id, project_id) pairs scrapped by an upgrade in the same
    # chain — e.g. a Battlestation completion drops the Star Base.
    chain_removals: list[tuple[int, str]] = []
    planet_type_updates: list[tuple[int, str]] = []  # terraforming biome changes
    blockaded_player_colonies: list[int] = []  # for the player blockade warning
    pop_updates: list[tuple[int, int, int, float]] = []  # for max_pop bumps
    # (owner_empire_id, ship_class, current_star_db_id, planet_entity_id, owner_obj)
    ship_spawns: list[tuple[int, str, int, int, Owner]] = []

    for entity_id, owner in cm.get_all(Owner):
        planet = cm.get_component(entity_id, Planet)
        if planet is None:
            continue
        pop = cm.get_component(entity_id, Population)
        build_state = cm.get_component(entity_id, BuildState)
        traits = traits_by_empire.get(owner.empire_id, [])
        tb = tech_bonus_by_empire.get(owner.empire_id, {"food": 0, "industry": 0, "research": 0})
        food, industry, research, bonus_bc = planet_output(planet, pop, build_state, traits, tb)
        food, industry, research, bonus_bc = _apply_colony_leader(
            getattr(game, "leaders", None), planet.id, food, industry, research, bonus_bc)

        bc_to_empire = bonus_bc
        _cur = build_state.current_project if build_state else None
        _mode = PROJECTS.get(_cur, {}).get("type") if _cur else None
        if _mode == "mode":
            # Perpetual mode order: the colony's whole industry output is
            # converted, not spent on construction.
            if _cur == "trade_goods":
                bc_to_empire += industry
            elif _cur == "housing" and pop is not None and pop.max > 0 \
                    and pop.current < pop.max:
                # Industry accelerates growth; applied next pop_growth_tick.
                pop.growth_progress += industry * HOUSING_GROWTH_PER_INDUSTRY
                pop_updates.append((planet.id, pop.current, pop.max,
                                    pop.growth_progress))
        elif build_state and build_state.current_project:
            build_state.progress += industry
            queue_changed = False
            # Resolve as many completions as the progress allows (rare, but
            # cheap buildings + big industry can finish multiple per turn).
            while True:
                cur = build_state.current_project
                if not cur:
                    break
                proj = PROJECTS.get(cur)
                # design:<id> orders aren't in PROJECTS — resolve them
                # against the empire's saved blueprints.
                if proj is None:
                    proj = design_project_spec(cur, getattr(game, "ship_designs", None))
                if proj is None:
                    # Unresolvable order — the design was deleted (or the
                    # save references a dead one). Drop it and advance the
                    # queue instead of stalling the planet forever.
                    build_state.current_project = (
                        build_state.queue.pop(0) if build_state.queue else None)
                    build_state.progress = 0
                    queue_changed = True
                    continue
                if build_state.progress < proj["cost"]:
                    break
                completed_id = build_state.current_project
                proj_type = proj.get("type", "building")

                if proj_type == "ship":
                    # Spawn a ship at this planet's star; do NOT add to
                    # completed so the project can be queued again. A
                    # design order carries its design_id so the spawn
                    # freezes that exact loadout instead of the auto one.
                    star_db_id = _star_db_id_for_planet(cm, entity_id)
                    if star_db_id is not None:
                        ship_spawns.append((
                            owner.empire_id, proj["ship_class"],
                            star_db_id, entity_id, owner,
                            proj.get("design_id"),
                        ))
                else:
                    build_state.completed.append(completed_id)
                    completed_inserts.append((planet.id, completed_id))

                    effects = proj.get("effects", {})
                    if "max_pop" in effects and pop is not None:
                        pop.max += effects["max_pop"]
                        pop_updates.append((planet.id, pop.current, pop.max, pop.growth_progress))

                    # Terraforming: upgrade the biome (never downgrade).
                    # Output is derived from planet_type live, so the cap
                    # delta is folded into max_pop and food/industry
                    # follow automatically next tick.
                    target = effects.get("terraform_to")
                    if target and pop is not None and _is_biome_upgrade(
                            planet.planet_type, target):
                        delta = (compute_max_population(target, planet.size)
                                 - compute_max_population(planet.planet_type,
                                                          planet.size))
                        planet.planet_type = target
                        if delta:
                            pop.max += delta
                        pop_updates.append((planet.id, pop.current, pop.max,
                                            pop.growth_progress))
                        planet_type_updates.append((planet.id, target))

                    # Upgrade chain: a new project in the same chain
                    # scraps every previous tier on this planet. Used
                    # for the orbital-defense chain (Star Base →
                    # Battlestation → Star Fortress).
                    chain = proj.get("chain")
                    if chain:
                        for prev_id in list(build_state.completed):
                            if prev_id == completed_id:
                                continue
                            if PROJECTS.get(prev_id, {}).get("chain") == chain:
                                build_state.completed.remove(prev_id)
                                chain_removals.append((planet.id, prev_id))

                    # Player-perspective turn log entry.
                    if player_id is not None and owner.empire_id == player_id:
                        orbit = cm.get_component(entity_id, Orbiting)
                        sn = cm.get_component(orbit.star_entity, Name) if orbit else None
                        star_name = sn.value if sn else "?"
                        turn_log(game, CAT_BUILDING,
                                 f"Built {proj.get('name', completed_id)} on {star_name}")

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

        # A hostile fleet in orbit blockades the colony: its commerce is
        # cut (no BC leaves the system) until the fleet is driven off.
        # Local industry still builds; research still flows.
        if bc_to_empire and is_blockaded(cm, entity_id, getattr(game, "diplomacy", None)):
            bc_to_empire = 0
            if player_id is not None and owner.empire_id == player_id:
                blockaded_player_colonies.append(planet.id)

        cur_bc, cur_res = empire_gains.get(owner.empire_id, (0, 0))
        empire_gains[owner.empire_id] = (cur_bc + bc_to_empire, cur_res + research)

    if blockaded_player_colonies:
        n = len(blockaded_player_colonies)
        turn_log(game, CAT_EVENT,
                 f"{n} colon{'y' if n == 1 else 'ies'} blockaded — trade cut. "
                 "Drive off the enemy fleet.")

    empire_updates: list[tuple[int, int, int]] = []
    tech_updates: list[tuple[int, str | None, int]] = []
    tech_unlocks: list[tuple[int, str]] = []
    locked_tech_inserts: list[tuple[int, str]] = []
    tech_by_empire: dict[int, TechState] = {
        t.empire_id: t for _eid, t in cm.get_all(TechState)
    }

    ai_mult = ai_output_multiplier(getattr(game.galaxy, "difficulty", "normal"))

    # Diplomacy: trade / research treaties give each signatory a percent
    # bonus to BC / research, stacking per active partner.
    diplo = getattr(game, "diplomacy", None)
    empire_ids = [e.id for _eid, e in cm.get_all(Empire)]

    for _eid, empire in cm.get_all(Empire):
        gain_bc, gain_res = empire_gains.get(empire.id, (0, 0))
        # AI empires get a flat cheating bonus per difficulty. The player's
        # gains are unchanged.
        if not empire.is_player and ai_mult != 1.0:
            gain_bc = int(round(gain_bc * ai_mult))
            gain_res = int(round(gain_res * ai_mult))
        # Treaty bonuses apply on top, for everyone.
        if diplo is not None:
            trade_pct = empire_trade_bonus_pct(diplo, empire.id, empire_ids)
            research_pct = empire_research_bonus_pct(diplo, empire.id, empire_ids)
            if trade_pct:
                gain_bc = int(round(gain_bc * (1 + trade_pct / 100)))
            if research_pct:
                gain_res = int(round(gain_res * (1 + research_pct / 100)))
        # Empire-wide tech percentages: Galactic Currency Exchange (+BC%),
        # Federation (+research%). Applied on top of treaty bonuses.
        _ts = tech_by_empire.get(empire.id)
        if _ts is not None:
            bc_pct = empire_bc_pct_tech(_ts.unlocked)
            res_pct = empire_research_pct_tech(_ts.unlocked)
            if bc_pct:
                gain_bc = int(round(gain_bc * (1 + bc_pct / 100)))
            if res_pct:
                gain_res = int(round(gain_res * (1 + res_pct / 100)))
        # Ship maintenance is deducted from income (a flat cost, not
        # scaled by trade bonuses). The treasury floors at 0 — an empire
        # that can't pay simply stops banking BC rather than going into
        # debt; every BC spender already checks affordability.
        upkeep = fleet_upkeep(cm, empire.id)
        _bc_before = empire.bc
        empire.bc = max(0, empire.bc + gain_bc - upkeep)
        # Warn the player only on the turn upkeep first empties the
        # treasury (not every turn while broke) — a nudge to scrap.
        if (empire.is_player and _bc_before > 0 and empire.bc == 0
                and upkeep > gain_bc):
            turn_log(game, CAT_EVENT,
                     "Treasury exhausted — fleet upkeep exceeds income. "
                     "Scrap ships to recover.")
        if gain_res:
            empire.research_points += gain_res
            tech = tech_by_empire.get(empire.id)
            if tech is not None and tech.current_target:
                tech.progress += gain_res
                proj = TECHS.get(tech.current_target)
                if proj and tech.progress >= proj["cost"]:
                    completed_tech = tech.current_target
                    tech.unlocked.append(completed_tech)
                    tech_unlocks.append((empire.id, completed_tech))
                    if empire.is_player:
                        tech_name = TECHS.get(completed_tech, {}).get("name", completed_tech)
                        turn_log(game, CAT_TECH, f"Researched {tech_name}")
                    # MOO2 choice rule: every other alternative at the
                    # same tier slot is locked-out for this empire (still
                    # acquirable by spy theft / tech trade).
                    from ecs.techs import alternatives_in_group
                    for alt in alternatives_in_group(completed_tech):
                        if (alt != completed_tech
                                and alt not in tech.unlocked
                                and alt not in tech.locked_out):
                            tech.locked_out.append(alt)
                            locked_tech_inserts.append((empire.id, alt))
                    tech.current_target = None
                    tech.progress = 0
                tech_updates.append((empire.id, tech.current_target, tech.progress))
        empire_updates.append((empire.id, empire.bc, empire.research_points))

    with get_connection() as conn:
        for empire_id, bc, research in empire_updates:
            update_empire_economy(conn, empire_id, bc, research)
        for empire_id, target, progress in tech_updates:
            update_empire_tech(conn, empire_id, target, progress)
        for empire_id, tech_id in tech_unlocks:
            insert_empire_tech(conn, empire_id, tech_id)
        for empire_id, tech_id in locked_tech_inserts:
            from ecs.db import insert_empire_locked_tech
            insert_empire_locked_tech(conn, empire_id, tech_id)
        for planet_id, current_project, progress in planet_build_updates:
            update_planet_build(conn, planet_id, current_project, progress)
        # Scrap previous-tier upgrades BEFORE inserting their successors
        # so each planet's row set stays consistent if it's read mid-flush.
        for planet_id, project_id in chain_removals:
            delete_planet_building(conn, planet_id, project_id)
        for planet_id, project_id in completed_inserts:
            insert_planet_building(conn, planet_id, project_id)
        for planet_id, queue in queue_updates:
            save_planet_build_queue(conn, planet_id, queue)
        for planet_id, current, mx, growth in pop_updates:
            update_planet_population(conn, planet_id, current, mx, growth)
        for planet_id, planet_type in planet_type_updates:
            update_planet_type(conn, planet_id, planet_type)

        # Spawn new ships: insert DB row, then attach ECS entity. The
        # planet's owning empire is captured at spawn time so ownership
        # can't shift mid-tick. The empire's best-researched loadout is
        # *frozen onto the hull* here — already-built ships keep their
        # old gear when newer tech later lands.
        from ecs.ship_design import compute_loadout, loadout_to_ship_fields
        designs_mgr = getattr(game, "ship_designs", None)
        for owner_empire_id, ship_class, star_db_id, planet_entity, _owner, design_id in ship_spawns:
            design = designs_mgr.get(design_id) if (design_id and designs_mgr) else None
            if design is not None:
                # Manual design: freeze the blueprint's exact loadout.
                fields = design.ship_fields()
            else:
                # Quick Build: snapshot the empire's current best gear.
                ts = tech_by_empire.get(owner_empire_id)
                unlocked_now = set(ts.unlocked) if ts is not None else set()
                fields = loadout_to_ship_fields(compute_loadout(ship_class, unlocked_now))
                fields.setdefault("weapon_mount", "normal")
            specials_csv = ",".join(fields.get("specials", []))
            mount = fields.get("weapon_mount", "normal")
            ship_id = insert_ship(
                conn, owner_empire_id, ship_class, star_db_id,
                armor_tech=fields["armor_tech"],
                shield_tech=fields["shield_tech"],
                weapon_tech=fields["weapon_tech"],
                weapon_count=fields["weapon_count"],
                specials=specials_csv,
                weapon_mount=mount,
            )
            ship_entity = game.entity_mgr.create_entity()
            cm.add_component(ship_entity, Ship(
                id=ship_id, ship_class=ship_class,
                armor_tech=fields["armor_tech"],
                shield_tech=fields["shield_tech"],
                weapon_tech=fields["weapon_tech"],
                weapon_count=fields["weapon_count"],
                specials=list(fields.get("specials", [])),
                weapon_mount=mount,
            ))
            cm.add_component(ship_entity, ShipOwner(empire_id=owner_empire_id))
            orbit = cm.get_component(planet_entity, Orbiting)
            if orbit is not None:
                cm.add_component(ship_entity, ShipAt(star_entity=orbit.star_entity))
        conn.commit()

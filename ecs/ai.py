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

from ecs.components import (
    Empire, Owner, Planet, Population, BuildState, TechState,
    Ship, ShipOwner, ShipAt, ShipInTransit, StarRef, Orbiting, Position,
)
from ecs.economy import FARMER_FOOD
from ecs.projects import PROJECTS, project_is_available
from ecs.techs import TECHS, is_available
from ecs.fleet import start_fleet_movement
from ecs.colonization import (
    COLONY_SHIP_CLASS, colonize_planet, can_colonize,
)
from ecs.db import (
    get_connection,
    update_planet_workers,
    update_planet_build,
    update_empire_tech,
)
from ecs.personalities import get as get_personality


# How many Colony Ships the AI lets pile up at once before pausing
# colony-ship construction. Keeps it from spending all its BC on
# transports it can't use.
AI_MAX_PARKED_COLONY_SHIPS = 2


# ---- Planet scoring for colonisation ----------------------------------
#
# Higher = more attractive. Two AIs at the same star with the same
# colony ship and the same race might disagree on which planet to take:
# an Economic AI grabs Ocean/Terran (food → BC), Scientific grabs Gaia
# (food + research bonus + artifacts), Militaristic grabs Ultra Rich
# Barren (industry).

_TYPE_BASE_SCORE = {
    "Gaia":   100,
    "Terran": 75,
    "Ocean":  70,
    "Swamp":  65,
    "Jungle": 65,
    "Steppe": 55,
    "Arid":   40,
    "Tundra": 40,
    "Desert": 30,
    "Barren": 15,
}
_FOOD_BIOMES = {"Gaia", "Terran", "Ocean", "Swamp", "Jungle", "Steppe"}

_RICHNESS_SCORE = {
    "Ultra Poor": -25, "Poor": -10, "Abundant": 0,
    "Rich": 25, "Ultra Rich": 50,
}
_GRAVITY_SCORE = {"Low": -15, "Normal": 0, "Heavy": -30}
_SIZE_SCORE = {"Tiny": 0, "Small": 15, "Medium": 30, "Large": 45, "Huge": 60}


def _score_candidate_planet(planet, traits: list[str], focus: str) -> float:
    """Personality-and-trait-aware utility score for a candidate planet.

    ``focus`` is one of: ``balanced`` / ``economy`` / ``science`` /
    ``industry`` — pulled from the empire's personality dict.
    """
    score = float(_TYPE_BASE_SCORE.get(planet.planet_type, 0))

    food_value = planet.planet_type in _FOOD_BIOMES
    rich_value = _RICHNESS_SCORE.get(planet.richness, 0)

    if focus == "economy":
        # More pop = more BC; food biomes feed faster, gold/gems sweeten.
        if food_value:
            score += 25
    elif focus == "science":
        # Gaia is a triple-prize (food + research bonus + extra growth);
        # other food biomes still attractive because more pop = more
        # scientists.
        if planet.planet_type == "Gaia":
            score += 50
        elif food_value:
            score += 15
    elif focus == "industry":
        # Workforce planets care more about minerals than biome.
        score += rich_value  # double-weight richness on top of the base bump
        if planet.planet_type == "Barren":
            score += 25  # militaristic loves Barren mining worlds

    score += rich_value
    score += _GRAVITY_SCORE.get(planet.gravity, 0)
    score += _SIZE_SCORE.get(planet.size, 0)

    # Specials — everyone likes them; focus boosts the matching kind.
    for sp in getattr(planet, "special", []) or []:
        score += 30
        if sp == "artifacts" and focus == "science":
            score += 40
        if sp in ("gold_veins", "gem_deposits") and focus == "economy":
            score += 25

    # Race traits: Subterranean doubles down on Huge/Large planets;
    # Tolerant cares less about food biomes (counted as neutral instead
    # of penalised — but our base score doesn't penalise non-food
    # biomes, so just a small +5 reward for picking what others
    # avoid).
    if "subterranean" in traits:
        score += _SIZE_SCORE.get(planet.size, 0) * 0.5
    if "tolerant" in traits and not food_value:
        # Tolerant races thrive on otherwise-marginal Barren/Desert
        # worlds — bump them a bit so the AI grabs frontier rocks.
        score += 20

    return score


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

    # Galaxy-wide colonisation candidates — computed once per tick so
    # every AI can reuse the list (and so we know whether building more
    # colony ships is worth it).
    candidate_stars = _unowned_habitable_stars(cm)

    for _eid, empire in cm.get_all(Empire):
        if empire.is_player:
            continue
        personality = get_personality(empire.personality)
        tech_state = tech_by_empire.get(empire.id)
        unlocked = set(tech_state.unlocked) if tech_state else set()

        focus = personality.get("colonization_focus", "balanced")
        # Settle planets first — a Colony Ship already at a habitable
        # target should be spent this turn (before production_tick
        # touches the new colony).
        _ai_settle_arrived_colony_ships(game, empire, focus)

        # Pause queuing new colony ships when the AI has plenty parked
        # or there's nowhere left to settle.
        parked_colony_count = _count_parked_colony_ships(cm, empire.id)
        suppress_colony = (
            not candidate_stars
            or parked_colony_count >= AI_MAX_PARKED_COLONY_SHIPS
        )

        for entity_id in empire_planets.get(empire.id, []):
            _ai_rebalance_workers(cm, entity_id, personality["worker_pct"], pending_writes)
            _ai_queue_building(
                cm, entity_id, personality["build_priority"], unlocked,
                pending_writes, suppress=("ship_colony_ship",) if suppress_colony else (),
            )

        if tech_state is not None:
            _ai_pick_research(tech_state, personality["research_priority"], pending_writes)

        # Dispatch any colony ships still parked after settling — fly
        # them to the highest-value reachable star (score minus
        # distance penalty).
        _ai_dispatch_colony_ships(cm, empire, candidate_stars, focus)

        if personality.get("aggressive"):
            _ai_dispatch_ships(cm, empire)

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


def _ai_queue_building(cm, entity_id, build_priority, unlocked: set,
                        pending_writes, suppress: tuple = ()):
    build_state = cm.get_component(entity_id, BuildState)
    planet = cm.get_component(entity_id, Planet)
    if build_state is None or planet is None:
        return
    if build_state.current_project or build_state.queue:
        return

    completed = set(build_state.completed)
    suppressed = set(suppress)
    for proj_id in build_priority:
        if proj_id in suppressed:
            continue
        if proj_id in completed:
            continue
        if not project_is_available(proj_id, unlocked):
            continue
        build_state.current_project = proj_id
        pending_writes.append(("build", (planet.id, proj_id, build_state.progress)))
        return


def _unowned_habitable_stars(cm) -> list[int]:
    """Stars that host at least one unowned habitable planet. Used by
    every AI's colonisation budget guard + dispatch heuristic."""
    seen: set[int] = set()
    for planet_entity, orbit in cm.get_all(Orbiting):
        planet = cm.get_component(planet_entity, Planet)
        if planet is None or not planet.colonizable:
            continue
        if cm.get_component(planet_entity, Owner) is not None:
            continue
        seen.add(orbit.star_entity)
    return list(seen)


def _count_parked_colony_ships(cm, empire_id: int) -> int:
    """Colony ships of ``empire_id`` currently parked (ShipAt). Ships in
    transit don't count — they're already committed."""
    n = 0
    for ship_entity, _at in cm.get_all(ShipAt):
        ship = cm.get_component(ship_entity, Ship)
        owner = cm.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id != empire_id:
            continue
        if ship.ship_class != COLONY_SHIP_CLASS:
            continue
        n += 1
    return n


def _candidate_planets_at_star(cm, star_entity: int) -> list[int]:
    """Unowned habitable planet entities orbiting ``star_entity``."""
    out: list[int] = []
    for planet_entity, orbit in cm.get_all(Orbiting):
        if orbit.star_entity != star_entity:
            continue
        planet = cm.get_component(planet_entity, Planet)
        if planet is None or not planet.colonizable:
            continue
        if cm.get_component(planet_entity, Owner) is not None:
            continue
        out.append(planet_entity)
    return out


def _best_planet_at_star(cm, star_entity: int, traits: list[str], focus: str):
    """Return (planet_entity, score) for the best unowned habitable
    planet at this star, or (None, -inf) if there's nothing to settle."""
    best, best_score = None, float("-inf")
    for planet_entity in _candidate_planets_at_star(cm, star_entity):
        planet = cm.get_component(planet_entity, Planet)
        score = _score_candidate_planet(planet, traits, focus)
        if score > best_score:
            best, best_score = planet_entity, score
    return best, best_score


def _ai_settle_arrived_colony_ships(game, empire, focus: str):
    """If any of the empire's Colony Ships is parked at a star with an
    unowned habitable planet, settle the highest-scoring candidate
    there. Score uses ``focus`` so Economic / Scientific / Militaristic
    pick the planet they actually want."""
    cm = game.component_mgr
    from ecs.races import traits_for_empire
    traits = traits_for_empire(cm, empire.id)

    parked_colony_stars: dict[int, list[int]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        ship = cm.get_component(ship_entity, Ship)
        owner = cm.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id != empire.id or ship.ship_class != COLONY_SHIP_CLASS:
            continue
        parked_colony_stars.setdefault(at.star_entity, []).append(ship_entity)

    for star_entity, _ships in parked_colony_stars.items():
        # Rank candidate planets at this star by score, highest first.
        scored: list[tuple[float, int]] = []
        for planet_entity in _candidate_planets_at_star(cm, star_entity):
            planet = cm.get_component(planet_entity, Planet)
            scored.append((
                _score_candidate_planet(planet, traits, focus),
                planet_entity,
            ))
        if not scored:
            continue
        scored.sort(key=lambda t: t[0], reverse=True)
        # Spend one ship per planet; settle as many as possible at this
        # star this turn until either we run out of ships or candidates.
        for _score, planet_entity in scored:
            if not can_colonize(cm, planet_entity, empire.id):
                break
            colonize_planet(game, planet_entity, empire.id)


# Distance penalty per parsec squared (px²) — keeps the formula in raw
# pixels so we don't need to import PIXELS_PER_PARSEC here. Tuned so a
# star ~300 px away (≈12 parsecs) is worth ~10 score points less than
# the same planet next door — close calls go to nearer stars, but a
# Gaia 600 px away will still beat a Desert next door.
_DISPATCH_DISTANCE_WEIGHT = 0.0001


def _ai_dispatch_colony_ships(cm, empire, candidate_stars: list[int], focus: str):
    """Send parked Colony Ships not currently at a candidate star to
    the star whose best planet has the highest score, minus a small
    distance penalty. No-op if there are no candidates."""
    if not candidate_stars:
        return
    candidate_set = set(candidate_stars)
    from ecs.races import traits_for_empire
    traits = traits_for_empire(cm, empire.id)

    # Pre-compute (star, best_planet_score) once per candidate so we
    # don't re-score every planet per ship.
    star_score: dict[int, float] = {}
    for star_entity in candidate_stars:
        _planet, score = _best_planet_at_star(cm, star_entity, traits, focus)
        star_score[star_entity] = score

    ships_by_star: dict[int, list[int]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        ship = cm.get_component(ship_entity, Ship)
        owner = cm.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id != empire.id or ship.ship_class != COLONY_SHIP_CLASS:
            continue
        if at.star_entity in candidate_set:
            continue  # already at a settle target — settle pass handles it
        ships_by_star.setdefault(at.star_entity, []).append(ship_entity)

    if not ships_by_star:
        return

    for src_star, ships in ships_by_star.items():
        src_pos = cm.get_component(src_star, Position)
        if src_pos is None:
            continue
        best, best_value = None, float("-inf")
        for cand, cand_score in star_score.items():
            if cand == src_star:
                continue
            cand_pos = cm.get_component(cand, Position)
            if cand_pos is None:
                continue
            d2 = (cand_pos.x - src_pos.x) ** 2 + (cand_pos.y - src_pos.y) ** 2
            value = cand_score - d2 * _DISPATCH_DISTANCE_WEIGHT
            if value > best_value:
                best_value, best = value, cand
        if best is not None:
            start_fleet_movement(cm, ships, src_star, best)


def _ai_dispatch_ships(cm, empire):
    """Aggressive AI: send any parked ships at the player's homeworld.

    Picks every parked ship not already at the target and dispatches.
    Each ship handles its own transit time so faster hulls arrive first.
    """
    # Locate the player empire + their home star entity.
    player = None
    for _eid, e in cm.get_all(Empire):
        if e.is_player:
            player = e
            break
    if player is None:
        return
    target_star = None
    for star_entity, ref in cm.get_all(StarRef):
        if ref.db_id == player.home_star_id:
            target_star = star_entity
            break
    if target_star is None:
        return

    # Group this AI's parked ships by their current star.
    ships_by_star: dict[int, list[int]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        owner = cm.get_component(ship_entity, ShipOwner)
        if owner is None or owner.empire_id != empire.id:
            continue
        if at.star_entity == target_star:
            continue  # already at target — nothing to do
        ships_by_star.setdefault(at.star_entity, []).append(ship_entity)

    for src_star, ships in ships_by_star.items():
        if ships:
            start_fleet_movement(cm, ships, src_star, target_star)


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

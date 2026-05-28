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
from ecs.economy import FARMER_FOOD, planet_output, empire_tech_bonus
from ecs.projects import PROJECTS, project_is_available
from ecs.techs import TECHS, is_available
from ecs.fleet import start_fleet_movement
from ecs.fuel import reachable_stars
from ecs.ships import empire_freighter_capacity
from ecs.colonization import (
    COLONY_SHIP_CLASS, colonize_planet, can_colonize,
)
from ecs.invasion import (
    TROOP_TRANSPORT_CLASS, can_invade, invade_planet,
    MARINES_PER_TRANSPORT, MILITIA_PER_MILLION_POP, _planet_defense_rating,
)
from ecs.races import traits_for_empire
from ecs.diplomacy import (
    NON_AGGRESSION, TRADE, RESEARCH, ALLIANCE, DEFENSIVE_PACT,
    would_accept_treaty, empire_strength, TREATY_ACCEPT_THRESHOLD,
)
from ecs.db import (
    get_connection,
    update_planet_workers,
    update_planet_build,
    update_empire_tech,
)
from ecs.personalities import get as get_personality
from ecs.espionage import SPY_COST
from ecs.leaders import MAX_LEADERS_PER_EMPIRE


# Fleet caps. Ship projects never enter BuildState.completed, so without
# a cap a ship sitting in the build priority would be rebuilt forever and
# block every lower-priority entry. These caps count ALL of an empire's
# ships of a class (parked + in transit) so dispatching a fleet doesn't
# reopen the build slot every turn.
AI_MAX_COLONY_SHIPS = 2
AI_MAX_TROOP_TRANSPORTS = 4
AI_MAX_WARSHIPS_PER_CLASS = 3

# Combat ships the AI sends to attack the player (excludes Troop
# Transports, which have their own invasion logic, and civilian hulls).
WARSHIP_CLASSES = {"frigate", "carrier", "cruiser", "battleship", "dreadnought"}


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
        traits = traits_for_empire(cm, empire.id)
        planet_ids = empire_planets.get(empire.id, [])
        # Settle planets first — a Colony Ship already at a habitable
        # target should be spent this turn (before production_tick
        # touches the new colony).
        _ai_settle_arrived_colony_ships(game, empire, focus)

        # Aggressive AIs invade enemy worlds with their Troop
        # Transports before doing anything else — settling first means a
        # captured world joins the economy this turn.
        if personality.get("aggressive"):
            _ai_invade_with_transports(game, empire)

        # If distant colonies are starving for lack of transport, build
        # a Freighter on an idle planet before the regular build pass
        # grabs every idle slot.
        _ai_maybe_queue_freighter(cm, empire, planet_ids, traits, pending_writes)

        # Decide which ship projects are wanted right now. A ship that
        # isn't wanted is suppressed so the build loop skips past it to
        # the next building instead of rebuilding the same hull forever.
        suppress = _ai_suppressed_ships(cm, empire, personality, candidate_stars)

        for entity_id in planet_ids:
            _ai_rebalance_workers(cm, entity_id, personality["worker_pct"], pending_writes)
            _ai_queue_building(
                cm, entity_id, personality["build_priority"], unlocked,
                pending_writes, suppress=suppress,
            )

        if tech_state is not None:
            _ai_pick_research(tech_state, personality["research_priority"], pending_writes)

        # Dispatch any colony ships still parked after settling — fly
        # them to the highest-value reachable star (score minus
        # distance penalty), limited to fuel range.
        reachable = reachable_stars(game, empire.id)
        _ai_dispatch_colony_ships(cm, empire, candidate_stars, focus, reachable)

        # Diplomacy: gang up on runaways, sign treaties with friends,
        # declare war on hated rivals.
        _ai_diplomacy(game, empire, personality, new_turn)

        # Espionage: train spies and point them at disliked rivals.
        _ai_espionage(game, empire, personality)

        # Leaders: hire from the pool and assign idle heroes.
        _ai_leaders(game, empire, personality)

        # Fuel range: stars this empire's fleets can actually reach
        # (within range of own/allied supply). Dispatch passes filter
        # their targets to this set so ships aren't sent into the void.
        reachable = reachable_stars(game, empire.id)

        if personality.get("aggressive"):
            # Send idle Troop Transports toward enemy planets, then
            # warships at the player's homeworld.
            _ai_dispatch_troop_transports(cm, empire, reachable)
            _ai_dispatch_ships(cm, empire, reachable)

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


def _count_ships(cm, empire_id: int, ship_class: str) -> int:
    """Total ships of ``empire_id`` + ``ship_class`` the empire owns,
    counting both parked and in-transit hulls. Used for fleet caps so
    dispatching a fleet (moving it from ShipAt to ShipInTransit) doesn't
    reopen the build slot the next turn."""
    n = 0
    for ship_entity, owner in cm.get_all(ShipOwner):
        if owner.empire_id != empire_id:
            continue
        ship = cm.get_component(ship_entity, Ship)
        if ship is not None and ship.ship_class == ship_class:
            n += 1
    return n


def _ai_suppressed_ships(cm, empire, personality, candidate_stars) -> tuple:
    """Ship project ids the AI should NOT build this turn. The build
    loop skips suppressed entries, so an unwanted ship in the priority
    list no longer blocks lower-priority buildings."""
    suppress: set[str] = set()
    aggressive = bool(personality.get("aggressive"))

    # Freighters are queued by dedicated logic (survival need), never
    # from the linear build priority.
    suppress.add("ship_freighter")

    # Colony ships: stop when there's nowhere to settle or we have
    # enough in the pipeline.
    if not candidate_stars or _count_ships(cm, empire.id, COLONY_SHIP_CLASS) >= AI_MAX_COLONY_SHIPS:
        suppress.add("ship_colony_ship")

    # Warships: cap per class for every AI so they don't get stuck
    # rebuilding the cheapest hull. Non-aggressive AIs keep only a token
    # defensive fleet (the cap still applies).
    for cls in WARSHIP_CLASSES:
        if _count_ships(cm, empire.id, cls) >= AI_MAX_WARSHIPS_PER_CLASS:
            suppress.add(f"ship_{cls}")

    # Troop transports: aggressive only, and only when there's an enemy
    # world to invade.
    if (not aggressive
            or not _enemy_owned_stars(cm, empire.id)
            or _count_ships(cm, empire.id, TROOP_TRANSPORT_CLASS) >= AI_MAX_TROOP_TRANSPORTS):
        suppress.add("ship_troop_transport")

    return tuple(suppress)


# ---- Freighter logistics ----------------------------------------------

def _ai_food_shortfall(cm, empire_id: int, traits: list[str], planet_ids: list[int]) -> int:
    """Per-planet food deficit that the empire's freighter capacity
    can't cover this turn. >0 means some colony is going hungry for
    lack of transport, not lack of food."""
    per_pop_need = 0.5 if "tolerant" in traits else 1.0
    per_planet_deficit = 0
    tech_bonus = empire_tech_bonus(cm, empire_id)
    for eid in planet_ids:
        planet = cm.get_component(eid, Planet)
        pop = cm.get_component(eid, Population)
        build_state = cm.get_component(eid, BuildState)
        if planet is None or pop is None:
            continue
        f, _i, _r, _b = planet_output(planet, pop, build_state, traits, tech_bonus)
        need = int(pop.current * per_pop_need + 0.999)  # ceil
        per_planet_deficit += max(0, need - f)
    capacity = empire_freighter_capacity(cm, empire_id)
    return max(0, per_planet_deficit - capacity)


def _ai_maybe_queue_freighter(cm, empire, planet_ids, traits, pending_writes):
    """Queue a Freighter on an idle planet when the empire's colonies
    are starving for want of transport capacity. One at a time — the
    next tick re-evaluates once it's built."""
    # Already building / queuing a freighter somewhere? Don't pile up.
    for eid in planet_ids:
        bs = cm.get_component(eid, BuildState)
        if bs is None:
            continue
        if bs.current_project == "ship_freighter" or "ship_freighter" in bs.queue:
            return
    # ``_ai_food_shortfall`` already nets out the capacity from
    # freighters the empire owns, so we only build another when there's
    # still an uncovered deficit.
    if _ai_food_shortfall(cm, empire.id, traits, planet_ids) <= 0:
        return
    # Build on the first idle planet.
    for eid in planet_ids:
        bs = cm.get_component(eid, BuildState)
        planet = cm.get_component(eid, Planet)
        if bs is None or planet is None:
            continue
        if bs.current_project or bs.queue:
            continue
        bs.current_project = "ship_freighter"
        pending_writes.append(("build", (planet.id, "ship_freighter", bs.progress)))
        return


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


def _ai_dispatch_colony_ships(cm, empire, candidate_stars: list[int], focus: str,
                              reachable: set[int] | None = None):
    """Send parked Colony Ships not currently at a candidate star to
    the star whose best planet has the highest score, minus a small
    distance penalty. Only targets within fuel range. No-op if there
    are no reachable candidates."""
    if reachable is not None:
        candidate_stars = [s for s in candidate_stars if s in reachable]
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


def _ai_dispatch_ships(cm, empire, reachable: set[int] | None = None):
    """Aggressive AI: send warships at the player's homeworld — but only
    if it's within fuel range. Out-of-reach targets are left alone so
    the AI doesn't strand fleets in the void."""
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
    if reachable is not None and target_star not in reachable:
        return  # player's homeworld out of fuel range — hold position

    # Group this AI's parked WARSHIPS by their current star. Civilian
    # hulls (colony, freighter) and troop transports are handled by
    # their own dispatch passes — only combat ships head for the
    # player's homeworld.
    ships_by_star: dict[int, list[int]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        owner = cm.get_component(ship_entity, ShipOwner)
        ship = cm.get_component(ship_entity, Ship)
        if owner is None or ship is None or owner.empire_id != empire.id:
            continue
        if ship.ship_class not in WARSHIP_CLASSES:
            continue
        if at.star_entity == target_star:
            continue  # already at target — nothing to do
        ships_by_star.setdefault(at.star_entity, []).append(ship_entity)

    for src_star, ships in ships_by_star.items():
        if ships:
            start_fleet_movement(cm, ships, src_star, target_star)


# ---- Troop transport invasion -----------------------------------------

def _enemy_owned_stars(cm, empire_id: int) -> dict[int, list[int]]:
    """Map star_entity -> list of enemy-owned planet entities at that
    star (owned by an empire other than ``empire_id``)."""
    out: dict[int, list[int]] = {}
    for planet_entity, orbit in cm.get_all(Orbiting):
        owner = cm.get_component(planet_entity, Owner)
        if owner is None or owner.empire_id == empire_id:
            continue
        out.setdefault(orbit.star_entity, []).append(planet_entity)
    return out


def _weakest_enemy_planet_at_star(cm, planet_entities: list[int]) -> int | None:
    """Pick the enemy planet at a star with the lowest defense
    (militia + defense buildings) — best odds for the assault."""
    best, best_def = None, None
    for planet_entity in planet_entities:
        pop = cm.get_component(planet_entity, Population)
        build_state = cm.get_component(planet_entity, BuildState)
        militia = (pop.current * MILITIA_PER_MILLION_POP) if pop else 0
        defense = militia + _planet_defense_rating(build_state)
        if best_def is None or defense < best_def:
            best, best_def = planet_entity, defense
    return best


def _ai_invade_with_transports(game, empire):
    """Launch one ground assault per star where the empire has Troop
    Transports sitting on an enemy planet. Picks the weakest enemy
    planet at each star for the best odds.

    Skips planets owned by an empire the AI still holds a peace treaty
    with — invading would break the pact and trigger the betrayal
    penalty. The AI waits for the (already-cancelled) treaty to lapse
    instead; its transports sit in orbit until then."""
    cm = game.component_mgr
    diplo = getattr(game, "diplomacy", None)
    enemy_stars = _enemy_owned_stars(cm, empire.id)
    if not enemy_stars:
        return

    # Stars where this empire has parked troop transports.
    tt_stars: set[int] = set()
    for ship_entity, at in cm.get_all(ShipAt):
        ship = cm.get_component(ship_entity, Ship)
        owner = cm.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id == empire.id and ship.ship_class == TROOP_TRANSPORT_CLASS:
            tt_stars.add(at.star_entity)

    for star in tt_stars:
        if star not in enemy_stars:
            continue
        target = _weakest_enemy_planet_at_star(cm, enemy_stars[star])
        if target is None or not can_invade(cm, target, empire.id):
            continue
        owner = cm.get_component(target, Owner)
        if (diplo is not None and owner is not None
                and diplo.has_peace_treaty(empire.id, owner.empire_id)):
            continue  # honour the pact; wait for it to expire
        invade_planet(game, target, empire.id)


def _ai_stage_strike(game, empire, target_empire_id: int):
    """Pre-position parked warships + troop transports toward the
    closest reachable system of ``target_empire_id`` — so the strike
    fleet is in orbit roughly when a cancelled peace treaty lapses."""
    cm = game.component_mgr
    reachable = reachable_stars(game, empire.id)
    if not reachable:
        return

    # Target's systems we can actually reach.
    target_stars: list[int] = []
    for planet_entity, owner in cm.get_all(Owner):
        if owner.empire_id != target_empire_id:
            continue
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is not None and orbit.star_entity in reachable:
            target_stars.append(orbit.star_entity)
    if not target_stars:
        return

    # Group the empire's parked strike ships by their current star.
    strike_classes = WARSHIP_CLASSES | {TROOP_TRANSPORT_CLASS}
    by_star: dict[int, list[int]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        ship = cm.get_component(ship_entity, Ship)
        owner = cm.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id != empire.id or ship.ship_class not in strike_classes:
            continue
        by_star.setdefault(at.star_entity, []).append(ship_entity)

    for src_star, ships in by_star.items():
        src_pos = cm.get_component(src_star, Position)
        if src_pos is None:
            continue
        best, best_d2 = None, float("inf")
        for ts in target_stars:
            if ts == src_star:
                continue
            tp = cm.get_component(ts, Position)
            if tp is None:
                continue
            d2 = (tp.x - src_pos.x) ** 2 + (tp.y - src_pos.y) ** 2
            if d2 < best_d2:
                best_d2, best = d2, ts
        if best is not None:
            start_fleet_movement(cm, ships, src_star, best)


def _ai_dispatch_troop_transports(cm, empire, reachable: set[int] | None = None):
    """Send idle Troop Transports to the closest reachable enemy star."""
    enemy_stars = _enemy_owned_stars(cm, empire.id)
    if reachable is not None:
        enemy_stars = {s: v for s, v in enemy_stars.items() if s in reachable}
    if not enemy_stars:
        return
    enemy_star_set = set(enemy_stars)

    ships_by_star: dict[int, list[int]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        ship = cm.get_component(ship_entity, Ship)
        owner = cm.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id != empire.id or ship.ship_class != TROOP_TRANSPORT_CLASS:
            continue
        if at.star_entity in enemy_star_set:
            continue  # already at an enemy star — invade pass handles it
        ships_by_star.setdefault(at.star_entity, []).append(ship_entity)

    for src_star, ships in ships_by_star.items():
        src_pos = cm.get_component(src_star, Position)
        if src_pos is None:
            continue
        best, best_dist = None, float("inf")
        for star in enemy_stars:
            if star == src_star:
                continue
            pos = cm.get_component(star, Position)
            if pos is None:
                continue
            d2 = (pos.x - src_pos.x) ** 2 + (pos.y - src_pos.y) ** 2
            if d2 < best_dist:
                best_dist, best = d2, star
        if best is not None:
            start_fleet_movement(cm, ships, src_star, best)


def _ai_diplomacy(game, empire, personality, turn: int):
    """Per-empire diplomacy: fear runaways, befriend the friendly, and
    (if aggressive) declare war on weaker rivals it dislikes.

    AI↔AI treaties auto-sign when both sides clear the attitude bar.
    Treaties *with the player* are left for the player to propose; the
    AI only declares/wages war on the player autonomously."""
    import random as _random
    cm = game.component_mgr
    diplo = getattr(game, "diplomacy", None)
    if diplo is None:
        return
    all_ids = [e.id for _e, e in cm.get_all(Empire)]
    others = [e for e in all_ids if e != empire.id]
    if not others:
        return

    my_strength = empire_strength(cm, empire.id)
    player_id = next((e.id for _e, e in cm.get_all(Empire) if e.is_player), None)
    aggressive = bool(personality.get("aggressive"))

    for o in others:
        o_strength = empire_strength(cm, o)
        att = diplo.attitude(empire.id, o)

        # Fear the runaway: a much stronger empire steadily loses our
        # goodwill (this is the gang-up pressure).
        if o_strength > my_strength * 1.8 and o_strength > 25:
            diplo.adjust_attitude(empire.id, o, -2)

        if diplo.at_war(empire.id, o):
            # Sue for peace if no longer rock-bottom hostile, or if we're
            # clearly the weaker side and bleeding.
            losing = my_strength < o_strength * 0.6
            if (att > -50 or losing) and _random.random() < 0.25:
                diplo.make_peace(empire.id, o, turn)
            continue

        is_player = (o == player_id)

        # Cooperative treaties — AI↔AI only (player proposes their own).
        if not is_player:
            for treaty in (NON_AGGRESSION, TRADE, RESEARCH, ALLIANCE):
                if diplo.has_treaty(empire.id, o, treaty):
                    continue
                # Both sides must want it.
                if (would_accept_treaty(diplo, empire.id, o, treaty)
                        and would_accept_treaty(diplo, o, empire.id, treaty)
                        and _random.random() < 0.4):
                    diplo.add_treaty(empire.id, o, treaty)
                    diplo.log.append(
                        f"T{turn}: Empire {empire.id} and {o} signed a "
                        f"{treaty.replace('_', ' ')}."
                    )
                    break  # one treaty per pair per turn

        # Aggression. When hostile to a rival it isn't outmatched by:
        #   * not bound by a pact → declare war outright.
        #   * bound by a pact → two options:
        #       (a) IMPATIENT: break it now and eat the betrayal penalty
        #           (reputation hit, others sever their treaties). Chosen
        #           when *really* hostile or with an overwhelming force
        #           edge — strike before the target can prepare.
        #       (b) PATIENT: cancel the pact (5-turn notice, no penalty)
        #           and stage a strike for the turn it lapses.
        if aggressive and att <= -30 and my_strength >= o_strength * 0.8:
            if not diplo.has_peace_treaty(empire.id, o):
                if _random.random() < 0.3:
                    diplo.declare_war(empire.id, o, turn, all_ids)
            else:
                very_hostile = att <= -60
                overwhelming = my_strength >= o_strength * 1.5
                if (very_hostile or overwhelming) and _random.random() < 0.35:
                    # Impatient — break the pact now (betrayal penalty).
                    diplo.declare_war(empire.id, o, turn, all_ids)
                    _ai_stage_strike(game, empire, o)
                elif not diplo.peace_cancellation_pending(empire.id, o):
                    # Patient — let the pact expire cleanly, then strike.
                    for t in (NON_AGGRESSION, ALLIANCE, DEFENSIVE_PACT):
                        if diplo.has_treaty(empire.id, o, t):
                            diplo.cancel_treaty(empire.id, o, t, turn)
                    diplo.log.append(
                        f"T{turn}: Empire {empire.id} quietly lets its pacts "
                        f"with {o} lapse — a strike is coming.")
                    _ai_stage_strike(game, empire, o)


# ---- Espionage ---------------------------------------------------------

# Keep this much BC in reserve before spending on spies.
AI_SPY_BUFFER_BC = 150
# Baseline spy ambition; grows with empire size + aggression.
AI_BASE_SPY_TARGET = 2


def _ai_espionage(game, empire, personality):
    """Train spies up to a size/aggression-scaled target, then point the
    free ones at the most-hated rival. At war / aggressive empires
    sabotage; everyone else steals tech. One defender is always kept
    home. Spy state is persisted by espionage_tick at end of turn; BC
    spent on training is netted out by the later production_tick."""
    import random as _random
    esp = getattr(game, "espionage", None)
    if esp is None:
        return
    diplo = getattr(game, "diplomacy", None)
    cm = game.component_mgr

    colonies = sum(1 for _e, o in cm.get_all(Owner) if o.empire_id == empire.id)
    target_spies = AI_BASE_SPY_TARGET + colonies // 2
    if personality.get("aggressive"):
        target_spies += 1

    # Train one spy this turn if under target and comfortably affordable.
    if (esp.spy_count(empire.id) < target_spies
            and empire.bc >= AI_SPY_BUFFER_BC + SPY_COST
            and _random.random() < 0.5):
        empire.bc -= SPY_COST
        esp.train_spy(empire.id)

    others = [e for _e, e in cm.get_all(Empire) if e.id != empire.id]
    if not others:
        return

    def hostility(o):
        if diplo is None:
            return 0
        h = -diplo.attitude(empire.id, o.id)
        if diplo.at_war(empire.id, o.id):
            h += 50
        return h

    target = max(others, key=hostility)
    # Only run offensive operations against someone we dislike or fight.
    if diplo is not None and not diplo.at_war(empire.id, target.id) \
            and diplo.attitude(empire.id, target.id) > -10:
        return

    at_war = diplo is not None and diplo.at_war(empire.id, target.id)
    mission = "sabotage" if (at_war or personality.get("aggressive")) else "steal"
    assign = max(0, esp.defense_count(empire.id) - 1)  # keep one defender
    if assign > 0:
        esp.adjust_mission(empire.id, target.id, mission, assign)


# ---- Leaders -----------------------------------------------------------

AI_LEADER_BUFFER_BC = 250


def _ai_best_colony_planet_id(game, cm, empire_id):
    """Planet id of the empire's biggest colony without a leader yet."""
    mgr = game.leaders
    best_id, best_pop = None, -1
    for eid, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        planet = cm.get_component(eid, Planet)
        pop = cm.get_component(eid, Population)
        if planet is None or pop is None:
            continue
        if mgr.colony_leader_for_planet(planet.id) is not None:
            continue
        if pop.current > best_pop:
            best_pop, best_id = pop.current, planet.id
    return best_id


def _ai_uncaptained_warship_id(game, cm, empire_id):
    """A warship id of the empire that has no ship leader yet."""
    mgr = game.leaders
    for ship_entity, owner in cm.get_all(ShipOwner):
        if owner.empire_id != empire_id:
            continue
        ship = cm.get_component(ship_entity, Ship)
        if ship is None or ship.ship_class not in WARSHIP_CLASSES:
            continue
        if mgr.ship_leader_for_ship(ship.id) is None:
            return ship.id
    return None


def _ai_leaders(game, empire, personality):
    """Hire a fitting candidate when affordable, then assign idle heroes
    to the biggest colony / an uncaptained warship. BC spent is netted
    out by production_tick; state persists via leaders_tick."""
    import random as _random
    mgr = getattr(game, "leaders", None)
    if mgr is None:
        return
    cm = game.component_mgr

    if mgr.count_for(empire.id) < MAX_LEADERS_PER_EMPIRE:
        prefer = "ship" if personality.get("aggressive") else "colony"
        pool = sorted(mgr.pool(), key=lambda l: (l.category != prefer, l.hire_cost))
        for cand in pool:
            if empire.bc >= AI_LEADER_BUFFER_BC + cand.hire_cost and _random.random() < 0.5:
                if mgr.hire(cand.id, empire.id):
                    empire.bc -= cand.hire_cost
                break

    for l in mgr.for_empire(empire.id):
        if l.category == "colony" and l.assigned_planet_id is None:
            pid = _ai_best_colony_planet_id(game, cm, empire.id)
            if pid is not None:
                mgr.assign_colony(l.id, pid)
        elif l.category == "ship" and l.assigned_ship_id is None:
            sid = _ai_uncaptained_warship_id(game, cm, empire.id)
            if sid is not None:
                mgr.assign_ship(l.id, sid)


def _ai_pick_research(tech_state: TechState, research_priority, pending_writes):
    if tech_state.current_target:
        return
    unlocked = set(tech_state.unlocked)
    locked = set(tech_state.locked_out)
    for tech_id in research_priority:
        if tech_id in unlocked or tech_id in locked:
            continue
        if not is_available(tech_id, unlocked, locked):
            continue
        tech_state.current_target = tech_id
        pending_writes.append((
            "tech",
            (tech_state.empire_id, tech_id, tech_state.progress),
        ))
        return

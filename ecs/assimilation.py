"""Conquest assimilation, revolts, and guerrilla insurgency.

Each colony tracks its ``original_race`` (the population's native race)
and an ``assimilation_progress`` 0–100. When a planet is invaded the
progress is reset to 0; each turn the new owner makes progress on
absorbing the population. While progress < 100 the colony is
"captured" and (if the original race has the ``defiant`` trait) may
rebel.

Three things happen per captured colony per turn:

1. **Assimilation.** Progress ticks up by ``BASE_ASSIMIL_RATE``,
   reduced if the captive race is Defiant. At 100 the planet's
   ``original_race`` flips to the owner's race and the colony is
   permanently absorbed.

2. **Revolt check** — defiant races only. If garrison + planet
   defences are weaker than the population's pressure, the colony
   rolls a chance of unrest. Outcomes (probability-weighted):
     * **Guerrilla strike** (most common): kicks off a multi-turn
       insurgency that sabotages buildings until suppressed.
     * **Civil unrest**: a million-strong pop loss this turn.
     * **Open uprising** (rarest): the planet returns to its original
       empire (or becomes ownerless if that empire is gone).

3. **Guerrilla resolution.** If ``guerrilla_turns > 0``, the
   insurgents may destroy a random non-defence building this turn.
   Garrison strength reduces ``guerrilla_turns`` faster — strong
   suppression wraps it up; no garrison lets it drag on.

Suppression sources (all add to garrison strength):
- Troop Transports parked at the colony's star.
- Completed planetary-defence buildings (Missile Base → Star Fortress).
- Marine combat tech (Powered Armor, Personal Shield).
- The owner's Warlord race trait.
"""
from __future__ import annotations

import random

from ecs.components import (
    Empire, Owner, Planet, Population, BuildState, Orbiting,
    Ship, ShipOwner, ShipAt,
)
from ecs.races import race_traits, traits_for_empire, trait_count
from ecs.projects import PROJECTS
from ecs.invasion import (
    _planet_defense_rating, _empire_unlocked, TROOP_TRANSPORT_CLASS,
)
from ecs.techs import (
    empire_marine_attack_bonus, empire_marine_defense_bonus,
)
from ecs.db import (
    get_connection, update_planet_conquest, update_planet_owner,
    update_planet_population, update_planet_workers,
    delete_planet_building,
)


# Tuning knobs.
BASE_ASSIMIL_RATE = 5         # progress per turn when captive is non-defiant
DEFIANT_PENALTY = 3           # subtract this when captive is Defiant
MIN_ASSIMIL_RATE = 1          # floor so progress always inches up
REVOLT_BASE_CHANCE = 0.08     # per-turn revolt roll on a defiant captured colony
GUERRILLA_TURNS = 5           # initial insurgency duration on a guerrilla outcome


def _empire_by_id(component_mgr, empire_id: int):
    for _eid, emp in component_mgr.get_all(Empire):
        if emp.id == empire_id:
            return emp
    return None


def _living_empires(component_mgr) -> set[int]:
    """Empire ids with at least one colony — used to check whether an
    uprising can hand the planet back to a still-extant original
    owner."""
    out: set[int] = set()
    for _eid, owner in component_mgr.get_all(Owner):
        out.add(owner.empire_id)
    return out


def _empire_owning_race(component_mgr, race_name: str) -> Empire | None:
    """Return a still-living empire whose race matches ``race_name``,
    or None. Used by uprisings to flip ownership back to a race-mate
    if one survives."""
    for _eid, emp in component_mgr.get_all(Empire):
        if emp.race_type == race_name:
            return emp
    return None


def _planet_garrison(component_mgr, planet_entity: int, empire_id: int) -> int:
    """Combined garrison strength on this colony — used as the dial
    against the captive population's revolt pressure."""
    star = component_mgr.get_component(planet_entity, Orbiting)
    troops = 0
    if star is not None:
        for ship_entity, at in component_mgr.get_all(ShipAt):
            if at.star_entity != star.star_entity:
                continue
            owner = component_mgr.get_component(ship_entity, ShipOwner)
            ship = component_mgr.get_component(ship_entity, Ship)
            if owner is None or ship is None:
                continue
            if owner.empire_id == empire_id and ship.ship_class == TROOP_TRANSPORT_CLASS:
                troops += 1
    bs = component_mgr.get_component(planet_entity, BuildState)
    defense_rating = _planet_defense_rating(bs)
    # Marine gear + Warlord trait add to suppression too.
    unlocked = _empire_unlocked(component_mgr, empire_id)
    marines = (empire_marine_attack_bonus(unlocked)
               + empire_marine_defense_bonus(unlocked))
    traits = traits_for_empire(component_mgr, empire_id)
    warlord = trait_count(traits, "warlord") * 2
    return troops * 5 + defense_rating + marines + warlord


def _population_pressure(component_mgr, planet_entity: int) -> int:
    """How much the colony's pop pushes against assimilation. Bigger
    populations are harder to garrison; defiant races count double."""
    pop = component_mgr.get_component(planet_entity, Population)
    n = pop.current if pop else 0
    planet = component_mgr.get_component(planet_entity, Planet)
    weight = 2
    if planet is not None and "defiant" in race_traits(planet.original_race):
        weight = 4
    return n * weight


def _pick_destructible_building(bs: BuildState) -> str | None:
    """A random completed non-defence project for guerrillas to wreck.
    Defence buildings are skipped — insurgents target economy/science,
    not the garrison."""
    if bs is None or not bs.completed:
        return None
    candidates = []
    for pid in bs.completed:
        proj = PROJECTS.get(pid, {})
        effects = proj.get("effects", {})
        # Skip planet-defence buildings — they're what's keeping the
        # garrison in place; guerrillas hit soft targets.
        if effects.get("defense", 0) > 0:
            continue
        candidates.append(pid)
    if not candidates:
        return None
    return random.choice(candidates)


def assimilation_tick(game, new_turn: int):
    """Per-turn: bring captured worlds closer to absorption, roll
    revolts on defiant captives, and run active guerrilla insurgencies.
    Persists changed planets in one DB transaction at the end."""
    cm = game.component_mgr
    rng = random
    player = game.player_empire()
    player_id = player.id if player else None
    pending: list[tuple[int, str, int, int]] = []
    pop_writes: list[tuple] = []
    worker_writes: list[tuple] = []
    owner_changes: list[tuple[int, int | None]] = []  # (planet_id, new_owner_or_None)
    destroyed: list[tuple[int, str]] = []
    log: list[str] = []

    # Snapshot up-front — an uprising can swap a planet's Owner
    # component mid-tick, which would corrupt the in-progress iteration.
    owned_entities = list(cm.get_all(Owner))
    for entity_id, owner in owned_entities:
        planet = cm.get_component(entity_id, Planet)
        if planet is None:
            continue
        # Seed the original_race on legacy / pre-feature saves.
        owner_emp = _empire_by_id(cm, owner.empire_id)
        if owner_emp is None:
            continue
        if not planet.original_race:
            planet.original_race = owner_emp.race_type
            planet.assimilation_progress = 100
            pending.append((planet.id, planet.original_race,
                            planet.assimilation_progress, planet.guerrilla_turns))
            continue
        # Already aligned — no work this turn.
        if planet.original_race == owner_emp.race_type:
            if planet.assimilation_progress < 100:
                planet.assimilation_progress = 100
                pending.append((planet.id, planet.original_race, 100, 0))
            continue

        # Captured + un-assimilated colony.
        captive_traits = race_traits(planet.original_race)
        defiant = "defiant" in captive_traits

        # 1. Progress
        rate = BASE_ASSIMIL_RATE
        if defiant:
            rate = max(MIN_ASSIMIL_RATE, rate - DEFIANT_PENALTY)
        # Owner's Warlord race a touch faster (iron-fist policy).
        owner_traits = traits_for_empire(cm, owner.empire_id)
        rate += trait_count(owner_traits, "warlord")
        # Galactic Unification tech binds captured worlds faster.
        from ecs.techs import empire_assimilation_bonus
        rate += empire_assimilation_bonus(_empire_unlocked(cm, owner.empire_id))
        planet.assimilation_progress = min(100, planet.assimilation_progress + rate)
        if planet.assimilation_progress >= 100:
            # Fully absorbed — population now identifies with new race.
            log.append(f"T{new_turn}: {planet.original_race} pop on planet "
                       f"#{planet.id} fully assimilated into {owner_emp.race_type}.")
            planet.original_race = owner_emp.race_type
            planet.guerrilla_turns = 0
            pending.append((planet.id, planet.original_race, 100, 0))
            continue

        # 2. Revolt roll — defiant races only.
        revolt_triggered = False
        if defiant:
            garrison = _planet_garrison(cm, entity_id, owner.empire_id)
            pressure = _population_pressure(cm, entity_id)
            if pressure > garrison:
                deficit = pressure - garrison
                # Stronger gap means bigger revolt chance; capped at ~25%.
                chance = min(0.25, REVOLT_BASE_CHANCE
                              + (deficit / max(1, pressure)) * 0.15)
                if rng.random() < chance:
                    revolt_triggered = True
                    roll = rng.random()
                    if roll < 0.55:
                        # Guerrilla strike — kick off insurgency.
                        planet.guerrilla_turns = max(planet.guerrilla_turns,
                                                     GUERRILLA_TURNS)
                        log.append(
                            f"T{new_turn}: Insurgency on planet #{planet.id} "
                            f"({planet.original_race} natives). Suppress with "
                            f"troops + defences."
                        )
                    elif roll < 0.85:
                        # Civil unrest — a pop falls in street fighting.
                        pop = cm.get_component(entity_id, Population)
                        if pop is not None and pop.current > 0:
                            pop.current -= 1
                            for role in ("workers", "scientists", "farmers"):
                                if getattr(pop, role) > 0:
                                    setattr(pop, role, getattr(pop, role) - 1)
                                    break
                            pop_writes.append(
                                (planet.id, pop.current, pop.max, pop.growth_progress))
                            worker_writes.append(
                                (planet.id, pop.farmers, pop.workers, pop.scientists))
                            log.append(
                                f"T{new_turn}: Civil unrest on planet #{planet.id}; "
                                f"1M pop lost."
                            )
                    else:
                        # Open uprising — flip back to the original race's empire
                        # if any still-living empire matches; otherwise abandoned.
                        homecoming = _empire_owning_race(cm, planet.original_race)
                        if homecoming is not None and homecoming.id != owner.empire_id:
                            cm.remove_component(entity_id, Owner)
                            cm.add_component(entity_id, Owner(empire_id=homecoming.id))
                            owner_changes.append((planet.id, homecoming.id))
                            # Once back home, original_race is the new owner's;
                            # assimilation resets to 100 automatically next turn.
                            log.append(
                                f"T{new_turn}: Open uprising! Planet #{planet.id} "
                                f"returned to {homecoming.name}."
                            )
                        else:
                            cm.remove_component(entity_id, Owner)
                            owner_changes.append((planet.id, None))
                            log.append(
                                f"T{new_turn}: Open uprising on planet #{planet.id}; "
                                f"colony declared independence."
                            )

        # 3. Guerrilla resolution
        if planet.guerrilla_turns > 0 and not revolt_triggered:
            # Sabotage this turn?
            sabotage_chance = max(0.15, 0.6 - _planet_garrison(
                cm, entity_id, owner.empire_id) / 60)
            if rng.random() < sabotage_chance:
                bs = cm.get_component(entity_id, BuildState)
                target = _pick_destructible_building(bs)
                if target is not None:
                    bs.completed.remove(target)
                    destroyed.append((planet.id, target))
                    from ecs.projects import PROJECTS as _P
                    pname = _P.get(target, {}).get("name", target)
                    log.append(
                        f"T{new_turn}: Insurgents destroyed {pname} on "
                        f"planet #{planet.id}."
                    )
            # Garrison wears the insurgency down — strong garrisons end
            # it in a turn or two; weak ones drag it on.
            wear = 1 + _planet_garrison(cm, entity_id, owner.empire_id) // 25
            planet.guerrilla_turns = max(0, planet.guerrilla_turns - wear)

        pending.append((planet.id, planet.original_race,
                        planet.assimilation_progress, planet.guerrilla_turns))

    # Persist.
    if not (pending or pop_writes or worker_writes or owner_changes or destroyed):
        return
    with get_connection() as conn:
        for planet_id, orig, prog, guerrillas in pending:
            update_planet_conquest(conn, planet_id, orig, prog, guerrillas)
        for planet_id, current, mx, growth in pop_writes:
            update_planet_population(conn, planet_id, current, mx, growth)
        for planet_id, f, w, s in worker_writes:
            update_planet_workers(conn, planet_id, f, w, s)
        for planet_id, new_owner in owner_changes:
            update_planet_owner(conn, planet_id, new_owner)
        for planet_id, project_id in destroyed:
            delete_planet_building(conn, planet_id, project_id)
        conn.commit()

    # Surface events to the player via a rolling log on the game
    # object — the colony screen will pick the latest entries to show.
    if log:
        existing = getattr(game, "assimilation_log", [])
        game.assimilation_log = (existing + log)[-40:]
        # Player-relevant events also go onto the espionage log so the
        # player notices them in the existing intelligence panel.
        esp = getattr(game, "espionage", None)
        if esp is not None and player_id is not None:
            for line in log:
                esp._log(line)

"""Orbital bombardment — warships shell an enemy colony from orbit.

MOO2's Doom Star earns its name here: a fleet parked over a hostile
colony can bombard it, killing population and wrecking buildings without
landing marines. It's the prelude to (or brutal alternative to) a ground
invasion, and the payoff for building big-gun capital ships.

Resolution each volley:

    power     = Σ warship attack (hull base + frozen loadout, mounts included)
    defense   = planet's completed defence-building rating
    effective = max(0, power - defense)          # defences absorb fire
    pop_lost  = effective // BOMBARD_POP_DIVISOR  (>=1 if effective>0)

Population takes the hit; with enough firepower a colony can be bombed
down to zero and destroyed (ownership cleared — the world is left
barren and recolonisable). A strong bombardment may also destroy one
non-defence building. Bombarding is an act of war (routes through the
diplomacy betrayal logic like an invasion).

One volley per colony per turn (``game.bombarded_this_turn``) so a fleet
can't shell a world to dust in a single turn of frantic clicking.
"""
from __future__ import annotations

import random

from ecs.components import (
    Planet, Owner, Population, BuildState, Orbiting, Ship, ShipOwner, ShipAt,
    Empire, Name,
)
from ecs.ships import SHIPS
from ecs.ship_design import stats_from_ship
from ecs.projects import PROJECTS
from ecs.db import (
    get_connection, update_planet_population, update_planet_workers,
    update_planet_owner, delete_planet_building,
)


# Hulls that can bombard — armed combat ships (troop transports and
# civilians can't).
BOMBARD_CLASSES = {"frigate", "carrier", "cruiser", "battleship",
                   "dreadnought", "titan", "doom_star"}

# Effective firepower needed per 1M pop killed. Tuned so a lone frigate
# scratches a colony while a Doom Star fleet depopulates one over a few
# turns.
BOMBARD_POP_DIVISOR = 4
# Effective power at/above which a volley also risks wrecking a building.
BOMBARD_BUILDING_THRESHOLD = 12
BOMBARD_BUILDING_CHANCE = 0.5


def _warships_at_star(cm, star_entity: int, empire_id: int) -> list[int]:
    out = []
    for ship_entity, at in cm.get_all(ShipAt):
        if at.star_entity != star_entity:
            continue
        owner = cm.get_component(ship_entity, ShipOwner)
        ship = cm.get_component(ship_entity, Ship)
        if owner is None or ship is None or owner.empire_id != empire_id:
            continue
        if ship.ship_class in BOMBARD_CLASSES:
            out.append(ship_entity)
    return out


def fleet_bombard_power(cm, star_entity: int, empire_id: int) -> int:
    """Total bombardment firepower of an empire's warships at a star —
    each ship's hull-class base attack plus its frozen loadout attack
    (weapon × count × mount)."""
    total = 0
    for se in _warships_at_star(cm, star_entity, empire_id):
        ship = cm.get_component(se, Ship)
        if ship is None:
            continue
        base = SHIPS.get(ship.ship_class, {}).get("attack", 0)
        total += base + stats_from_ship(ship).get("attack", 0)
    return total


def can_bombard(cm, planet_entity: int, empire_id: int) -> bool:
    """True if ``empire_id`` has ≥1 warship at the star of a populated
    colony owned by a *different* empire."""
    planet = cm.get_component(planet_entity, Planet)
    owner = cm.get_component(planet_entity, Owner)
    pop = cm.get_component(planet_entity, Population)
    orbit = cm.get_component(planet_entity, Orbiting)
    if planet is None or owner is None or orbit is None:
        return False
    if owner.empire_id == empire_id:
        return False
    if pop is None or pop.current <= 0:
        return False
    return bool(_warships_at_star(cm, orbit.star_entity, empire_id))


def _apply_pop_loss(pop: Population, amount: int) -> int:
    """Remove ``amount`` pop, trimming worker roles worker→sci→farmer.
    Returns the actual amount removed."""
    amount = min(amount, pop.current)
    pop.current -= amount
    remaining = amount
    for role in ("workers", "scientists", "farmers"):
        take = min(getattr(pop, role), remaining)
        setattr(pop, role, getattr(pop, role) - take)
        remaining -= take
        if remaining <= 0:
            break
    pop.growth_progress = 0.0
    return amount


def bombard_planet(game, planet_entity: int, empire_id: int,
                   rng: random.Random | None = None,
                   declare_war: bool = True) -> dict:
    """Resolve one bombardment volley. Returns a result dict:

        {"success": bool, "power": int, "defense": int, "effective": int,
         "pop_lost": int, "building_destroyed": str|None,
         "colony_destroyed": bool, "reason": str|None}

    ``declare_war`` routes the attack through the diplomacy betrayal
    logic (an empire bombarding another). Non-diplomatic attackers —
    the Antaran raiders — pass ``False`` since they aren't part of the
    treaty system.
    """
    rng = rng or random
    cm = game.component_mgr
    if not can_bombard(cm, planet_entity, empire_id):
        return {"success": False, "reason": "cannot_bombard", "pop_lost": 0}

    # One volley per colony per turn.
    planet = cm.get_component(planet_entity, Planet)
    already = getattr(game, "bombarded_this_turn", None)
    if already is not None and planet.id in already:
        return {"success": False, "reason": "already_bombarded_this_turn",
                "pop_lost": 0}

    orbit = cm.get_component(planet_entity, Orbiting)
    pop = cm.get_component(planet_entity, Population)
    build_state = cm.get_component(planet_entity, BuildState)
    defender_owner = cm.get_component(planet_entity, Owner)

    # Bombardment is an act of war (triggers betrayal logic if a treaty
    # was in force), mirroring invasion. Skipped for the Antarans, who
    # aren't part of the diplomacy system.
    diplo = getattr(game, "diplomacy", None)
    if declare_war and diplo is not None:
        from ecs.diplomacy import all_empire_ids
        turn = getattr(getattr(game, "galaxy", None), "turn", 0)
        diplo.note_invasion(empire_id, defender_owner.empire_id, turn,
                            all_empire_ids(cm))

    from ecs.invasion import _planet_defense_rating
    power = fleet_bombard_power(cm, orbit.star_entity, empire_id)
    defense = _planet_defense_rating(build_state)
    effective = max(0, power - defense)

    pop_lost = 0
    building_destroyed = None
    colony_destroyed = False
    if effective > 0:
        pop_lost = max(1, effective // BOMBARD_POP_DIVISOR)
        pop_lost = _apply_pop_loss(pop, pop_lost)
        # Building wreckage on a heavy volley.
        if (effective >= BOMBARD_BUILDING_THRESHOLD and build_state
                and build_state.completed and rng.random() < BOMBARD_BUILDING_CHANCE):
            destructible = [p for p in build_state.completed
                            if not PROJECTS.get(p, {}).get("effects", {}).get("defense")]
            if destructible:
                building_destroyed = rng.choice(destructible)
                build_state.completed.remove(building_destroyed)

    if pop is not None and pop.current <= 0:
        colony_destroyed = True

    # Persist.
    with get_connection() as conn:
        if colony_destroyed:
            # The colony is wiped — clear ownership + population so the
            # world reverts to a barren, recolonisable planet.
            cm.remove_component(planet_entity, Owner)
            cm.remove_component(planet_entity, Population)
            planet.original_race = ""
            planet.assimilation_progress = 100
            planet.guerrilla_turns = 0
            update_planet_owner(conn, planet.id, None)
            update_planet_population(conn, planet.id, 0, 0, 0.0)
        else:
            if pop is not None:
                update_planet_population(conn, planet.id, pop.current,
                                         pop.max, pop.growth_progress)
                update_planet_workers(conn, planet.id, pop.farmers,
                                      pop.workers, pop.scientists)
        if building_destroyed is not None:
            delete_planet_building(conn, planet.id, building_destroyed)
        conn.commit()

    if already is not None:
        already.add(planet.id)

    # Player-perspective log line.
    player = next((e for _x, e in cm.get_all(Empire) if e.is_player), None)
    if player is not None and empire_id == player.id:
        from ecs.turn_log import log as turn_log, CAT_COMBAT
        sn = cm.get_component(orbit.star_entity, Name)
        star_name = sn.value if sn else "?"
        if colony_destroyed:
            turn_log(game, CAT_COMBAT, f"Bombarded {star_name} to ruin")
        elif pop_lost:
            turn_log(game, CAT_COMBAT,
                     f"Bombarded {star_name}: -{pop_lost}M pop")

    return {
        "success": True, "power": power, "defense": defense,
        "effective": effective, "pop_lost": pop_lost,
        "building_destroyed": building_destroyed,
        "colony_destroyed": colony_destroyed, "reason": None,
    }

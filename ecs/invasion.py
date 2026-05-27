"""Planet invasion (ground combat).

Troop Transport ships parked at an enemy-owned planet can launch a
ground assault. The transport carries marines; the planet musters
militia (per million pop) plus the defense rating of every completed
military building on it. A ±20% random swing decides the winner.

- Invader wins: takes the planet (Owner switches), some transports
  are destroyed proportional to the defense's relative strength, and
  the population takes losses from the bombardment.
- Defender wins: every attacking transport is destroyed; the planet
  loses a chunk of population repelling the assault.

This is intentionally a coarse model — MOO2's tactical hex-grid land
battles aren't on the roadmap. The strength formula is deterministic
enough that defending-with-defense-buildings reliably beats a single
transport, and a fleet of transports reliably overwhelms an
undefended frontier world.
"""
from __future__ import annotations

import random

from ecs.components import (
    Planet, Orbiting, Owner, Population, BuildState,
    Ship, ShipOwner, ShipAt, ShipInTransit,
)
from ecs.projects import PROJECTS
from ecs.db import (
    get_connection, update_planet_owner, update_planet_population,
    update_planet_workers, delete_ship,
)


TROOP_TRANSPORT_CLASS = "troop_transport"
MARINES_PER_TRANSPORT = 5          # marines a single transport lands
MILITIA_PER_MILLION_POP = 2        # planetary defenders auto-raised
DEFENDER_POP_LOSS_RATIO = 0.5      # surviving pop after a successful invasion
DEFEND_POP_LOSS_ON_FAILURE = 1     # pop lost when invasion fails
RANDOM_SWING = 0.20                # ±20% on each side's effective strength


# ----------------------------------------------------------------------

def _troop_transports_at_star(component_mgr, star_entity: int, empire_id: int) -> list[int]:
    out = []
    for ship_entity, at in component_mgr.get_all(ShipAt):
        if at.star_entity != star_entity:
            continue
        owner = component_mgr.get_component(ship_entity, ShipOwner)
        ship = component_mgr.get_component(ship_entity, Ship)
        if owner is None or ship is None:
            continue
        if owner.empire_id != empire_id:
            continue
        if ship.ship_class != TROOP_TRANSPORT_CLASS:
            continue
        out.append(ship_entity)
    return out


def can_invade(component_mgr, planet_entity: int, empire_id: int) -> bool:
    """True if the planet is owned by a *different* empire and the
    invader has at least one Troop Transport parked at its star."""
    planet = component_mgr.get_component(planet_entity, Planet)
    if planet is None:
        return False
    owner = component_mgr.get_component(planet_entity, Owner)
    if owner is None or owner.empire_id == empire_id:
        return False  # no point invading an unowned or own planet
    orbit = component_mgr.get_component(planet_entity, Orbiting)
    if orbit is None:
        return False
    return bool(_troop_transports_at_star(
        component_mgr, orbit.star_entity, empire_id,
    ))


def _planet_defense_rating(build_state) -> int:
    """Sum the ``defense`` effect from every completed building."""
    if build_state is None:
        return 0
    total = 0
    for project_id in build_state.completed:
        effects = PROJECTS.get(project_id, {}).get("effects", {})
        total += effects.get("defense", 0)
    return total


def _destroy_ship_entity(game, ship_entity: int) -> int | None:
    """Remove ship components + entity. Returns the DB id (or None)
    so the caller can batch DB deletes."""
    cm = game.component_mgr
    ship = cm.get_component(ship_entity, Ship)
    db_id = ship.id if ship is not None else None
    for comp_type in (Ship, ShipOwner, ShipAt, ShipInTransit):
        cm.remove_component(ship_entity, comp_type)
    game.entity_mgr.destroy_entity(ship_entity)
    return db_id


def invade_planet(game, planet_entity: int, empire_id: int) -> dict:
    """Resolve a ground assault. Returns a small log dict:

    {"success": bool, "attacker_strength": int, "defender_strength": int,
     "transports_lost": int, "pop_lost": int}.

    Returns ``{"success": False, "reason": "..."}`` for invalid setups
    so callers can show a hint without crashing.
    """
    cm = game.component_mgr
    if not can_invade(cm, planet_entity, empire_id):
        return {"success": False, "reason": "not_invadable"}

    planet = cm.get_component(planet_entity, Planet)
    orbit = cm.get_component(planet_entity, Orbiting)
    pop = cm.get_component(planet_entity, Population)
    build_state = cm.get_component(planet_entity, BuildState)
    defender_owner = cm.get_component(planet_entity, Owner)
    if planet is None or orbit is None or defender_owner is None:
        return {"success": False, "reason": "invalid"}

    # Launching the assault is an act of war. If a peace/NAP was in
    # force this also triggers the betrayal reputation penalty.
    diplo = getattr(game, "diplomacy", None)
    if diplo is not None:
        from ecs.diplomacy import all_empire_ids
        turn = getattr(getattr(game, "galaxy", None), "turn", 0)
        diplo.note_invasion(empire_id, defender_owner.empire_id, turn,
                            all_empire_ids(cm))

    transports = _troop_transports_at_star(cm, orbit.star_entity, empire_id)
    n_transports = len(transports)
    raw_attack = n_transports * MARINES_PER_TRANSPORT
    militia = (pop.current * MILITIA_PER_MILLION_POP) if pop else 0
    defense_buildings = _planet_defense_rating(build_state)
    raw_defense = militia + defense_buildings

    # Apply random swing — both sides roll independently.
    atk_strength = raw_attack * (1 + random.uniform(-RANDOM_SWING, RANDOM_SWING))
    def_strength = raw_defense * (1 + random.uniform(-RANDOM_SWING, RANDOM_SWING))

    destroyed_db_ids: list[int] = []
    pop_lost = 0
    success = atk_strength > def_strength

    if success:
        # Invader wins. Transports destroyed proportional to how strong
        # the defense was — a token garrison costs you 0–1 ships, a
        # well-defended world costs you most of the fleet.
        loss_ratio = min(1.0, raw_defense / max(1.0, raw_attack))
        n_lost = min(n_transports, int(round(loss_ratio * n_transports)))
        for ship_entity in transports[:n_lost]:
            db_id = _destroy_ship_entity(game, ship_entity)
            if db_id is not None:
                destroyed_db_ids.append(db_id)

        # Planet changes hands. Half the pop survives the takeover
        # (rounding up so single-pop colonies still have someone left).
        old_pop = pop.current if pop else 0
        new_pop = max(1, int(round(old_pop * DEFENDER_POP_LOSS_RATIO)))
        pop_lost = old_pop - new_pop

        # Apply on the planet entity.
        cm.remove_component(planet_entity, Owner)
        cm.add_component(planet_entity, Owner(empire_id=empire_id))
        if pop is not None:
            pop.current = new_pop
            # Reset worker assignment proportionally — defenders' civic
            # infrastructure is in shambles after the assault.
            from ecs.economy import default_assignment, normalize_assignment
            farmers, workers, scientists = default_assignment(planet.planet_type, new_pop)
            pop.farmers, pop.workers, pop.scientists = farmers, workers, scientists
            pop.growth_progress = 0.0
    else:
        # Defender holds. Every transport is destroyed; the planet
        # loses a single pop from the engagement (bombardment, civil
        # damage, etc.).
        for ship_entity in transports:
            db_id = _destroy_ship_entity(game, ship_entity)
            if db_id is not None:
                destroyed_db_ids.append(db_id)
        if pop is not None and pop.current > 0:
            pop_lost = min(pop.current, DEFEND_POP_LOSS_ON_FAILURE)
            pop.current -= pop_lost
            for role in ("workers", "scientists", "farmers"):
                if getattr(pop, role) >= pop_lost:
                    setattr(pop, role, getattr(pop, role) - pop_lost)
                    break
                elif getattr(pop, role) > 0:
                    pop_lost -= getattr(pop, role)
                    setattr(pop, role, 0)
            pop.growth_progress = 0.0

    # Flush to DB.
    with get_connection() as conn:
        for db_id in destroyed_db_ids:
            delete_ship(conn, db_id)
        if success:
            update_planet_owner(conn, planet.id, empire_id)
        if pop is not None:
            update_planet_population(conn, planet.id, pop.current, pop.max, pop.growth_progress)
            update_planet_workers(conn, planet.id, pop.farmers, pop.workers, pop.scientists)
        conn.commit()

    return {
        "success": success,
        "attacker_strength": raw_attack,
        "defender_strength": raw_defense,
        "transports_lost": len(destroyed_db_ids),
        "pop_lost": pop_lost,
    }

"""Colony ship colonization and outpost claims.

- A **Colony Ship** parked at a star can be spent to settle an unowned
  habitable planet at the same star. Spending the ship destroys it and
  adds Owner + Population + BuildState components to the chosen planet
  so it joins the empire's economy on the next turn.

- An **Outpost Ship** parked at a star can be spent to plant an outpost,
  claiming the system without colonizing any planet. The ship is
  consumed and an ``Outpost`` component is attached to the star entity.
  Outposts give star-ownership colouring (the star reads as the empire's
  even with no settled planets) and reserve the system against rival
  outpost attempts.
"""
from __future__ import annotations

from ecs.components import (
    Planet, Orbiting, Owner, Population, BuildState, Empire, Outpost,
    Ship, ShipOwner, ShipAt, ShipInTransit, Name,
)
from ecs.economy import compute_max_population, default_assignment
from ecs.races import trait_count, traits_for_empire
from ecs.db import (
    get_connection, update_planet_owner, update_planet_population,
    update_planet_workers, delete_ship, update_planet_conquest,
    insert_outpost,
)
from ecs.turn_log import log as turn_log, CAT_COLONY


COLONY_SHIP_CLASS = "colony_ship"
OUTPOST_SHIP_CLASS = "outpost_ship"
INITIAL_POPULATION = 1  # 1M settlers from the colony ship


def can_colonize(component_mgr, planet_entity: int, empire_id: int) -> bool:
    """A planet is colonizable by ``empire_id`` if it's habitable, no
    one owns it yet, and the empire has at least one Colony Ship at
    the same star (parked, not in transit)."""
    planet = component_mgr.get_component(planet_entity, Planet)
    if planet is None or not planet.colonizable:
        return False
    if component_mgr.get_component(planet_entity, Owner) is not None:
        return False
    orbit = component_mgr.get_component(planet_entity, Orbiting)
    if orbit is None:
        return False
    # A living system guardian blocks settling the whole system until
    # it's destroyed.
    from ecs.monsters import monster_at_star
    if monster_at_star(component_mgr, orbit.star_entity):
        return False
    return _find_player_colony_ship_at_star(
        component_mgr, orbit.star_entity, empire_id,
    ) is not None


def _find_player_colony_ship_at_star(component_mgr, star_entity: int, empire_id: int):
    """Return one of the empire's Colony Ship entities parked at the
    given star, or None. Ships in transit (ShipInTransit) are skipped."""
    for ship_entity, at in component_mgr.get_all(ShipAt):
        if at.star_entity != star_entity:
            continue
        ship = component_mgr.get_component(ship_entity, Ship)
        owner = component_mgr.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id != empire_id:
            continue
        if ship.ship_class != COLONY_SHIP_CLASS:
            continue
        return ship_entity
    return None


def colonize_planet(game, planet_entity: int, empire_id: int) -> bool:
    """Spend a Colony Ship to settle ``planet_entity`` for ``empire_id``.

    Returns True on success. Failure cases (no eligible ship, planet
    already owned, etc.) are silent no-ops so UI callers can guard
    with ``can_colonize`` and not have to retry.
    """
    cm = game.component_mgr
    if not can_colonize(cm, planet_entity, empire_id):
        return False

    planet = cm.get_component(planet_entity, Planet)
    orbit = cm.get_component(planet_entity, Orbiting)
    if planet is None or orbit is None:
        return False

    ship_entity = _find_player_colony_ship_at_star(cm, orbit.star_entity, empire_id)
    if ship_entity is None:
        return False
    ship_comp = cm.get_component(ship_entity, Ship)
    if ship_comp is None:
        return False

    # Apply ownership + starter population to the ECS state. The
    # subterranean racial trait pads the max-pop cap by +2 per stack
    # (same rule used for homeworlds in galaxy_generator).
    traits = traits_for_empire(cm, empire_id)
    max_pop = compute_max_population(planet.planet_type, planet.size)
    max_pop += 2 * trait_count(traits, "subterranean")
    farmers, workers, scientists = default_assignment(planet.planet_type, INITIAL_POPULATION)

    cm.add_component(planet_entity, Owner(empire_id=empire_id))
    # Stamp the founding empire's race onto the planet — a fresh
    # colony is already 100% the empire's own race.
    emp = next((e for _e, e in cm.get_all(Empire) if e.id == empire_id), None)
    if emp is not None:
        planet.original_race = emp.race_type
    planet.assimilation_progress = 100
    planet.guerrilla_turns = 0
    cm.add_component(planet_entity, Population(
        current=INITIAL_POPULATION, max=max_pop,
        farmers=farmers, workers=workers, scientists=scientists,
    ))
    # BuildState — only attach if the planet didn't already have one
    # (it shouldn't, since unowned planets don't build).
    if cm.get_component(planet_entity, BuildState) is None:
        cm.add_component(planet_entity, BuildState())

    # Drop the ship entity + DB row. Mirrors combat._destroy_ship.
    ship_db_id = ship_comp.id
    for comp_type in (Ship, ShipOwner, ShipAt, ShipInTransit):
        cm.remove_component(ship_entity, comp_type)
    game.entity_mgr.destroy_entity(ship_entity)

    with get_connection() as conn:
        update_planet_owner(conn, planet.id, empire_id)
        update_planet_population(conn, planet.id, INITIAL_POPULATION, max_pop, 0.0)
        update_planet_workers(conn, planet.id, farmers, workers, scientists)
        update_planet_conquest(conn, planet.id, planet.original_race,
                                planet.assimilation_progress, planet.guerrilla_turns)
        delete_ship(conn, ship_db_id)
        conn.commit()

    # Player-perspective log entry.
    if emp is not None and emp.is_player:
        sn = cm.get_component(orbit.star_entity, Name)
        star_name = sn.value if sn else "?"
        turn_log(game, CAT_COLONY,
                 f"Colonised {planet.planet_type.title()} at {star_name}")
    return True


# ---- Outposts --------------------------------------------------------

def _find_outpost_ship_at_star(component_mgr, star_entity: int, empire_id: int):
    """Return one of ``empire_id``'s Outpost Ships parked at the given
    star (not in transit), or None."""
    for ship_entity, at in component_mgr.get_all(ShipAt):
        if at.star_entity != star_entity:
            continue
        ship = component_mgr.get_component(ship_entity, Ship)
        owner = component_mgr.get_component(ship_entity, ShipOwner)
        if ship is None or owner is None:
            continue
        if owner.empire_id != empire_id:
            continue
        if ship.ship_class != OUTPOST_SHIP_CLASS:
            continue
        return ship_entity
    return None


def star_has_outpost(component_mgr, star_entity: int) -> bool:
    return component_mgr.get_component(star_entity, Outpost) is not None


def star_outpost_owner(component_mgr, star_entity: int) -> int | None:
    """Empire id of the outpost holder, or None if no outpost."""
    out = component_mgr.get_component(star_entity, Outpost)
    return out.empire_id if out is not None else None


def _star_has_any_colony(component_mgr, star_entity: int) -> bool:
    """True if any planet orbiting this star has an Owner — outpost
    planting is blocked when a colony already exists in the system."""
    for entity_id, orbit in component_mgr.get_all(Orbiting):
        if orbit.star_entity != star_entity:
            continue
        if component_mgr.get_component(entity_id, Owner) is not None:
            return True
    return False


def can_plant_outpost(component_mgr, star_entity: int, empire_id: int) -> bool:
    """An outpost can be planted by ``empire_id`` at ``star_entity`` if:
    no outpost is already there, no planet in the system has an owner
    (any empire — outposts are for *empty* systems), and the empire has
    an Outpost Ship parked at this star."""
    if star_has_outpost(component_mgr, star_entity):
        return False
    if _star_has_any_colony(component_mgr, star_entity):
        return False
    return _find_outpost_ship_at_star(
        component_mgr, star_entity, empire_id,
    ) is not None


def plant_outpost(game, star_entity: int, empire_id: int) -> bool:
    """Spend an Outpost Ship parked at ``star_entity`` to plant an
    outpost claim for ``empire_id``. Returns True on success."""
    cm = game.component_mgr
    if not can_plant_outpost(cm, star_entity, empire_id):
        return False
    ship_entity = _find_outpost_ship_at_star(cm, star_entity, empire_id)
    if ship_entity is None:
        return False
    ship_comp = cm.get_component(ship_entity, Ship)
    if ship_comp is None:
        return False

    cm.add_component(star_entity, Outpost(empire_id=empire_id))

    # Burn the outpost ship: ECS + DB.
    ship_db_id = ship_comp.id
    for comp_type in (Ship, ShipOwner, ShipAt, ShipInTransit):
        cm.remove_component(ship_entity, comp_type)
    game.entity_mgr.destroy_entity(ship_entity)

    # Look up the star's DB id so the outpost row survives save/load.
    from ecs.components import StarRef
    ref = cm.get_component(star_entity, StarRef)
    star_db_id = ref.db_id if ref else None

    with get_connection() as conn:
        if star_db_id is not None:
            insert_outpost(conn, star_db_id, empire_id)
        delete_ship(conn, ship_db_id)
        conn.commit()

    # Player log line.
    emp = next((e for _x, e in cm.get_all(Empire) if e.id == empire_id), None)
    if emp is not None and emp.is_player:
        sn = cm.get_component(star_entity, Name)
        star_name = sn.value if sn else "?"
        turn_log(game, CAT_COLONY, f"Outpost planted at {star_name}")
    return True

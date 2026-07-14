"""The Dimensional Portal — the player's strike back at Antares.

The Antaran raiders (see ``ecs.antaran``) harass the galaxy from a
pocket dimension. Master of Orion 2's answer is the Dimensional Portal:
research it, build the gateway on a colony, mass a fleet in that system,
and tear open the way to Antares itself. Win the battle at the Antaran
homeworld and the game is won outright (an "Antaran" victory) — the
hardest, most aggressive path to the end screen.

This module is the rules engine:

- ``has_portal`` / ``can_launch_assault`` — is the strike available?
- ``launch_assault`` — snapshot the staging fleet into canonical
  ``battle.Combatant``s, throw them against a fixed, fearsome Antares
  home fleet, resolve with the SAME auto-resolver every other battle
  uses, apply losses to the survivors, and on victory stamp
  ``game.pending_endgame`` so the GalaxyScene rolls the end screen.

The Antares defenders are ECS-less throwaway combatants (they never
touch the DB), built from a Doom Star prototype so their strength tracks
the real ship/tech tables rather than a hand-tuned magic number.
"""
from __future__ import annotations

import random

from ecs.components import Ship, ShipOwner, ShipAt, ShipInTransit, Owner, Orbiting, BuildState, Planet
from ecs.ships import SHIPS
from ecs.ship_design import stats_from_ship
from ecs.battle import Combatant, resolve_auto, winner_of
from ecs.antaran import ANTARAN_EMPIRE_ID, ensure_antaran_empire
from ecs.db import get_connection, delete_ship


PORTAL_TECH = "dimensional_portal"
PORTAL_BUILDING = "dimensional_portal"

# The Antares home fleet: a wall of Doom Stars with apex Antaran gear.
# Built from this prototype so the numbers follow the ship/tech tables.
ANTARES_DEFENDER_COUNT = 8
_ANTARES_PROTO = dict(
    ship_class="doom_star",
    armor_tech="xentronium_armor",
    shield_tech="class_vii_shield",
    weapon_tech="death_ray",
    weapon_count=4,
    weapon_mount="heavy",
)

# Warship classes that can make the crossing (armed hulls only — the
# same set that can bombard).
ASSAULT_CLASSES = {"frigate", "carrier", "cruiser", "battleship",
                   "dreadnought", "titan", "doom_star"}


def _make_combatant(ship: Ship, empire_id: int, key) -> Combatant:
    """Snapshot a Ship (real or prototype) into a battle Combatant, using
    the same hull/attack derivation as ``combat._build_combatants``:
    ship-class base + frozen-loadout equipment bonuses."""
    stats = stats_from_ship(ship)
    base = SHIPS.get(ship.ship_class, {})
    hull_max = base.get("hull", 0) + stats.get("hull", 0)
    attack = base.get("attack", 0) + stats.get("attack", 0)
    shield_cap = stats.get("shield_capacity", 0)
    return Combatant(
        key=key,
        empire_id=empire_id,
        attack=attack,
        hull=hull_max,
        hull_max=hull_max,
        shield=shield_cap,
        shield_max=shield_cap,
        shield_regen=stats.get("shield_regen", 0),
        defense=stats.get("defense", 0),
    )


def _antares_defenders() -> list[Combatant]:
    proto = Ship(id=-1, **_ANTARES_PROTO)
    return [_make_combatant(proto, ANTARAN_EMPIRE_ID, f"antares_{i}")
            for i in range(ANTARES_DEFENDER_COUNT)]


def _portal_planets(cm, empire_id: int):
    """Yield (planet_entity, star_entity) for each of the empire's
    colonies that has a completed Dimensional Portal."""
    for planet_entity, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        bs = cm.get_component(planet_entity, BuildState)
        if bs is None or PORTAL_BUILDING not in bs.completed:
            continue
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is None:
            continue
        yield planet_entity, orbit.star_entity


def has_portal(cm, empire_id: int) -> bool:
    return next(_portal_planets(cm, empire_id), None) is not None


def _warships_at_star(cm, star_entity, empire_id: int) -> list[int]:
    out = []
    for ship_entity, at in cm.get_all(ShipAt):
        if at.star_entity != star_entity:
            continue
        owner = cm.get_component(ship_entity, ShipOwner)
        ship = cm.get_component(ship_entity, Ship)
        if owner is None or ship is None or owner.empire_id != empire_id:
            continue
        if ship.ship_class in ASSAULT_CLASSES:
            out.append(ship_entity)
    return out


def _launch_site(cm, empire_id: int):
    """Pick the portal system with the largest staging fleet. Returns
    (star_entity, [ship_entity, ...]) or (None, [])."""
    best_star, best_force = None, []
    for _planet, star in _portal_planets(cm, empire_id):
        force = _warships_at_star(cm, star, empire_id)
        if len(force) > len(best_force):
            best_star, best_force = star, force
    return best_star, best_force


def can_launch_assault(game, empire_id: int) -> tuple[bool, str]:
    """(ok, reason). Requires a completed portal AND at least one
    warship staged in a portal system."""
    cm = game.component_mgr
    if not has_portal(cm, empire_id):
        return False, "no_portal"
    star, force = _launch_site(cm, empire_id)
    if not force:
        return False, "no_fleet"
    return True, "ok"


def _remove_ships(game, ship_entities: list[int]):
    """Delete lost attackers from ECS + DB."""
    cm = game.component_mgr
    ids = []
    for e in ship_entities:
        ship = cm.get_component(e, Ship)
        if ship is not None and ship.id is not None:
            ids.append(ship.id)
    if ids:
        with get_connection() as conn:
            for sid in ids:
                delete_ship(conn, sid)
            conn.commit()
    for e in ship_entities:
        for comp in (Ship, ShipOwner, ShipAt, ShipInTransit):
            cm.remove_component(e, comp)
        game.entity_mgr.destroy_entity(e)


def launch_assault(game, empire_id: int,
                   rng: random.Random | None = None) -> dict:
    """Resolve the assault on Antares. Returns a result dict::

        {"launched": bool, "victory": bool, "sent": int, "lost": int,
         "defenders": int, "reason": str|None}

    On victory, sets ``game.pending_endgame`` so the end screen fires.
    Lost attacker ships are destroyed either way; survivors return home
    (they stay parked at the staging star)."""
    rng = rng or random.Random()
    cm = game.component_mgr
    ok, reason = can_launch_assault(game, empire_id)
    if not ok:
        return {"launched": False, "victory": False, "sent": 0, "lost": 0,
                "defenders": 0, "reason": reason}

    star, force = _launch_site(cm, empire_id)
    attackers = [_make_combatant(cm.get_component(e, Ship), empire_id, e)
                 for e in force]
    defenders = _antares_defenders()
    ensure_antaran_empire(game)

    rosters = {empire_id: attackers, ANTARAN_EMPIRE_ID: defenders}
    resolve_auto(rosters, {}, lambda a, b: a != b, rng)
    winner = winner_of(rosters)

    lost = [c.key for c in attackers if c.destroyed]
    _remove_ships(game, lost)

    victory = winner == empire_id
    result = {"launched": True, "victory": victory, "sent": len(force),
              "lost": len(lost), "defenders": len(defenders), "reason": None}
    if victory:
        game.pending_endgame = {"result": "victory", "mode": "Antaran",
                                "winner_id": empire_id}
    return result

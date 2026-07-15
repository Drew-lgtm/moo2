"""Orbital blockade — a hostile fleet chokes a colony's trade.

MOO2 lets a fleet parked over an enemy colony blockade it: no marines,
no bombardment, just presence. Trade income from that colony dries up
until the blockading fleet is driven off. It's the low-commitment
economic-warfare option — pressure a rival's treasury without the
escalation of invasion or the pop-slaughter of bombardment.

Model: a colony is blockaded if an empire AT WAR with its owner has at
least one warship parked at the colony's star. While blockaded, the
colony contributes no BC to its empire (see economy.production_tick) —
buildings still rise from local industry, but commerce is cut.

The colony-less pseudo-empires (Antaran raiders, space monsters) do NOT
blockade — they have their own bombardment / guardian behaviour and
aren't part of the diplomacy (at-war) system.
"""
from __future__ import annotations

from ecs.components import Owner, Orbiting, Ship, ShipOwner, ShipAt


# Armed hulls that can enforce a blockade (same set that can bombard).
BLOCKADE_CLASSES = {"frigate", "carrier", "cruiser", "battleship",
                    "dreadnought", "titan", "doom_star"}


def is_blockaded(cm, planet_entity: int, diplo) -> bool:
    """True if a real empire at war with this colony's owner has >=1
    warship at the colony's star."""
    owner = cm.get_component(planet_entity, Owner)
    orbit = cm.get_component(planet_entity, Orbiting)
    if owner is None or orbit is None or diplo is None:
        return False
    from ecs.monsters import is_pseudo_empire
    for ship_entity, at in cm.get_all(ShipAt):
        if at.star_entity != orbit.star_entity:
            continue
        s_owner = cm.get_component(ship_entity, ShipOwner)
        ship = cm.get_component(ship_entity, Ship)
        if s_owner is None or ship is None:
            continue
        if s_owner.empire_id == owner.empire_id:
            continue
        if is_pseudo_empire(s_owner.empire_id):
            continue  # raiders/monsters don't blockade
        if ship.ship_class not in BLOCKADE_CLASSES:
            continue
        if diplo.at_war(s_owner.empire_id, owner.empire_id):
            return True
    return False

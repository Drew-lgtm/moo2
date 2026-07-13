"""Ship class catalog.

Each entry defines a ship class that can be built at a planet via the
build queue. Ship "projects" live in ecs.projects.PROJECTS with id
``ship_<class>`` and type "ship"; completing one spawns a Ship entity at
the building planet's star instead of marking the project as completed.

Combat stats (attack, hull) are placeholders for the future combat tick.
``speed`` is parsecs per turn — used by the fleet movement tick once
that lands.

**Speed model**: in vacuum there's no drag, so cruise speed is set by
the drive tech rather than hull size. Every combat hull therefore
ships at the same baseline speed (2). Scout is the only outlier — its
dedicated reconnaissance frame trades hull / armor mass for extra
engines, justifying a +1 speed advantage at the design level. Drive
tech (Nuclear → Fusion → Ion → …) adds an empire-wide bonus on top.
"""
from __future__ import annotations


SHIPS: dict[str, dict] = {
    # ---- Civilian ships --------------------------------------------------
    # No-attack utility hulls. Each plays a different logistic role:
    # Scout extends visibility; Freighter hauls food + colonists between
    # colonies (MOO2's freighter pool, to be wired into the economy);
    # Outpost Ship claims empty systems; Colony Ship founds new colonies.
    #
    # ``space`` is the equipment budget every ship of this class carries.
    # Bigger hulls fit more (and bigger) gear: more weapons, thicker
    # armor, better shields, more specials. Civilians get just enough
    # room for armor + shield.
    "scout": {
        "id": "scout", "name": "Scout", "ship_class_kind": "civilian",
        "cost": 20, "speed": 3, "attack": 0, "hull": 1, "space": 4,
        "image": "ships/frigate.png",
        "description": "Dedicated recon hull. +1 speed over the line.",
    },
    "freighter": {
        "id": "freighter", "name": "Freighter", "ship_class_kind": "civilian",
        "cost": 50, "speed": 2, "attack": 0, "hull": 4, "space": 4,
        "image": "ships/carrier.png",
        "description": "Hauls colonists and food between worlds. "
                       "Required for inter-colony food redistribution.",
    },
    "outpost_ship": {
        "id": "outpost_ship", "name": "Outpost Ship", "ship_class_kind": "civilian",
        "cost": 80, "speed": 2, "attack": 0, "hull": 3, "space": 4,
        "image": "ships/frigate.png",
        "description": "Plants an outpost in an empty system.",
    },
    "colony_ship": {
        "id": "colony_ship", "name": "Colony Ship", "ship_class_kind": "civilian",
        "cost": 120, "speed": 2, "attack": 0, "hull": 4, "space": 6,
        "image": "ships/carrier.png",
        "description": "Founds a new colony on an unowned habitable planet.",
    },
    # ---- Military ships --------------------------------------------------
    # All combat hulls share the same base cruise speed (2). Drive tech
    # (Power field in the tech tree) lifts every ship in the fleet by
    # the same amount, so warship size doesn't compromise strategic
    # mobility — only acceleration in tactical combat would, and we
    # don't model that yet.
    "troop_transport": {
        "id": "troop_transport", "name": "Troop Transport", "ship_class_kind": "military",
        "cost": 70, "speed": 2, "attack": 1, "hull": 5, "space": 6,
        "image": "ships/carrier.png",
        "description": "Carries marines to invade enemy planets.",
    },
    "frigate": {
        "id": "frigate", "name": "Frigate", "ship_class_kind": "military",
        "cost": 30, "speed": 2, "attack": 1, "hull": 2, "space": 6,
        "image": "ships/frigate.png",
        "description": "Small skirmisher.",
    },
    "carrier": {
        "id": "carrier", "name": "Carrier", "ship_class_kind": "military",
        "cost": 60, "speed": 2, "attack": 2, "hull": 4, "space": 12,
        "image": "ships/carrier.png",
        "description": "Medium hull with fighter complement.",
    },
    "cruiser": {
        "id": "cruiser", "name": "Cruiser", "ship_class_kind": "military",
        "cost": 80, "speed": 2, "attack": 3, "hull": 6, "space": 20,
        "image": "ships/cruiser.png",
        "description": "Workhorse warship.",
    },
    "battleship": {
        "id": "battleship", "name": "Battleship", "ship_class_kind": "military",
        "cost": 150, "speed": 2, "attack": 6, "hull": 12, "space": 35,
        "image": "ships/battleship.png",
        "description": "Heavy line-of-battle vessel.",
    },
    "dreadnought": {
        "id": "dreadnought", "name": "Dreadnought", "ship_class_kind": "military",
        "cost": 250, "speed": 2, "attack": 12, "hull": 20, "space": 60,
        "image": "ships/dreadnought.png",
        "description": "Capital ship. Devastating in a fleet engagement.",
    },
    # ---- Apex hulls (tech-gated) ----------------------------------------
    # Titan and Doom Star sit above the Dreadnought and require dedicated
    # construction techs. Their huge space budgets let a designer fit
    # heavy-mount batteries or a Stellar Converter that smaller hulls
    # can't carry — the payoff for a long tech investment.
    "titan": {
        "id": "titan", "name": "Titan", "ship_class_kind": "military",
        "cost": 500, "speed": 2, "attack": 20, "hull": 34, "space": 100,
        "image": "ships/dreadnought.png",
        "description": "Colossal warship. Requires Titan Construction.",
        "required_tech": "titan_construction",
    },
    "doom_star": {
        "id": "doom_star", "name": "Doom Star", "ship_class_kind": "military",
        "cost": 900, "speed": 2, "attack": 34, "hull": 60, "space": 170,
        "image": "ships/dreadnought.png",
        "description": "Apex battle station. Requires Doom Star Construction.",
        "required_tech": "doom_star_construction",
    },
}

# Order ships appear in the Build screen: civilians first (smaller to
# bigger commitment), then military (smaller to bigger).
SHIP_ORDER = [
    "scout", "freighter", "outpost_ship", "colony_ship",
    "troop_transport", "frigate", "carrier", "cruiser", "battleship",
    "dreadnought", "titan", "doom_star",
]

CIVILIAN_SHIPS = [s for s, spec in SHIPS.items() if spec.get("ship_class_kind") == "civilian"]
MILITARY_SHIPS = [s for s, spec in SHIPS.items() if spec.get("ship_class_kind") == "military"]


def ship(ship_class: str) -> dict | None:
    return SHIPS.get(ship_class)


# ---- Freighter (logistics) capacity ----------------------------------
#
# How much food the empire can physically move between colonies per
# turn. A small baseline represents private shuttles + civilian
# bureaucracy so a one-planet empire never needs a Freighter. Every
# Freighter ship the empire owns adds the per-ship capacity. Used by
# ``pop_growth_tick`` to gate inter-colony food transport.
BASELINE_FREIGHTER_CAPACITY = 5
FREIGHTER_FOOD_CAPACITY = 5


def empire_freighter_capacity(component_mgr, empire_id: int) -> int:
    """Total food units the empire can ship between colonies each turn.

    Lazy-imported components so this module stays light (ships.py is
    imported very early during scene setup)."""
    from ecs.components import Ship, ShipOwner
    count = 0
    for ship_entity, owner in component_mgr.get_all(ShipOwner):
        if owner.empire_id != empire_id:
            continue
        s = component_mgr.get_component(ship_entity, Ship)
        if s is not None and s.ship_class == "freighter":
            count += 1
    return BASELINE_FREIGHTER_CAPACITY + count * FREIGHTER_FOOD_CAPACITY

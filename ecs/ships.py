"""Ship class catalog.

Each entry defines a ship class that can be built at a planet via the
build queue. Ship "projects" live in ecs.projects.PROJECTS with id
``ship_<class>`` and type "ship"; completing one spawns a Ship entity at
the building planet's star instead of marking the project as completed.

Combat stats (attack, hull) are placeholders for the future combat tick.
``speed`` is parsecs per turn — used by the fleet movement tick once
that lands.
"""
from __future__ import annotations


SHIPS: dict[str, dict] = {
    # ---- Civilian ships --------------------------------------------------
    # Cheap, no-attack utility hulls. Scout extends visibility; Transport
    # ferries population (when colonization lands); Outpost claims empty
    # systems; Colony Ship founds new colonies.
    "scout": {
        "id": "scout", "name": "Scout", "ship_class_kind": "civilian",
        "cost": 20, "speed": 4, "attack": 0, "hull": 1,
        "image": "ships/frigate.png",
        "description": "Fast recon. Long-range eyes for the empire.",
    },
    "transport": {
        "id": "transport", "name": "Transport", "ship_class_kind": "civilian",
        "cost": 50, "speed": 2, "attack": 0, "hull": 4,
        "image": "ships/carrier.png",
        "description": "Carries population between colonies.",
    },
    "outpost_ship": {
        "id": "outpost_ship", "name": "Outpost Ship", "ship_class_kind": "civilian",
        "cost": 80, "speed": 2, "attack": 0, "hull": 3,
        "image": "ships/frigate.png",
        "description": "Plants an outpost in an empty system.",
    },
    "colony_ship": {
        "id": "colony_ship", "name": "Colony Ship", "ship_class_kind": "civilian",
        "cost": 120, "speed": 2, "attack": 0, "hull": 4,
        "image": "ships/carrier.png",
        "description": "Founds a new colony on an unowned habitable planet.",
    },
    # ---- Military ships --------------------------------------------------
    "frigate": {
        "id": "frigate", "name": "Frigate", "ship_class_kind": "military",
        "cost": 30, "speed": 3, "attack": 1, "hull": 2,
        "image": "ships/frigate.png",
        "description": "Small skirmisher.",
    },
    "carrier": {
        "id": "carrier", "name": "Carrier", "ship_class_kind": "military",
        "cost": 60, "speed": 2, "attack": 2, "hull": 4,
        "image": "ships/carrier.png",
        "description": "Medium hull with fighter complement.",
    },
    "cruiser": {
        "id": "cruiser", "name": "Cruiser", "ship_class_kind": "military",
        "cost": 80, "speed": 2, "attack": 3, "hull": 6,
        "image": "ships/cruiser.png",
        "description": "Workhorse warship.",
    },
    "battleship": {
        "id": "battleship", "name": "Battleship", "ship_class_kind": "military",
        "cost": 150, "speed": 1, "attack": 6, "hull": 12,
        "image": "ships/battleship.png",
        "description": "Heavy line-of-battle vessel.",
    },
    "dreadnought": {
        "id": "dreadnought", "name": "Dreadnought", "ship_class_kind": "military",
        "cost": 250, "speed": 1, "attack": 12, "hull": 20,
        "image": "ships/dreadnought.png",
        "description": "Capital ship. Devastating in a fleet engagement.",
    },
}

# Order ships appear in the Build screen: civilians first (smaller to
# bigger commitment), then military (smaller to bigger).
SHIP_ORDER = [
    "scout", "transport", "outpost_ship", "colony_ship",
    "frigate", "carrier", "cruiser", "battleship", "dreadnought",
]

CIVILIAN_SHIPS = [s for s, spec in SHIPS.items() if spec.get("ship_class_kind") == "civilian"]
MILITARY_SHIPS = [s for s, spec in SHIPS.items() if spec.get("ship_class_kind") == "military"]


def ship(ship_class: str) -> dict | None:
    return SHIPS.get(ship_class)

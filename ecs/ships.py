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
    "frigate": {
        "id": "frigate",
        "name": "Frigate",
        "cost": 30,
        "speed": 3,
        "attack": 1,
        "hull": 2,
        "image": "ships/frigate.png",
    },
    "carrier": {
        "id": "carrier",
        "name": "Carrier",
        "cost": 60,
        "speed": 2,
        "attack": 2,
        "hull": 4,
        "image": "ships/carrier.png",
    },
    "cruiser": {
        "id": "cruiser",
        "name": "Cruiser",
        "cost": 80,
        "speed": 2,
        "attack": 3,
        "hull": 6,
        "image": "ships/cruiser.png",
    },
    "battleship": {
        "id": "battleship",
        "name": "Battleship",
        "cost": 150,
        "speed": 1,
        "attack": 6,
        "hull": 12,
        "image": "ships/battleship.png",
    },
    "dreadnought": {
        "id": "dreadnought",
        "name": "Dreadnought",
        "cost": 250,
        "speed": 1,
        "attack": 12,
        "hull": 20,
        "image": "ships/dreadnought.png",
    },
}

SHIP_ORDER = ["frigate", "carrier", "cruiser", "battleship", "dreadnought"]


def ship(ship_class: str) -> dict | None:
    return SHIPS.get(ship_class)

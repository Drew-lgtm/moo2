"""Per-planet construction project catalog.

A project has a cost (build points) and an effects dict applied to the
planet when complete. Recognized effect keys:

- "bc":           int   — flat BC per turn added to planet output
- "research":     int   — flat research per turn added to planet output
- "max_pop":      int   — applied ONCE at completion, bumping Population.max
- "growth_rate":  float — added to the base logistic growth rate

Projects also carry a ``type`` field:

- "building" (default): on completion, the project id is appended to
  BuildState.completed and its flat effects start applying every turn.
- "ship": on completion, a Ship entity of class ``ship_class`` is spawned
  at the building planet's star; the project does NOT enter completed,
  so the player can rebuild it any number of times.
"""
from __future__ import annotations

from ecs.ships import SHIPS, SHIP_ORDER


PROJECTS: dict[str, dict] = {
    "factory": {
        "id": "factory",
        "name": "Factory",
        "cost": 60,
        "description": "+2 BC per turn",
        "effects": {"bc": 2},
    },
    "granary": {
        "id": "granary",
        "name": "Granary",
        "cost": 60,
        "description": "Population grows faster",
        "effects": {"growth_rate": 0.2},
    },
    "research_lab": {
        "id": "research_lab",
        "name": "Research Lab",
        "cost": 60,
        "description": "+3 Research per turn",
        "effects": {"research": 3},
        "required_tech": "computer_science",
    },
    "hydroponics": {
        "id": "hydroponics",
        "name": "Hydroponics",
        "cost": 80,
        "description": "+2 max population",
        "effects": {"max_pop": 2},
        "required_tech": "agriculture",
    },
    "marketplace": {
        "id": "marketplace",
        "name": "Marketplace",
        "cost": 80,
        "description": "+3 BC, faster growth",
        "effects": {"bc": 3, "growth_rate": 0.1},
        "required_tech": "trade",
    },
    "capital": {
        "id": "capital",
        "name": "Capital",
        "cost": 120,
        "description": "+2 BC, +2 Research, +1 max pop",
        "effects": {"bc": 2, "research": 2, "max_pop": 1},
        "required_tech": "governance",
    },
    "atmospheric_renewer": {
        "id": "atmospheric_renewer",
        "name": "Atmospheric Renewer",
        "cost": 180,
        "description": "+2 max pop, faster growth",
        "effects": {"max_pop": 2, "growth_rate": 0.1},
        "required_tech": "advanced_construction",
    },
    "automated_factory": {
        "id": "automated_factory",
        "name": "Automated Factory",
        "cost": 250,
        "description": "+5 BC per turn",
        "effects": {"bc": 5},
        "required_tech": "automated_factories",
    },
    "stock_exchange": {
        "id": "stock_exchange",
        "name": "Stock Exchange",
        "cost": 180,
        "description": "+5 BC, faster growth",
        "effects": {"bc": 5, "growth_rate": 0.1},
        "required_tech": "financial_planning",
    },
    "supercomputer": {
        "id": "supercomputer",
        "name": "Supercomputer",
        "cost": 200,
        "description": "+6 Research per turn",
        "effects": {"research": 6},
        "required_tech": "advanced_computers",
    },
    "galactic_cybernet": {
        "id": "galactic_cybernet",
        "name": "Galactic Cybernet",
        "cost": 350,
        "description": "+12 Research per turn",
        "effects": {"research": 12},
        "required_tech": "galactic_networks",
    },
    "soil_enrichment_b": {
        "id": "soil_enrichment_b",
        "name": "Soil Enrichment",
        "cost": 200,
        "description": "+1 max pop, faster growth",
        "effects": {"max_pop": 1, "growth_rate": 0.2},
        "required_tech": "soil_enrichment",
    },
    "cloning_center": {
        "id": "cloning_center",
        "name": "Cloning Center",
        "cost": 250,
        "description": "+1 max pop, much faster growth",
        "effects": {"max_pop": 1, "growth_rate": 0.3},
        "required_tech": "cloning",
    },
    # ---- Tier 4 expansions (added with the physics field overhaul) ----
    "deep_core_mine": {
        "id": "deep_core_mine",
        "name": "Deep Core Mine",
        "cost": 300,
        "description": "+8 BC per turn",
        "effects": {"bc": 8},
        "required_tech": "robo_miners",
    },
    "vr_network": {
        "id": "vr_network",
        "name": "VR Network",
        "cost": 280,
        "description": "+4 Research, faster growth",
        "effects": {"research": 4, "growth_rate": 0.15},
        "required_tech": "virtual_reality_network",
    },
    "positronic_brain": {
        "id": "positronic_brain",
        "name": "Positronic Brain",
        "cost": 400,
        "description": "+15 Research per turn",
        "effects": {"research": 15},
        "required_tech": "positronic_computers",
    },
    "terraforming": {
        "id": "terraforming",
        "name": "Terraforming",
        "cost": 350,
        "description": "+3 max pop",
        "effects": {"max_pop": 3},
        "required_tech": "terraforming",
    },
}

# Inject ship projects from the SHIPS catalog so SystemView gets them
# automatically. Each maps to a build project of type "ship".
for _ship_id in SHIP_ORDER:
    _spec = SHIPS[_ship_id]
    PROJECTS[f"ship_{_ship_id}"] = {
        "id": f"ship_{_ship_id}",
        "name": _spec["name"],
        "cost": _spec["cost"],
        "description": f"Hull {_spec['hull']}  Attack {_spec['attack']}  Speed {_spec['speed']}",
        "type": "ship",
        "ship_class": _ship_id,
    }


# Display order in pickers. Two rows of buildings now that the tech
# tree adds late-game choices; the colony scene wraps if it overflows.
BUILDING_ORDER = [
    # Early game (free or simple tech)
    "factory", "granary", "research_lab", "hydroponics", "marketplace", "capital",
    # Mid / late game (gated by deeper tech)
    "atmospheric_renewer", "automated_factory", "stock_exchange",
    "supercomputer", "galactic_cybernet", "soil_enrichment_b", "cloning_center",
    # Late game (tier-4 tech unlocks)
    "deep_core_mine", "vr_network", "positronic_brain", "terraforming",
]
SHIP_PROJECT_ORDER = [f"ship_{s}" for s in SHIP_ORDER]
PROJECT_ORDER = BUILDING_ORDER + SHIP_PROJECT_ORDER


def project_is_available(project_id: str, unlocked_techs: set[str] | list) -> bool:
    """A project requires its `required_tech` (if any) to be in
    `unlocked_techs`. Projects without that key are always available."""
    proj = PROJECTS.get(project_id)
    if proj is None:
        return False
    required = proj.get("required_tech")
    if required is None:
        return True
    return required in set(unlocked_techs)


def building_growth_bonus(completed_ids) -> float:
    """Sum the growth_rate bonuses from a planet's completed buildings."""
    total = 0.0
    for project_id in completed_ids:
        total += PROJECTS.get(project_id, {}).get("effects", {}).get("growth_rate", 0.0)
    return total


def project(project_id: str) -> dict | None:
    return PROJECTS.get(project_id)

"""Per-planet construction project catalog.

A project has a cost (build points) and an effects dict applied to the
planet when complete. Recognized effect keys:

- "bc":           int   — flat BC per turn added to planet output
- "research":     int   — flat research per turn added to planet output
- "max_pop":      int   — applied ONCE at completion, bumping Population.max
- "growth_rate":  float — added to the base logistic growth rate

The build system uses each planet's BC output as its "industry" per turn:
while a project is active, that BC accumulates toward the project's cost
instead of flowing to the empire. Research always flows to the empire.
"""
from __future__ import annotations


PROJECTS: dict[str, dict] = {
    "factory": {
        "id": "factory",
        "name": "Factory",
        "cost": 60,
        "description": "+2 BC per turn",
        "effects": {"bc": 2},
    },
    "research_lab": {
        "id": "research_lab",
        "name": "Research Lab",
        "cost": 60,
        "description": "+3 Research per turn",
        "effects": {"research": 3},
    },
    "hydroponics": {
        "id": "hydroponics",
        "name": "Hydroponics",
        "cost": 80,
        "description": "+2 max population",
        "effects": {"max_pop": 2},
    },
    "marketplace": {
        "id": "marketplace",
        "name": "Marketplace",
        "cost": 80,
        "description": "+3 BC, faster growth",
        "effects": {"bc": 3, "growth_rate": 0.1},
    },
    "granary": {
        "id": "granary",
        "name": "Granary",
        "cost": 60,
        "description": "Population grows faster",
        "effects": {"growth_rate": 0.2},
    },
    "capital": {
        "id": "capital",
        "name": "Capital",
        "cost": 120,
        "description": "+2 BC, +2 Research, +1 max pop",
        "effects": {"bc": 2, "research": 2, "max_pop": 1},
    },
}

# Display order in pickers.
PROJECT_ORDER = ["factory", "research_lab", "hydroponics", "marketplace", "granary", "capital"]


def building_growth_bonus(completed_ids) -> float:
    """Sum the growth_rate bonuses from a planet's completed buildings."""
    total = 0.0
    for project_id in completed_ids:
        total += PROJECTS.get(project_id, {}).get("effects", {}).get("growth_rate", 0.0)
    return total


def project(project_id: str) -> dict | None:
    return PROJECTS.get(project_id)

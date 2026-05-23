"""Empire-level tech tree.

Each tech has a research-point cost and optional prerequisites (other
tech ids that must be unlocked first). When unlocked, a tech can gate
new project entries via projects[*]["required_tech"].

Research from production_tick accumulates against the current target
(see TechState). On completion, the tech moves to unlocked and progress
resets; any overflow is discarded for now (simpler than build progress,
since research goal-switching is the usual case anyway).
"""
from __future__ import annotations


TECHS: dict[str, dict] = {
    "computer_science": {
        "id": "computer_science",
        "name": "Computer Science",
        "cost": 80,
        "prereqs": [],
        "description": "Enables Research Lab",
    },
    "agriculture": {
        "id": "agriculture",
        "name": "Agriculture",
        "cost": 80,
        "prereqs": [],
        "description": "Enables Hydroponics",
    },
    "trade": {
        "id": "trade",
        "name": "Trade",
        "cost": 100,
        "prereqs": [],
        "description": "Enables Marketplace",
    },
    "industrial_engineering": {
        "id": "industrial_engineering",
        "name": "Industrial Engineering",
        "cost": 100,
        "prereqs": [],
        "description": "Prerequisite for Capital",
    },
    "governance": {
        "id": "governance",
        "name": "Governance",
        "cost": 200,
        "prereqs": ["trade", "industrial_engineering"],
        "description": "Enables Capital",
    },
}

# Display order in pickers.
TECH_ORDER = [
    "computer_science",
    "agriculture",
    "trade",
    "industrial_engineering",
    "governance",
]


def is_available(tech_id: str, unlocked: set[str] | list) -> bool:
    """A tech can be researched only if its prereqs are unlocked and it
    isn't already unlocked itself."""
    if tech_id not in TECHS:
        return False
    if tech_id in unlocked:
        return False
    unlocked_set = set(unlocked)
    return all(p in unlocked_set for p in TECHS[tech_id]["prereqs"])

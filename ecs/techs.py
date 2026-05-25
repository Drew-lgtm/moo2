"""Empire-level tech tree, organised MOO2-style by field and tier.

5 fields are represented: Construction, Power, Sociology, Computers,
Biology. Physics and Force Fields exist in MOO2 too but get deferred
until weapons + shields land. Each tech carries:

- ``field``: which column it occupies in the Research scene.
- ``tier``: row 1..5; higher tiers cost more and have prereqs.
- ``cost``: research points to unlock.
- ``prereqs``: tech ids that must already be unlocked.
- ``description``: brief summary shown in tooltips / panels.
- optional ``speed_bonus``: drive techs contribute this to the
  empire's ship speed (max across unlocked drive techs; not additive).

Research from production_tick routes to TechState.current_target; on
completion the tech moves to ``unlocked`` and gates new projects via
projects.required_tech.
"""
from __future__ import annotations


# Fields the catalog covers (order = display order in Research scene).
FIELDS = ["construction", "power", "sociology", "computers", "biology"]

FIELD_NAMES = {
    "construction": "Construction",
    "power":        "Power",
    "sociology":    "Sociology",
    "computers":    "Computers",
    "biology":      "Biology",
}

# Display colours per field; used by the Research scene to tint columns.
FIELD_COLORS = {
    "construction": (210, 150, 80),
    "power":        (230, 200, 80),
    "sociology":    (160, 220, 140),
    "computers":    (140, 180, 230),
    "biology":      (150, 220, 180),
}


TECHS: dict[str, dict] = {
    # ---- Construction ------------------------------------------------------
    "industrial_engineering": {
        "id": "industrial_engineering",
        "name": "Industrial Engineering",
        "field": "construction",
        "tier": 1,
        "cost": 80,
        "prereqs": [],
        "description": "Enables Factory",
    },
    "advanced_construction": {
        "id": "advanced_construction",
        "name": "Advanced Construction",
        "field": "construction",
        "tier": 2,
        "cost": 200,
        "prereqs": ["industrial_engineering"],
        "description": "Enables Atmospheric Renewer",
    },
    "automated_factories": {
        "id": "automated_factories",
        "name": "Automated Factories",
        "field": "construction",
        "tier": 3,
        "cost": 400,
        "prereqs": ["advanced_construction"],
        "description": "Enables Automated Factory",
    },

    # ---- Power (drives) ----------------------------------------------------
    "nuclear_drives": {
        "id": "nuclear_drives",
        "name": "Nuclear Drives",
        "field": "power",
        "tier": 1,
        "cost": 100,
        "prereqs": [],
        "description": "Ships gain +1 speed",
        "speed_bonus": 1,
    },
    "fusion_drives": {
        "id": "fusion_drives",
        "name": "Fusion Drives",
        "field": "power",
        "tier": 2,
        "cost": 200,
        "prereqs": ["nuclear_drives"],
        "description": "Ships gain +2 speed (replaces Nuclear)",
        "speed_bonus": 2,
    },
    "ion_drives": {
        "id": "ion_drives",
        "name": "Ion Drives",
        "field": "power",
        "tier": 3,
        "cost": 350,
        "prereqs": ["fusion_drives"],
        "description": "Ships gain +3 speed (replaces Fusion)",
        "speed_bonus": 3,
    },
    "anti_matter_drives": {
        "id": "anti_matter_drives",
        "name": "Anti-Matter Drives",
        "field": "power",
        "tier": 4,
        "cost": 500,
        "prereqs": ["ion_drives"],
        "description": "Ships gain +4 speed",
        "speed_bonus": 4,
    },
    "hyper_drives": {
        "id": "hyper_drives",
        "name": "Hyper Drives",
        "field": "power",
        "tier": 5,
        "cost": 800,
        "prereqs": ["anti_matter_drives"],
        "description": "Ships gain +6 speed",
        "speed_bonus": 6,
    },

    # ---- Sociology ---------------------------------------------------------
    "trade": {
        "id": "trade",
        "name": "Trade",
        "field": "sociology",
        "tier": 1,
        "cost": 100,
        "prereqs": [],
        "description": "Enables Marketplace",
    },
    "governance": {
        "id": "governance",
        "name": "Governance",
        "field": "sociology",
        "tier": 2,
        "cost": 200,
        "prereqs": ["trade", "industrial_engineering"],
        "description": "Enables Capital",
    },
    "financial_planning": {
        "id": "financial_planning",
        "name": "Financial Planning",
        "field": "sociology",
        "tier": 3,
        "cost": 300,
        "prereqs": ["governance"],
        "description": "Enables Stock Exchange",
    },

    # ---- Computers ---------------------------------------------------------
    "computer_science": {
        "id": "computer_science",
        "name": "Computer Science",
        "field": "computers",
        "tier": 1,
        "cost": 80,
        "prereqs": [],
        "description": "Enables Research Lab",
    },
    "advanced_computers": {
        "id": "advanced_computers",
        "name": "Advanced Computers",
        "field": "computers",
        "tier": 2,
        "cost": 200,
        "prereqs": ["computer_science"],
        "description": "Enables Supercomputer",
    },
    "galactic_networks": {
        "id": "galactic_networks",
        "name": "Galactic Networks",
        "field": "computers",
        "tier": 3,
        "cost": 400,
        "prereqs": ["advanced_computers"],
        "description": "Enables Galactic Cybernet",
    },

    # ---- Biology -----------------------------------------------------------
    "agriculture": {
        "id": "agriculture",
        "name": "Agriculture",
        "field": "biology",
        "tier": 1,
        "cost": 80,
        "prereqs": [],
        "description": "Enables Hydroponics",
    },
    "soil_enrichment": {
        "id": "soil_enrichment",
        "name": "Soil Enrichment",
        "field": "biology",
        "tier": 2,
        "cost": 150,
        "prereqs": ["agriculture"],
        "description": "Enables Soil Enrichment",
    },
    "cloning": {
        "id": "cloning",
        "name": "Cloning",
        "field": "biology",
        "tier": 3,
        "cost": 300,
        "prereqs": ["soil_enrichment"],
        "description": "Enables Cloning Center",
    },
}

# Convenience: techs grouped by field, sorted by tier.
def techs_in_field(field: str) -> list[dict]:
    return sorted(
        (t for t in TECHS.values() if t.get("field") == field),
        key=lambda t: t.get("tier", 0),
    )

# Order used by the Info-panel research list and the Research scene's
# "next available" hint.
TECH_ORDER = [
    "industrial_engineering", "nuclear_drives", "trade", "computer_science", "agriculture",
    "advanced_construction", "fusion_drives", "governance", "advanced_computers", "soil_enrichment",
    "automated_factories", "ion_drives", "financial_planning", "galactic_networks", "cloning",
    "anti_matter_drives", "hyper_drives",
]


def is_available(tech_id: str, unlocked: set[str] | list) -> bool:
    if tech_id not in TECHS:
        return False
    if tech_id in unlocked:
        return False
    unlocked_set = set(unlocked)
    return all(p in unlocked_set for p in TECHS[tech_id]["prereqs"])


def empire_speed_bonus(unlocked: set[str] | list) -> int:
    """Best drive tech contributes this. Max across all unlocked drive
    techs (not additive — Fusion replaces Nuclear, etc.)."""
    unlocked_set = set(unlocked)
    best = 0
    for tech_id, spec in TECHS.items():
        if tech_id in unlocked_set:
            best = max(best, spec.get("speed_bonus", 0))
    return best

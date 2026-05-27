"""Empire-level tech tree, organised MOO2-style by field and tier.

Six fields are represented:

- **Construction** — heavy industry, factories, robo-miners
- **Power** — ship drives (Nuclear → Fusion → Ion → Anti-Matter → Hyper)
- **Sociology** — trade, government, finance, virtual networks
- **Computers** — research throughput, networks, positronic brains
- **Biology** — farming, growth, cloning, terraforming
- **Physics** — ship weapons (Laser → Phasor → Plasma) + scanners

Each tech carries:

- ``field``: which column it occupies in the Research scene.
- ``tier``: row 1..N; higher tiers cost more and have prereqs.
- ``cost``: research points to unlock.
- ``prereqs``: tech ids that must already be unlocked.
- ``description``: brief summary shown in tooltips / panels.
- optional ``speed_bonus``: drive techs contribute this to the
  empire's ship speed (MAX across unlocked, not additive — Fusion
  replaces Nuclear, etc.).
- optional ``attack_bonus`` / ``hull_bonus``: weapon and scanner
  techs contribute these to every ship in combat. Also MAX across
  unlocked so progression matters.

Research from production_tick routes to TechState.current_target; on
completion the tech moves to ``unlocked`` and gates new projects via
projects.required_tech.
"""
from __future__ import annotations


# Fields the catalog covers (order = display order in Research scene).
FIELDS = ["construction", "power", "sociology", "computers", "biology", "physics", "espionage"]

FIELD_NAMES = {
    "construction": "Construction",
    "power":        "Power",
    "sociology":    "Sociology",
    "computers":    "Computers",
    "biology":      "Biology",
    "physics":      "Physics",
    "espionage":    "Espionage",
}

# Display colours per field; used by the Research scene to tint columns.
FIELD_COLORS = {
    "construction": (210, 150, 80),
    "power":        (230, 200, 80),
    "sociology":    (160, 220, 140),
    "computers":    (140, 180, 230),
    "biology":      (150, 220, 180),
    "physics":      (220, 140, 220),
    "espionage":    (200, 110, 130),
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
    "robo_miners": {
        "id": "robo_miners",
        "name": "Robo-Miners",
        "field": "construction",
        "tier": 4,
        "cost": 700,
        "prereqs": ["automated_factories"],
        "description": "Enables Deep Core Mine",
    },

    # ---- Power (drives) ----------------------------------------------------
    "nuclear_drives": {
        "id": "nuclear_drives",
        "name": "Nuclear Drives",
        "field": "power",
        "tier": 1,
        "cost": 100,
        "prereqs": [],
        "description": "+1 speed, 9 parsec fuel range",
        "speed_bonus": 1,
        "fuel_range": 9,
    },
    "fusion_drives": {
        "id": "fusion_drives",
        "name": "Fusion Drives",
        "field": "power",
        "tier": 2,
        "cost": 200,
        "prereqs": ["nuclear_drives"],
        "description": "+2 speed, 12 parsec fuel range",
        "speed_bonus": 2,
        "fuel_range": 12,
    },
    "ion_drives": {
        "id": "ion_drives",
        "name": "Ion Drives",
        "field": "power",
        "tier": 3,
        "cost": 350,
        "prereqs": ["fusion_drives"],
        "description": "+3 speed, 16 parsec fuel range",
        "speed_bonus": 3,
        "fuel_range": 16,
    },
    "anti_matter_drives": {
        "id": "anti_matter_drives",
        "name": "Anti-Matter Drives",
        "field": "power",
        "tier": 4,
        "cost": 500,
        "prereqs": ["ion_drives"],
        "description": "+4 speed, 20 parsec fuel range",
        "speed_bonus": 4,
        "fuel_range": 20,
    },
    "hyper_drives": {
        "id": "hyper_drives",
        "name": "Hyper Drives",
        "field": "power",
        "tier": 5,
        "cost": 800,
        "prereqs": ["anti_matter_drives"],
        "description": "+6 speed, 28 parsec fuel range",
        "speed_bonus": 6,
        "fuel_range": 28,
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
    "virtual_reality_network": {
        "id": "virtual_reality_network",
        "name": "Virtual Reality Network",
        "field": "sociology",
        "tier": 4,
        "cost": 500,
        "prereqs": ["financial_planning"],
        "description": "Enables VR Network",
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
    "positronic_computers": {
        "id": "positronic_computers",
        "name": "Positronic Computers",
        "field": "computers",
        "tier": 4,
        "cost": 700,
        "prereqs": ["galactic_networks"],
        "description": "Enables Positronic Brain",
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
    "terraforming": {
        "id": "terraforming",
        "name": "Terraforming",
        "field": "biology",
        "tier": 4,
        "cost": 600,
        "prereqs": ["cloning"],
        "description": "Enables Terraforming",
    },

    # ---- Physics (ship weapons + scanners) ---------------------------------
    "laser_cannons": {
        "id": "laser_cannons",
        "name": "Laser Cannons",
        "field": "physics",
        "tier": 1,
        "cost": 100,
        "prereqs": [],
        "description": "Ships gain +1 attack",
        "attack_bonus": 1,
    },
    "phasors": {
        "id": "phasors",
        "name": "Phasors",
        "field": "physics",
        "tier": 2,
        "cost": 250,
        "prereqs": ["laser_cannons"],
        "description": "Ships gain +2 attack (replaces Laser)",
        "attack_bonus": 2,
    },
    "tachyon_scanner": {
        "id": "tachyon_scanner",
        "name": "Tachyon Scanner",
        "field": "physics",
        "tier": 3,
        "cost": 400,
        "prereqs": ["phasors"],
        "description": "+1 hull, long-range fleet detection",
        "hull_bonus": 1,
        "sensor_range": 16,
    },
    "plasma_cannons": {
        "id": "plasma_cannons",
        "name": "Plasma Cannons",
        "field": "physics",
        "tier": 4,
        "cost": 600,
        "prereqs": ["tachyon_scanner"],
        "description": "Ships gain +3 attack, +1 hull",
        "attack_bonus": 3,
        "hull_bonus": 1,
    },

    # ---- Espionage (spies + counter-intelligence) --------------------------
    "spy_network": {
        "id": "spy_network",
        "name": "Spy Network",
        "field": "espionage",
        "tier": 1,
        "cost": 120,
        "prereqs": [],
        "description": "+1 spy skill & security",
        "spy_offense": 1,
        "spy_defense": 1,
    },
    "stealth_suit": {
        "id": "stealth_suit",
        "name": "Stealth Suit",
        "field": "espionage",
        "tier": 2,
        "cost": 280,
        "prereqs": ["spy_network"],
        "description": "+2 spy skill; caught spies rarely identified",
        "spy_offense": 2,
        "stealth": True,
    },
    "mind_scan": {
        "id": "mind_scan",
        "name": "Mind Scan",
        "field": "espionage",
        "tier": 3,
        "cost": 420,
        "prereqs": ["spy_network"],
        "description": "+3 security; always unmask caught spies",
        "spy_defense": 3,
        "mind_scan": True,
    },
    "neural_scrambler": {
        "id": "neural_scrambler",
        "name": "Neural Scrambler",
        "field": "espionage",
        "tier": 4,
        "cost": 640,
        "prereqs": ["stealth_suit", "mind_scan"],
        "description": "+3 spy skill & security",
        "spy_offense": 3,
        "spy_defense": 3,
    },
}

# Convenience: techs grouped by field, sorted by tier.
def techs_in_field(field: str) -> list[dict]:
    return sorted(
        (t for t in TECHS.values() if t.get("field") == field),
        key=lambda t: t.get("tier", 0),
    )

# Order used by the Info-panel research list and the Research scene's
# "next available" hint. Tier 1s first, then 2s, then 3s, etc., so the
# panel surfaces a sensible "next research" suggestion.
TECH_ORDER = [
    # Tier 1
    "industrial_engineering", "nuclear_drives", "trade", "computer_science",
    "agriculture", "laser_cannons", "spy_network",
    # Tier 2
    "advanced_construction", "fusion_drives", "governance", "advanced_computers",
    "soil_enrichment", "phasors", "stealth_suit",
    # Tier 3
    "automated_factories", "ion_drives", "financial_planning", "galactic_networks",
    "cloning", "tachyon_scanner", "mind_scan",
    # Tier 4
    "robo_miners", "anti_matter_drives", "virtual_reality_network",
    "positronic_computers", "terraforming", "plasma_cannons", "neural_scrambler",
    # Tier 5 (only Power goes this deep)
    "hyper_drives",
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


# Fuel range (in parsecs) with no drive tech at all. Every empire can
# operate this far from a friendly supply system from turn 1.
BASE_FUEL_RANGE = 6


def empire_fuel_range(unlocked: set[str] | list) -> int:
    """Best drive tech's fuel range, falling back to BASE_FUEL_RANGE.
    Like speed, drives replace each other (max, not sum)."""
    unlocked_set = set(unlocked)
    best = BASE_FUEL_RANGE
    for tech_id, spec in TECHS.items():
        if tech_id in unlocked_set:
            best = max(best, spec.get("fuel_range", 0))
    return best


# Sensor range (parsecs) with no scanner tech — colonies + ships detect
# enemy fleets passing this close. Scanner techs (Tachyon Scanner) push
# it far out so you see incoming attacks earlier.
BASE_SENSOR_RANGE = 6


def empire_sensor_range(unlocked: set[str] | list) -> int:
    unlocked_set = set(unlocked)
    best = BASE_SENSOR_RANGE
    for tech_id, spec in TECHS.items():
        if tech_id in unlocked_set:
            best = max(best, spec.get("sensor_range", 0))
    return best


def empire_attack_bonus(unlocked: set[str] | list) -> int:
    """Best weapon tech contributes this. Max (not sum) — Phasor
    replaces Laser, etc."""
    unlocked_set = set(unlocked)
    best = 0
    for tech_id, spec in TECHS.items():
        if tech_id in unlocked_set:
            best = max(best, spec.get("attack_bonus", 0))
    return best


def empire_hull_bonus(unlocked: set[str] | list) -> int:
    """Best hull/scanner tech contributes this. Max across unlocked."""
    unlocked_set = set(unlocked)
    best = 0
    for tech_id, spec in TECHS.items():
        if tech_id in unlocked_set:
            best = max(best, spec.get("hull_bonus", 0))
    return best


def empire_spy_offense(unlocked: set[str] | list) -> int:
    """Best espionage tech contributes this to offensive spy skill."""
    unlocked_set = set(unlocked)
    best = 0
    for tech_id, spec in TECHS.items():
        if tech_id in unlocked_set:
            best = max(best, spec.get("spy_offense", 0))
    return best


def empire_spy_defense(unlocked: set[str] | list) -> int:
    """Best espionage tech contributes this to internal security."""
    unlocked_set = set(unlocked)
    best = 0
    for tech_id, spec in TECHS.items():
        if tech_id in unlocked_set:
            best = max(best, spec.get("spy_defense", 0))
    return best


def empire_has_stealth(unlocked: set[str] | list) -> bool:
    """Stealth Suit: caught offensive spies are rarely identified."""
    return any(TECHS.get(t, {}).get("stealth") for t in unlocked)


def empire_has_mind_scan(unlocked: set[str] | list) -> bool:
    """Mind Scan: caught enemy spies are always unmasked (defeats stealth)."""
    return any(TECHS.get(t, {}).get("mind_scan") for t in unlocked)

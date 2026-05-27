"""AI empire personalities.

Each personality biases the AI loop's decisions:

- ``worker_pct``: percentage (0-100) of non-farmer pop assigned to workers;
  the rest become scientists. Higher = more industry/BC, less research.
- ``build_priority``: ordered list of project ids the AI prefers to queue.
- ``research_priority``: ordered list of tech ids the AI targets in order.

Players use "balanced", but human players don't run AI logic anyway —
the catalog is keyed for diagnostic display.
"""
from __future__ import annotations


PERSONALITIES: dict[str, dict] = {
    "balanced": {
        "name": "Balanced",
        "description": "Even mix of growth, science, and economy.",
        "worker_pct": 75,
        "colonization_focus": "balanced",
        "build_priority": [
            "factory", "granary", "research_lab", "marketplace",
            "ship_colony_ship",  # expand once basic infra is up
            "hydroponics", "capital", "supercomputer", "stock_exchange",
            "atmospheric_renewer", "ship_frigate", "ship_cruiser",
            # Defensive tail — built when the economy outpaces other
            # priorities, hardening colonies against invasion.
            "missile_base", "ground_batteries", "star_base", "battlestation",
        ],
        "research_priority": [
            "agriculture", "trade", "computer_science", "industrial_engineering",
            "governance", "advanced_construction", "advanced_computers",
            "nuclear_drives", "soil_enrichment", "financial_planning",
            "fusion_drives", "automated_factories", "galactic_networks", "cloning",
        ],
        "aggressive": False,
    },
    "economic": {
        "name": "Economic",
        "description": "Markets and growth first; aggressive expansion.",
        "worker_pct": 70,
        "colonization_focus": "economy",
        "build_priority": [
            "granary", "marketplace", "factory",
            "ship_colony_ship",  # spread wide for more revenue
            "hydroponics", "stock_exchange", "research_lab", "capital",
            "atmospheric_renewer", "soil_enrichment_b",
            "cloning_center", "automated_factory",
            "missile_base", "ground_batteries", "star_base",
        ],
        "research_priority": [
            "trade", "agriculture", "governance", "industrial_engineering",
            "financial_planning", "soil_enrichment", "advanced_construction",
            "cloning", "computer_science", "automated_factories",
        ],
        "aggressive": False,
    },
    "scientific": {
        "name": "Scientific",
        "description": "Researches aggressively; light defensive fleet.",
        "worker_pct": 40,
        "colonization_focus": "science",
        "build_priority": [
            "research_lab", "supercomputer", "factory", "granary",
            "ship_colony_ship",  # more colonies = more scientists
            "marketplace", "galactic_cybernet", "hydroponics", "capital",
            "ship_frigate",
            "missile_base", "ground_batteries", "star_base", "battlestation",
        ],
        "research_priority": [
            "computer_science", "advanced_computers", "agriculture",
            "industrial_engineering", "galactic_networks", "trade",
            "advanced_construction", "soil_enrichment", "governance",
            "nuclear_drives", "fusion_drives",
        ],
        "aggressive": False,
    },
    "militaristic": {
        "name": "Militaristic",
        "description": "Heavy fleet, attacks the player on sight.",
        "worker_pct": 90,
        "colonization_focus": "industry",
        "build_priority": [
            "factory", "ship_frigate",
            "ship_colony_ship",  # secure border worlds before fighting
            "automated_factory", "research_lab", "ship_cruiser",
            "ship_troop_transport",  # invade enemy worlds
            "marketplace", "ship_battleship", "hydroponics",
            "ship_dreadnought", "granary", "capital",
            # Fortify conquered worlds.
            "missile_base", "ground_batteries", "star_base",
            "battlestation", "star_fortress",
        ],
        "research_priority": [
            "industrial_engineering", "nuclear_drives", "trade", "fusion_drives",
            "advanced_construction", "ion_drives", "governance",
            "automated_factories", "anti_matter_drives", "computer_science",
            "agriculture", "hyper_drives",
        ],
        "aggressive": True,
    },
}

# Order AI empires cycle through when more than one needs a personality.
# The first slot is intentionally not "balanced" — AI variety is the goal.
AI_PERSONALITY_CYCLE = ["economic", "scientific", "militaristic", "balanced"]

DEFAULT_PERSONALITY = "balanced"


def get(personality: str) -> dict:
    return PERSONALITIES.get(personality, PERSONALITIES[DEFAULT_PERSONALITY])

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
        "build_priority": [
            "factory", "granary", "research_lab", "marketplace", "hydroponics",
            "capital", "ship_frigate", "ship_cruiser",
        ],
        "research_priority": ["agriculture", "trade", "computer_science", "industrial_engineering", "governance"],
        "aggressive": False,
    },
    "economic": {
        "name": "Economic",
        "description": "Markets and growth first; no fleet building.",
        "worker_pct": 70,
        "build_priority": ["granary", "marketplace", "factory", "hydroponics", "research_lab", "capital"],
        "research_priority": ["trade", "agriculture", "computer_science", "industrial_engineering", "governance"],
        "aggressive": False,
    },
    "scientific": {
        "name": "Scientific",
        "description": "Researches aggressively; light defensive fleet.",
        "worker_pct": 40,
        "build_priority": [
            "research_lab", "factory", "granary", "marketplace", "hydroponics",
            "capital", "ship_frigate",
        ],
        "research_priority": ["computer_science", "agriculture", "industrial_engineering", "trade", "governance"],
        "aggressive": False,
    },
    "militaristic": {
        "name": "Militaristic",
        "description": "Heavy fleet, attacks the player on sight.",
        "worker_pct": 90,
        "build_priority": [
            "factory", "ship_frigate", "research_lab", "ship_cruiser",
            "marketplace", "ship_battleship", "hydroponics", "ship_dreadnought",
            "granary", "capital",
        ],
        "research_priority": ["industrial_engineering", "trade", "governance", "computer_science", "agriculture"],
        "aggressive": True,
    },
}

# Order AI empires cycle through when more than one needs a personality.
# The first slot is intentionally not "balanced" — AI variety is the goal.
AI_PERSONALITY_CYCLE = ["economic", "scientific", "militaristic", "balanced"]

DEFAULT_PERSONALITY = "balanced"


def get(personality: str) -> dict:
    return PERSONALITIES.get(personality, PERSONALITIES[DEFAULT_PERSONALITY])

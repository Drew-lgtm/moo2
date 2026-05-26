"""Galaxy age setting (Young / Average / Old) — biases generation.

MOO2-style flavour:

- **Young**: recently formed. Lots of geologically active rocks — more
  Volcanic/Inferno/Asteroids, more Rich/Ultra Rich mineral richness,
  fewer mature fertile worlds. Minerals everywhere, food scarce.
- **Average**: balanced baseline (the current default weights).
- **Old**: long-stable galaxy. Life has had time to develop; ore beds
  have been mined or settled. More Terran/Ocean/Swamp/Jungle, fewer
  Volcanic/Inferno, mineral richness skews toward Poor / Ultra Poor.

Gaia is gated separately: its spawn weight stays low regardless of age,
because Gaia is supposed to feel like a lottery ticket.

The actual generation passes the age string to ``planet_type_weights``,
``richness_weights_habitable``, and ``richness_weights_mining`` —
``galaxy_generator`` calls these instead of using the raw module-level
tables.
"""
from __future__ import annotations

from ecs.planet_features import (
    RICHNESS_WEIGHTS_HABITABLE, RICHNESS_WEIGHTS_MINING,
)


AGES = ("young", "average", "old")
DEFAULT_AGE = "average"


# Base planet-type weights for the average galaxy. Galaxy_generator
# applies age multipliers on top.
BASE_TYPE_WEIGHTS = {
    "Terran": 0.09, "Ocean": 0.08, "Swamp": 0.06, "Jungle": 0.07,
    "Arid": 0.08, "Desert": 0.07, "Tundra": 0.07, "Steppe": 0.06,
    "Barren": 0.04, "Gaia": 0.01,
    "Radiated": 0.05, "Toxic": 0.05, "Inferno": 0.03, "Volcanic": 0.03,
    "Asteroids": 0.06, "Gas Giant": 0.07,
}

# Per-age modifier per planet type. 1.0 = unchanged. Gaia is pinned to
# 1.0 in every age so it stays equally rare.
AGE_TYPE_MULTIPLIERS = {
    "young": {
        "Terran": 0.6, "Ocean": 0.6, "Swamp": 0.7, "Jungle": 0.7,
        "Arid": 1.0, "Desert": 1.2, "Tundra": 0.9, "Steppe": 0.8,
        "Barren": 1.3, "Gaia": 1.0,
        "Radiated": 1.4, "Toxic": 1.3, "Inferno": 1.8, "Volcanic": 1.8,
        "Asteroids": 1.6, "Gas Giant": 1.2,
    },
    "average": {t: 1.0 for t in BASE_TYPE_WEIGHTS},
    "old": {
        "Terran": 1.5, "Ocean": 1.5, "Swamp": 1.4, "Jungle": 1.4,
        "Arid": 1.1, "Desert": 0.8, "Tundra": 1.0, "Steppe": 1.2,
        "Barren": 0.7, "Gaia": 1.0,
        "Radiated": 0.6, "Toxic": 0.6, "Inferno": 0.4, "Volcanic": 0.4,
        "Asteroids": 0.7, "Gas Giant": 0.9,
    },
}


# Mineral richness shifts. Young galaxies have lots of high-grade ore;
# old galaxies have been picked over.
AGE_RICHNESS_HABITABLE = {
    "young": {
        "Ultra Poor": 0.04, "Poor": 0.16, "Abundant": 0.38,
        "Rich": 0.28, "Ultra Rich": 0.14,
    },
    "average": dict(RICHNESS_WEIGHTS_HABITABLE),
    "old": {
        "Ultra Poor": 0.14, "Poor": 0.30, "Abundant": 0.38,
        "Rich": 0.14, "Ultra Rich": 0.04,
    },
}

AGE_RICHNESS_MINING = {
    "young": {
        "Ultra Poor": 0.03, "Poor": 0.08, "Abundant": 0.24,
        "Rich": 0.35, "Ultra Rich": 0.30,
    },
    "average": dict(RICHNESS_WEIGHTS_MINING),
    "old": {
        "Ultra Poor": 0.10, "Poor": 0.25, "Abundant": 0.35,
        "Rich": 0.22, "Ultra Rich": 0.08,
    },
}


def normalize_age(age: str | None) -> str:
    a = (age or DEFAULT_AGE).lower()
    return a if a in AGES else DEFAULT_AGE


def planet_type_weights(age: str) -> dict[str, float]:
    """Return planet-type weights for ``age``. Unnormalised — caller can
    feed straight into ``random.choices`` (it normalises internally)."""
    age = normalize_age(age)
    mult = AGE_TYPE_MULTIPLIERS[age]
    return {t: BASE_TYPE_WEIGHTS[t] * mult.get(t, 1.0) for t in BASE_TYPE_WEIGHTS}


def richness_weights_habitable(age: str) -> dict[str, float]:
    return dict(AGE_RICHNESS_HABITABLE[normalize_age(age)])


def richness_weights_mining(age: str) -> dict[str, float]:
    return dict(AGE_RICHNESS_MINING[normalize_age(age)])

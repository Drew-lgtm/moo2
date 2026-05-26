"""Planet richness / gravity / special-feature catalog (MOO2-style).

These descriptors live on the Planet component and are applied during
``ecs.economy.planet_output``. Generation lives in
``ecs.galaxy_generator`` so creation logic stays in one place.

Effects summary:

- ``RICHNESS_INDUSTRY_MULT`` — multiplies worker industry output. Asteroid
  belts and barren worlds skew toward the extremes; habitable worlds
  cluster around Abundant. This is MOO2's biggest industrial dial.
- ``GRAVITY_OUTPUT_MULT`` — multiplies all per-pop output (food, industry,
  research). MOO2 lets races buy off this penalty with "Low Grav Home" or
  "Heavy Grav Home" traits; we don't model adaptation yet so the penalty
  is flat.
- ``SPECIAL_FEATURES`` — flat per-turn add to the matching stat. Rare
  (~10% of planets get one); deposit features stack into BC, artifacts
  contribute research.
"""
from __future__ import annotations

import random


# ---- richness ---------------------------------------------------------

RICHNESS_LEVELS = [
    "Ultra Poor", "Poor", "Abundant", "Rich", "Ultra Rich",
]

RICHNESS_INDUSTRY_MULT = {
    "Ultra Poor": 0.5,
    "Poor":       0.75,
    "Abundant":   1.0,
    "Rich":       1.5,
    "Ultra Rich": 2.0,
}

# Generation weights for habitable planets — bell-shaped around Abundant.
RICHNESS_WEIGHTS_HABITABLE = {
    "Ultra Poor": 0.08,
    "Poor":       0.22,
    "Abundant":   0.40,
    "Rich":       0.22,
    "Ultra Rich": 0.08,
}

# Asteroid belts and barren rocks are why anyone wants asteroid belts —
# bias them noticeably richer.
RICHNESS_WEIGHTS_MINING = {
    "Ultra Poor": 0.05,
    "Poor":       0.15,
    "Abundant":   0.30,
    "Rich":       0.30,
    "Ultra Rich": 0.20,
}


# ---- gravity ----------------------------------------------------------

GRAVITY_LEVELS = ["Low", "Normal", "Heavy"]

GRAVITY_OUTPUT_MULT = {
    "Low":    0.75,
    "Normal": 1.0,
    "Heavy":  0.5,
}

# Gravity scales with planet size — Tiny/Small skew low-g, Huge skews
# heavy-g. Normal is the default for Medium/Large.
GRAVITY_WEIGHTS_BY_SIZE = {
    "Tiny":   {"Low": 0.70, "Normal": 0.28, "Heavy": 0.02},
    "Small":  {"Low": 0.45, "Normal": 0.50, "Heavy": 0.05},
    "Medium": {"Low": 0.15, "Normal": 0.70, "Heavy": 0.15},
    "Large":  {"Low": 0.05, "Normal": 0.55, "Heavy": 0.40},
    "Huge":   {"Low": 0.02, "Normal": 0.28, "Heavy": 0.70},
}


# ---- special features -------------------------------------------------

# Each feature stacks at most once per planet. Effects are flat per-turn
# adds applied in planet_output; researchers/workers don't have to be
# assigned for them to fire.
SPECIAL_FEATURES = {
    "artifacts":     {"name": "Artifacts",     "research": 5,
                      "desc": "Ancient ruins yield +5 research per turn."},
    "gem_deposits":  {"name": "Gem Deposits",  "bc": 5,
                      "desc": "Glittering veins generate +5 BC per turn."},
    "gold_veins":    {"name": "Gold Veins",    "bc": 10,
                      "desc": "Massive deposits generate +10 BC per turn."},
}

# How often a planet gets *any* feature, and the per-feature weights when
# it does. Tuned so artifacts are the rarest and gem deposits the most
# common — gold veins sit in between as a juicy mid-game grab.
SPECIAL_FEATURE_CHANCE = 0.12
SPECIAL_FEATURE_WEIGHTS = {
    "gem_deposits": 0.55,
    "gold_veins":   0.30,
    "artifacts":    0.15,
}


# ---- helpers ----------------------------------------------------------

def _weighted_pick(weights: dict, rng: random.Random | None = None) -> str:
    r = rng or random
    keys = list(weights.keys())
    vals = list(weights.values())
    return r.choices(keys, weights=vals, k=1)[0]


MINING_TYPES = {"Asteroids", "Gas Giant", "Barren", "Radiated", "Volcanic"}


def random_richness(planet_type: str, rng: random.Random | None = None,
                    weights_habitable: dict | None = None,
                    weights_mining: dict | None = None) -> str:
    """Asteroids / gas giants / barren / radiated lean toward Rich; the
    rest follow the habitable bell curve. Callers (e.g.
    galaxy_generator) pass age-modified tables; defaults are the average
    galaxy curves above."""
    if planet_type in MINING_TYPES:
        table = weights_mining if weights_mining is not None else RICHNESS_WEIGHTS_MINING
    else:
        table = weights_habitable if weights_habitable is not None else RICHNESS_WEIGHTS_HABITABLE
    return _weighted_pick(table, rng)


def random_gravity(size: str, rng: random.Random | None = None) -> str:
    table = GRAVITY_WEIGHTS_BY_SIZE.get(size, GRAVITY_WEIGHTS_BY_SIZE["Medium"])
    return _weighted_pick(table, rng)


def maybe_special_feature(rng: random.Random | None = None) -> str | None:
    r = rng or random
    if r.random() >= SPECIAL_FEATURE_CHANCE:
        return None
    return _weighted_pick(SPECIAL_FEATURE_WEIGHTS, rng)


def parse_specials(blob: str) -> list[str]:
    if not blob:
        return []
    return [s for s in blob.split(",") if s]


def specials_to_blob(specials) -> str:
    return ",".join(specials) if specials else ""


def feature_bonuses(specials) -> tuple[int, int]:
    """Sum (research, bc) across the special features on a planet."""
    research = bc = 0
    for key in specials:
        meta = SPECIAL_FEATURES.get(key)
        if meta is None:
            continue
        research += meta.get("research", 0)
        bc += meta.get("bc", 0)
    return research, bc

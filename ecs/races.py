"""Race catalog and racial trait definitions.

A race is a small dict with:
- ``name``: display name
- ``traits``: list of trait keys (duplicates count — Psilon has
  research_bonus twice for +2 research per scientist).
- ``description``: one-line flavour for the empire setup screen.

Custom races skip the preset list entirely: the empire setup screen
offers a point-buy budget of CUSTOM_POINTS_BUDGET (10) and the player
picks any combination of traits whose costs sum to <= the budget.

Trait effects are applied:
- in ``economy.planet_output()`` for per-pop / per-build bonuses
- in ``economy.pop_growth_tick()`` for growth-rate + food modifiers
- in ``combat.combat_tick()`` (TODO) for ship attack / hull bonuses
"""
from __future__ import annotations


# Trait catalog. Costs are points: positive = pick costs points,
# negative = pick refunds points (so "Slow Growth" gives you 3
# back to spend on something else).
TRAITS: dict[str, dict] = {
    "food_bonus":     {"name": "+1 Food / Farmer",     "cost":  4, "desc": "Each farmer produces +1 food."},
    "industry_bonus": {"name": "+1 Industry / Worker", "cost":  4, "desc": "Each worker produces +1 industry."},
    "research_bonus": {"name": "+1 Research / Scientist", "cost": 4, "desc": "Each scientist produces +1 research."},
    "bc_bonus":       {"name": "+1 BC / Worker",        "cost":  3, "desc": "Each worker produces +1 BC."},
    "fast_growth":    {"name": "Fast Growth",           "cost":  4, "desc": "+0.2 to logistic growth rate."},
    "slow_growth":    {"name": "Slow Growth",           "cost": -3, "desc": "-0.2 to logistic growth rate."},
    "weak_industry":  {"name": "Weak Industry",         "cost": -3, "desc": "Each worker produces -1 industry (min 0)."},
    "tolerant":       {"name": "Tolerant",              "cost":  6, "desc": "Pop consumes only 0.5 food each."},
    "ship_attack":    {"name": "+1 Ship Attack",        "cost":  3, "desc": "All ships gain +1 attack power."},
    "ship_hull":      {"name": "+2 Ship Hull",          "cost":  3, "desc": "All ships gain +2 hull."},
    "warlord":        {"name": "Warlord",               "cost":  4,
                       "desc": "+1 ground attack per marine and +1 defense per militia."},
    "pacifist":       {"name": "Pacifist",              "cost": -2,
                       "desc": "-1 ground attack per marine. Defense unaffected."},
    "hive_mind":      {"name": "Hive Mind",             "cost":  6,
                       "desc": "+1 industry per worker. +2 spy defense — "
                               "the collective notices intruders. "
                               "Cannot use Pleasure Dome."},
    "mind_link":      {"name": "Mind Link",             "cost":  5,
                       "desc": "+1 research per scientist. +1 spy defense — "
                               "telepathic collective. Cannot use Pleasure Dome."},
    "spymaster":      {"name": "Spymaster",             "cost":  4,
                       "desc": "+1 spy offense and +1 spy defense per pick."},
    "defiant":        {"name": "Defiant",               "cost":  3,
                       "desc": "Slow to assimilate under foreign rule. Can "
                               "revolt or wage guerrilla war against weak "
                               "garrisons."},
    "rich_homeworld": {"name": "Rich Homeworld",        "cost":  3, "desc": "Homeworld starts with +50 BC."},
    "subterranean":   {"name": "Subterranean",          "cost":  6, "desc": "Every colony gets +2 max pop."},
}

# Order shown in trait picker.
TRAIT_ORDER = [
    "food_bonus", "industry_bonus", "research_bonus", "bc_bonus",
    "fast_growth", "tolerant",
    "ship_attack", "ship_hull", "warlord", "hive_mind", "mind_link",
    "spymaster", "defiant",
    "rich_homeworld", "subterranean",
    "slow_growth", "weak_industry", "pacifist",
]


# 15 races, broadly matching MOO2 lore where it lines up with traits we
# actually implement. Cosmetic descriptions are short; traits do the
# heavy lifting.
RACES: dict[str, dict] = {
    "Humans":    {"name": "Humans",    "traits": ["bc_bonus", "research_bonus"],
                  "description": "Charismatic traders."},
    "Alkari":    {"name": "Alkari",    "traits": ["ship_attack", "ship_hull"],
                  "description": "Sky-born warriors."},
    "Bulrathi":  {"name": "Bulrathi",  "traits": ["warlord", "industry_bonus", "defiant", "slow_growth"],
                  "description": "Massive ursinoids — devastating in ground combat, prodigious workers, will not bow."},
    "Darlok":    {"name": "Darlok",    "traits": ["spymaster", "spymaster", "slow_growth"],
                  "description": "Shapeshifter spies — masters of infiltration and counter-intel."},
    "Elerian":   {"name": "Elerian",   "traits": ["mind_link", "ship_attack"],
                  "description": "Telepathic scholars — linked minds and skilled gunners."},
    "Gnolam":    {"name": "Gnolam",    "traits": ["bc_bonus", "bc_bonus", "rich_homeworld"],
                  "description": "Lucky merchants."},
    "Klackon":   {"name": "Klackon",   "traits": ["hive_mind", "food_bonus"],
                  "description": "Hive-mind insectoids — relentless workers, hard to infiltrate."},
    "Meklar":    {"name": "Meklar",    "traits": ["industry_bonus", "industry_bonus"],
                  "description": "Cybernetic industrial machine."},
    "Mrrshan":   {"name": "Mrrshan",   "traits": ["ship_attack", "warlord", "defiant"],
                  "description": "Feline warriors — proud, fierce, will not be tamed."},
    "Psilon":    {"name": "Psilon",    "traits": ["mind_link", "research_bonus", "pacifist"],
                  "description": "Genius scientists with linked minds — but lousy soldiers."},
    "Sakkra":    {"name": "Sakkra",    "traits": ["fast_growth", "food_bonus"],
                  "description": "Reptilian breeders."},
    "Silicoid":  {"name": "Silicoid",  "traits": ["tolerant", "industry_bonus", "slow_growth"],
                  "description": "Crystalline life — no food needed, untiring workers."},
    "Trilarian": {"name": "Trilarian", "traits": ["food_bonus", "ship_attack", "defiant"],
                  "description": "Aquatic warriors — never accept landed rule."},
    "Raas":      {"name": "Raas",      "traits": ["fast_growth", "fast_growth", "weak_industry"],
                  "description": "Hardy nomads — breed twice as fast, but indifferent labourers."},
    "Nommo":     {"name": "Nommo",     "traits": ["research_bonus", "bc_bonus"],
                  "description": "Mystical merfolk."},
}

RACE_ORDER = list(RACES.keys())

CUSTOM_RACE_NAME = "Custom"
CUSTOM_POINTS_BUDGET = 10


def race_traits(race_name: str) -> list[str]:
    race = RACES.get(race_name)
    return list(race["traits"]) if race else []


def effective_traits(race_type: str, custom_traits: str) -> list[str]:
    """Return the trait list for an empire: preset race's traits OR
    parsed custom_traits string when race_type == CUSTOM_RACE_NAME."""
    if race_type == CUSTOM_RACE_NAME and custom_traits:
        return [t for t in custom_traits.split(",") if t]
    return race_traits(race_type)


def trait_cost_total(traits) -> int:
    return sum(TRAITS.get(t, {}).get("cost", 0) for t in traits)


def trait_count(traits, key: str) -> int:
    return sum(1 for t in traits if t == key)


def traits_for_empire(component_mgr, empire_id: int) -> list[str]:
    """Resolve an empire entity's effective trait list. Used by economy
    ticks that already have an empire_id in hand."""
    # Lazy import: races.py must not depend on components.py at module
    # load (it's imported very early during scene setup).
    from ecs.components import Empire
    for _eid, emp in component_mgr.get_all(Empire):
        if emp.id == empire_id:
            return effective_traits(emp.race_type, emp.custom_traits)
    return []

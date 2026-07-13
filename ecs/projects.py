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
        "id": "factory", "name": "Factory", "category": "economy",
        "cost": 60, "description": "+2 BC per turn",
        "effects": {"bc": 2},
    },
    "granary": {
        "id": "granary", "name": "Granary", "category": "farming",
        "cost": 60, "description": "Population grows faster",
        "effects": {"growth_rate": 0.2},
    },
    "research_lab": {
        "id": "research_lab", "name": "Research Lab", "category": "science",
        "cost": 60, "description": "+3 Research per turn",
        "effects": {"research": 3},
        "required_tech": "computer_science",
    },
    "hydroponics": {
        "id": "hydroponics", "name": "Hydroponics", "category": "farming",
        "cost": 80, "description": "+2 max population",
        "effects": {"max_pop": 2},
        "required_tech": "agriculture",
    },
    "marketplace": {
        "id": "marketplace", "name": "Marketplace", "category": "economy",
        "cost": 80, "description": "+3 BC, faster growth",
        "effects": {"bc": 3, "growth_rate": 0.1},
        "required_tech": "trade",
    },
    "capital": {
        "id": "capital", "name": "Capital", "category": "economy",
        "cost": 120, "description": "+2 BC, +2 Research, +1 max pop",
        "effects": {"bc": 2, "research": 2, "max_pop": 1},
        "required_tech": "governance",
    },
    "atmospheric_renewer": {
        "id": "atmospheric_renewer", "name": "Atmospheric Renewer", "category": "farming",
        "cost": 180, "description": "+2 max pop, faster growth",
        "effects": {"max_pop": 2, "growth_rate": 0.1},
        "required_tech": "advanced_construction",
    },
    "automated_factory": {
        "id": "automated_factory", "name": "Automated Factory", "category": "economy",
        "cost": 250, "description": "+5 BC per turn",
        "effects": {"bc": 5},
        "required_tech": "automated_factories",
    },
    "stock_exchange": {
        "id": "stock_exchange", "name": "Stock Exchange", "category": "economy",
        "cost": 180, "description": "+5 BC, faster growth",
        "effects": {"bc": 5, "growth_rate": 0.1},
        "required_tech": "financial_planning",
    },
    "supercomputer": {
        "id": "supercomputer", "name": "Supercomputer", "category": "science",
        "cost": 200, "description": "+6 Research per turn",
        "effects": {"research": 6},
        "required_tech": "advanced_computers",
    },
    "galactic_cybernet": {
        "id": "galactic_cybernet", "name": "Galactic Cybernet", "category": "science",
        "cost": 350, "description": "+12 Research per turn",
        "effects": {"research": 12},
        "required_tech": "galactic_networks",
    },
    "soil_enrichment_b": {
        "id": "soil_enrichment_b", "name": "Enriched Soil", "category": "farming",
        "cost": 200, "description": "+1 max pop, faster growth",
        "effects": {"max_pop": 1, "growth_rate": 0.2},
        "required_tech": "soil_enrichment",
    },
    "cloning_center": {
        "id": "cloning_center", "name": "Cloning Center", "category": "farming",
        "cost": 250, "description": "+1 max pop, cloned cells & organs (+0.55 growth)",
        "effects": {"max_pop": 1, "growth_rate": 0.55},
        "required_tech": "cloning",
    },
    "subterranean_farms": {
        "id": "subterranean_farms", "name": "Subterranean Farms",
        "category": "farming",
        "cost": 150, "description": "Underground fungi vats (+3 food/turn)",
        "effects": {"food": 3},
        "required_tech": "soil_enrichment",
    },
    "weather_control_center": {
        "id": "weather_control_center", "name": "Weather Control Center",
        "category": "farming",
        "cost": 320, "description": "Climate engineering (+5 food, faster growth)",
        "effects": {"food": 5, "growth_rate": 0.15},
        "required_tech": "weather_controller",
    },
    "orbital_mirror": {
        "id": "orbital_mirror", "name": "Orbital Mirror",
        "category": "farming",
        "cost": 380, "description": "Solar reflectors in orbit (+4 food, +growth)",
        "effects": {"food": 4, "growth_rate": 0.10},
        "required_tech": "orbital_mirror_array",
    },
    "astro_university_b": {
        "id": "astro_university_b", "name": "Astro University",
        "category": "science",
        "cost": 320, "description": "Networked research institutes (+8 research)",
        "effects": {"research": 8},
        "required_tech": "astro_university",
    },
    "pleasure_dome_b": {
        "id": "pleasure_dome_b", "name": "Pleasure Dome",
        "category": "economy",
        "cost": 360, "description": "Leisure habitat (+2 max pop, +5 BC, +growth)",
        "effects": {"max_pop": 2, "bc": 5, "growth_rate": 0.20},
        "required_tech": "pleasure_dome",
        # Hive Mind / Mind Link races have no individual desires —
        # leisure habitats are meaningless to them.
        "forbidden_traits": ["hive_mind", "mind_link"],
    },
    # ---- Tier 4 expansions ----
    "deep_core_mine": {
        "id": "deep_core_mine", "name": "Deep Core Mine", "category": "economy",
        "cost": 300, "description": "+8 BC per turn",
        "effects": {"bc": 8},
        "required_tech": "robo_miners",
    },
    "vr_network": {
        "id": "vr_network", "name": "VR Network", "category": "science",
        "cost": 280, "description": "+4 Research, faster growth",
        "effects": {"research": 4, "growth_rate": 0.15},
        "required_tech": "virtual_reality_network",
    },
    "positronic_brain": {
        "id": "positronic_brain", "name": "Positronic Brain", "category": "science",
        "cost": 400, "description": "+15 Research per turn",
        "effects": {"research": 15},
        "required_tech": "positronic_computers",
    },
    "terraforming": {
        "id": "terraforming", "name": "Terraforming", "category": "farming",
        "cost": 350, "description": "+3 max pop",
        "effects": {"max_pop": 3},
        "required_tech": "terraforming",
    },
    # Habitability chain — each unlocked by a formerly-stub tech. These
    # reuse the standard max_pop / food completion effects; the tech's
    # gameplay payoff IS unlocking the buildable project (MOO2 model).
    "atmospheric_terraforming_b": {
        "id": "atmospheric_terraforming_b", "name": "Atmosphere Terraforming",
        "category": "farming",
        "cost": 300, "description": "Reshape the air (+2 max pop, +growth)",
        "effects": {"max_pop": 2, "growth_rate": 0.10},
        "required_tech": "atmospheric_terraforming",
    },
    "radiation_shielding": {
        "id": "radiation_shielding", "name": "Radiation Shielding",
        "category": "farming",
        "cost": 400, "description": "Habitats for hostile worlds (+3 max pop)",
        "effects": {"max_pop": 3},
        "required_tech": "irradiation_resistance",
    },
    "biomorphic_farms": {
        "id": "biomorphic_farms", "name": "Biomorphic Farms",
        "category": "farming",
        "cost": 450, "description": "Engineered crops (+3 food, +1 max pop)",
        "effects": {"food": 3, "max_pop": 1},
        "required_tech": "biomorphic_fungi",
    },
    "gaia_transformation_b": {
        "id": "gaia_transformation_b", "name": "Gaia Transformation",
        "category": "farming",
        "cost": 700, "description": "Terraform to a garden world (+5 max pop, +growth)",
        "effects": {"max_pop": 5, "growth_rate": 0.15},
        "required_tech": "gaia_transformation",
    },
    "artificial_planet_b": {
        "id": "artificial_planet_b", "name": "Artificial Planet",
        "category": "economy",
        "cost": 900, "description": "Vast orbital habitats (+6 max pop)",
        "effects": {"max_pop": 6},
        "required_tech": "artificial_planet",
    },
    # ---- Military (planetary defenses) ---------------------------------
    # MOO2-style ground/orbital defense buildings. Effects are flat
    # planet bonuses for now; ``defense`` value is reserved for the
    # future combat-tick integration (planets with defense contribute
    # attack/hull to friendly ships in their system).
    "missile_base": {
        "id": "missile_base", "name": "Missile Base", "category": "military",
        "cost": 80, "description": "Ground-based interceptors. +2 defense.",
        "effects": {"defense": 2},
    },
    "ground_batteries": {
        "id": "ground_batteries", "name": "Ground Batteries", "category": "military",
        "cost": 140, "description": "Heavy planet-side cannons. +4 defense.",
        "effects": {"defense": 4},
        "required_tech": "industrial_engineering",
    },
    "fighter_garrison": {
        "id": "fighter_garrison", "name": "Fighter Garrison", "category": "military",
        "cost": 160, "description": "Stationed fighter wing. +5 defense.",
        "effects": {"defense": 5},
        "required_tech": "industrial_engineering",
    },
    # Orbital defense chain: only one of these can stand at a planet at
    # a time. Completing a higher tier scraps the lower one (handled in
    # production_tick via the shared ``chain`` tag). MOO2-faithful —
    # building the new fortress replaces the old, no refunds.
    "star_base": {
        "id": "star_base", "name": "Star Base", "category": "military",
        "cost": 220, "description": "Orbital platform. +8 defense.",
        "effects": {"defense": 8},
        "required_tech": "advanced_construction",
        "chain": "orbital_defense",
    },
    "battlestation": {
        "id": "battlestation", "name": "Battlestation", "category": "military",
        "cost": 380, "description": "Upgraded orbital fortress. +14 defense. "
                                    "Replaces the Star Base.",
        "effects": {"defense": 14},
        "required_tech": "automated_factories",
        "chain": "orbital_defense",
    },
    "star_fortress": {
        "id": "star_fortress", "name": "Star Fortress", "category": "military",
        "cost": 600, "description": "Top-tier system stronghold. +24 defense. "
                                    "Replaces the Battlestation.",
        "effects": {"defense": 24},
        "required_tech": "robo_miners",
        "chain": "orbital_defense",
    },
}


# Display ordering of categories in the Build screen, plus a label
# and accent colour for each. Military now holds planetary defenses;
# Ships hosts every vessel (civilian + military) for clarity.
CATEGORIES = [
    ("economy",  "Economy",  (240, 200, 100)),
    ("farming",  "Farming",  (140, 220, 140)),
    ("science",  "Science",  (140, 180, 240)),
    ("military", "Military", (240, 130, 130)),
    ("ships",    "Ships",    (200, 160, 240)),
]
CATEGORY_LABEL = {key: label for key, label, _ in CATEGORIES}
CATEGORY_COLOR = {key: color for key, _, color in CATEGORIES}

# Inject ship projects from the SHIPS catalog so the Build screen gets
# them automatically. Each maps to a build project of type "ship" filed
# under the Ships category, tagged with the ship's kind (civilian /
# military) so the BuildScene can group them.
for _ship_id in SHIP_ORDER:
    _spec = SHIPS[_ship_id]
    _kind = _spec.get("ship_class_kind", "military")
    # Civilian ships (Scout, Freighter, Outpost, Colony) get a clearer
    # description; military ones list their combat stats.
    if _kind == "civilian":
        _desc = _spec.get("description") or f"Speed {_spec['speed']}"
    else:
        _desc = f"Hull {_spec['hull']}  Attack {_spec['attack']}  Speed {_spec['speed']}"
    PROJECTS[f"ship_{_ship_id}"] = {
        "id": f"ship_{_ship_id}",
        "name": _spec["name"],
        "category": "ships",
        "ship_kind": _kind,  # civilian | military
        "cost": _spec["cost"],
        "description": _desc,
        "type": "ship",
        "ship_class": _ship_id,
    }
    # Tech-gated hulls (Titan / Doom Star) carry their requirement so the
    # Build screen locks them until the tech is researched.
    if _spec.get("required_tech"):
        PROJECTS[f"ship_{_ship_id}"]["required_tech"] = _spec["required_tech"]


def projects_in_category(category: str, unlocked_techs=None) -> list[dict]:
    """Return projects tagged with ``category``, alphabetical by name.

    If ``unlocked_techs`` is given, the result includes locked items
    too — callers (BuildScene) display them dimmed so the player can
    see what's coming.
    """
    out = [p for p in PROJECTS.values() if p.get("category") == category]
    out.sort(key=lambda p: p["name"].lower())
    return out


# Display order in pickers. Two rows of buildings now that the tech
# tree adds late-game choices; the colony scene wraps if it overflows.
BUILDING_ORDER = [
    # Early game (free or simple tech)
    "factory", "granary", "research_lab", "hydroponics", "marketplace", "capital",
    # Mid / late game (gated by deeper tech)
    "atmospheric_renewer", "automated_factory", "stock_exchange",
    "supercomputer", "galactic_cybernet", "soil_enrichment_b",
    "subterranean_farms", "cloning_center",
    # Late game (tier-4 tech unlocks)
    "deep_core_mine", "vr_network", "positronic_brain", "terraforming",
    # Top-tier exotic projects
    "weather_control_center", "orbital_mirror",
    "astro_university_b", "pleasure_dome_b",
    # Planetary defenses
    "missile_base", "ground_batteries", "fighter_garrison",
    "star_base", "battlestation", "star_fortress",
]
SHIP_PROJECT_ORDER = [f"ship_{s}" for s in SHIP_ORDER]
PROJECT_ORDER = BUILDING_ORDER + SHIP_PROJECT_ORDER


def project_is_available(project_id: str, unlocked_techs: set[str] | list,
                          traits=None) -> bool:
    """A project requires its `required_tech` (if any) to be unlocked,
    and must not have any trait listed in ``forbidden_traits`` that the
    empire actually has. Pass ``traits`` from ``effective_traits`` for
    the trait filter; omit it to skip the trait check (older callers)."""
    proj = PROJECTS.get(project_id)
    if proj is None:
        return False
    if traits:
        for forbidden in proj.get("forbidden_traits", ()):
            if forbidden in traits:
                return False
    required = proj.get("required_tech")
    if required is None:
        return True
    return required in set(unlocked_techs)


def project_allowed_for_traits(project_id: str, traits) -> bool:
    """True if the project isn't disabled by the empire's race traits.
    Used by economy ticks to filter completed buildings on conquest /
    rule-change so a hive race that captured a Pleasure-Dome world
    doesn't get its effects."""
    proj = PROJECTS.get(project_id)
    if proj is None:
        return False
    if not traits:
        return True
    for forbidden in proj.get("forbidden_traits", ()):
        if forbidden in traits:
            return False
    return True


def building_growth_bonus(completed_ids, traits=None) -> float:
    """Sum the growth_rate bonuses from a planet's completed buildings.
    Buildings forbidden by the empire's race traits (e.g. Pleasure
    Dome for hive races) contribute nothing."""
    total = 0.0
    for project_id in completed_ids:
        if traits and not project_allowed_for_traits(project_id, traits):
            continue
        total += PROJECTS.get(project_id, {}).get("effects", {}).get("growth_rate", 0.0)
    return total


def project(project_id: str) -> dict | None:
    return PROJECTS.get(project_id)

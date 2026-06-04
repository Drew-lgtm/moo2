"""Empire-level tech tree, MOO2-style.

Nine fields × multiple tiers. At each tier the player picks **one of
2-3 alternatives** — the others get locked out for that empire (MOO2's
signature trade-off; they can still be acquired by spy theft or tech
trade with a rival who chose differently).

Fields:

- **Construction** — heavy industry, factories, armor frames
- **Power** — ship drives, fuel, energy systems
- **Chemistry** — armor materials, fuel cells, atmospheric work
- **Sociology** — trade, government, diplomacy
- **Computers** — research, networks, security
- **Biology** — farming, growth, terraforming, genetics
- **Physics** — ship weapons, scanners, exotic beams
- **Force Fields** — shields, cloaking, planetary barriers
- **Espionage** — spies, counter-intel (a modern addition)

Each tech carries:

- ``field`` / ``tier`` — column + row in the Research scene.
- ``tier_group`` — the tier slot id (e.g. ``construction_t2``). Techs
  sharing a tier_group are alternatives at the same choice point.
- ``cost`` — research points to unlock.
- ``prereqs`` — list of tech ids; satisfied if *any* alternative in the
  prereq's tier_group is unlocked (so picking a different branch still
  unlocks the next tier).
- ``description`` — UI tooltip text.
- effect fields (optional): ``speed_bonus`` / ``attack_bonus`` /
  ``hull_bonus`` / ``sensor_range`` / ``fuel_range`` /
  ``industry_per_worker`` / ``food_per_farmer`` /
  ``research_per_scientist`` / ``spy_offense`` / ``spy_defense`` /
  ``stealth`` / ``mind_scan``. MAX semantics across unlocked techs.
- ``effect_stub`` — True means the tech is in the catalogue but its
  effect isn't wired up to a game system yet (clearly marked in the UI
  with "(not yet implemented)"). Stubs preserve MOO2's tree shape until
  the underlying mechanic lands.
"""
from __future__ import annotations


# Fields the catalog covers (order = display order in Research scene).
FIELDS = [
    "construction", "power", "chemistry", "sociology", "computers",
    "biology", "physics", "force_fields", "espionage",
]

FIELD_NAMES = {
    "construction": "Construction",
    "power":        "Power",
    "chemistry":    "Chemistry",
    "sociology":    "Sociology",
    "computers":    "Computers",
    "biology":      "Biology",
    "physics":      "Physics",
    "force_fields": "Force Fields",
    "espionage":    "Espionage",
}

FIELD_COLORS = {
    "construction": (210, 150, 80),
    "power":        (230, 200, 80),
    "chemistry":    (180, 200, 120),
    "sociology":    (160, 220, 140),
    "computers":    (140, 180, 230),
    "biology":      (150, 220, 180),
    "physics":      (220, 140, 220),
    "force_fields": (120, 200, 230),
    "espionage":    (200, 110, 130),
}


def _t(field, tier):
    """Convenience for tier_group keys."""
    return f"{field}_t{tier}"


TECHS: dict[str, dict] = {
    # ===================================================================
    # Construction — industry, factories, armor frames
    # ===================================================================
    "industrial_engineering": {
        "id": "industrial_engineering", "name": "Industrial Engineering",
        "field": "construction", "tier": 1, "tier_group": _t("construction", 1),
        "cost": 80, "prereqs": [],
        "description": "Enables Factory; +1 production per worker",
        "industry_per_worker": 1,
    },
    "heavy_armor": {
        "id": "heavy_armor", "name": "Heavy Armor",
        "field": "construction", "tier": 1, "tier_group": _t("construction", 1),
        "cost": 80, "prereqs": [],
        "description": "Reinforced ship plating (+2 hull)",
        "equipment": {"slot": "armor", "size": 1, "hull": 2},
    },
    "anti_missile_rockets": {
        "id": "anti_missile_rockets", "name": "Anti-Missile Rockets",
        "field": "construction", "tier": 1, "tier_group": _t("construction", 1),
        "cost": 80, "prereqs": [],
        "description": "Point-defense interceptors (+1 defense per ship)",
        "equipment": {"slot": "special", "size": 1, "defense": 1},
    },
    "advanced_construction": {
        "id": "advanced_construction", "name": "Advanced Construction",
        "field": "construction", "tier": 2, "tier_group": _t("construction", 2),
        "cost": 200, "prereqs": ["industrial_engineering"],
        "description": "Enables Atmospheric Renewer; +1 production per worker",
        "industry_per_worker": 1,
    },
    "cold_fusion": {
        "id": "cold_fusion", "name": "Cold Fusion",
        "field": "construction", "tier": 2, "tier_group": _t("construction", 2),
        "cost": 200, "prereqs": ["industrial_engineering"],
        "description": "Clean civilian grid (+1 production/worker)",
        "industry_per_worker": 1,
    },
    "pollution_processor": {
        "id": "pollution_processor", "name": "Pollution Processor",
        "field": "construction", "tier": 2, "tier_group": _t("construction", 2),
        "cost": 200, "prereqs": ["industrial_engineering"],
        "description": "Waste reclamation (+1 production/worker)",
        "industry_per_worker": 1,
    },
    "automated_factories": {
        "id": "automated_factories", "name": "Robotic Factories",
        "field": "construction", "tier": 3, "tier_group": _t("construction", 3),
        "cost": 400, "prereqs": ["advanced_construction"],
        "description": "Enables Automated Factory; +2 production per worker",
        "industry_per_worker": 2,
    },
    "battle_pods": {
        "id": "battle_pods", "name": "Battle Pods",
        "field": "construction", "tier": 3, "tier_group": _t("construction", 3),
        "cost": 400, "prereqs": ["advanced_construction"],
        "description": "Modular internal volume (+50% ship space)",
        "equipment": {"slot": "special", "size": 1, "space_bonus_pct": 50},
    },
    "powered_armor": {
        "id": "powered_armor", "name": "Powered Armor",
        "field": "construction", "tier": 3, "tier_group": _t("construction", 3),
        "cost": 400, "prereqs": ["advanced_construction"],
        "description": "Marine exoskeletons (+3 attack, +1 defense per marine)",
        "marine_attack": 3, "marine_defense": 1,
    },
    "robo_miners": {
        "id": "robo_miners", "name": "Deep Core Mining",
        "field": "construction", "tier": 4, "tier_group": _t("construction", 4),
        "cost": 700, "prereqs": ["automated_factories"],
        "description": "Enables Deep Core Mine; +3 production per worker",
        "industry_per_worker": 3,
    },
    "augmented_engines": {
        "id": "augmented_engines", "name": "Augmented Engines",
        "field": "construction", "tier": 4, "tier_group": _t("construction", 4),
        "cost": 700, "prereqs": ["automated_factories"],
        "description": "Tactical thrust boost (+1 attack per ship)",
        "equipment": {"slot": "special", "size": 1, "attack": 1},
    },
    "fast_missile_racks": {
        "id": "fast_missile_racks", "name": "Fast Missile Racks",
        "field": "construction", "tier": 4, "tier_group": _t("construction", 4),
        "cost": 700, "prereqs": ["automated_factories"],
        "description": "Double-fire missile launchers (+2 attack per ship)",
        "equipment": {"slot": "special", "size": 2, "attack": 2},
    },
    "adamantium_armor": {
        "id": "adamantium_armor", "name": "Adamantium Armor",
        "field": "construction", "tier": 5, "tier_group": _t("construction", 5),
        "cost": 1100, "prereqs": ["robo_miners"],
        "description": "Hardened ship hulls (+6 hull)",
        "equipment": {"slot": "armor", "size": 2, "hull": 6},
    },
    "inertial_stabilizer": {
        "id": "inertial_stabilizer", "name": "Inertial Stabilizer",
        "field": "construction", "tier": 5, "tier_group": _t("construction", 5),
        "cost": 1100, "prereqs": ["robo_miners"],
        "description": "Ships dodge incoming fire (+2 defense)",
        "equipment": {"slot": "special", "size": 2, "defense": 2},
    },
    "artificial_planet": {
        "id": "artificial_planet", "name": "Artificial Planet",
        "field": "construction", "tier": 6, "tier_group": _t("construction", 6),
        "cost": 1600, "prereqs": ["adamantium_armor"],
        "description": "Construct planetoid colonies", "effect_stub": True,
    },
    "xeno_hull": {
        "id": "xeno_hull", "name": "Xeno-Composite Hull",
        "field": "construction", "tier": 6, "tier_group": _t("construction", 6),
        "cost": 1600, "prereqs": ["adamantium_armor"],
        "description": "Alien composite shipframes (+5 hull)",
        "equipment": {"slot": "armor", "size": 2, "hull": 5},
    },

    # ===================================================================
    # Power — drives, fuel, energy systems
    # ===================================================================
    "nuclear_drives": {
        "id": "nuclear_drives", "name": "Nuclear Drives",
        "field": "power", "tier": 1, "tier_group": _t("power", 1),
        "cost": 60, "prereqs": [],
        "description": "+1 ship speed, fuel range 6 pc",
        "speed_bonus": 1, "fuel_range": 6,
    },
    "chemical_fuel": {
        "id": "chemical_fuel", "name": "Chemical Fuel Refinement",
        "field": "power", "tier": 1, "tier_group": _t("power", 1),
        "cost": 60, "prereqs": [],
        "description": "Refined chemical fuel (+1 parsec range)",
        "fuel_range": 1,
    },
    "fusion_drives": {
        "id": "fusion_drives", "name": "Fusion Drives",
        "field": "power", "tier": 2, "tier_group": _t("power", 2),
        "cost": 150, "prereqs": ["nuclear_drives"],
        "description": "+2 ship speed, fuel range 8 pc",
        "speed_bonus": 2, "fuel_range": 8,
    },
    "subspace_communications": {
        "id": "subspace_communications", "name": "Subspace Communications",
        "field": "power", "tier": 2, "tier_group": _t("power", 2),
        "cost": 150, "prereqs": ["nuclear_drives"],
        "description": "Real-time fleet command", "effect_stub": True,
    },
    "ion_drives": {
        "id": "ion_drives", "name": "Ion Drives",
        "field": "power", "tier": 3, "tier_group": _t("power", 3),
        "cost": 300, "prereqs": ["fusion_drives"],
        "description": "+3 ship speed, fuel range 11 pc",
        "speed_bonus": 3, "fuel_range": 11,
    },
    "warp_dissipator": {
        "id": "warp_dissipator", "name": "Warp Dissipator",
        "field": "power", "tier": 3, "tier_group": _t("power", 3),
        "cost": 300, "prereqs": ["fusion_drives"],
        "description": "Disable enemy FTL in-system", "effect_stub": True,
    },
    "anti_matter_drives": {
        "id": "anti_matter_drives", "name": "Anti-Matter Drives",
        "field": "power", "tier": 4, "tier_group": _t("power", 4),
        "cost": 500, "prereqs": ["ion_drives"],
        "description": "+4 ship speed, fuel range 14 pc",
        "speed_bonus": 4, "fuel_range": 14,
    },
    "energy_absorber": {
        "id": "energy_absorber", "name": "Energy Absorber",
        "field": "power", "tier": 4, "tier_group": _t("power", 4),
        "cost": 500, "prereqs": ["ion_drives"],
        "description": "Convert incoming energy to shields", "effect_stub": True,
    },
    "hyper_drives": {
        "id": "hyper_drives", "name": "Hyper Drives",
        "field": "power", "tier": 5, "tier_group": _t("power", 5),
        "cost": 750, "prereqs": ["anti_matter_drives"],
        "description": "+5 ship speed, fuel range 18 pc",
        "speed_bonus": 5, "fuel_range": 18,
    },
    "interphased_drive": {
        "id": "interphased_drive", "name": "Interphased Drive",
        "field": "power", "tier": 5, "tier_group": _t("power", 5),
        "cost": 750, "prereqs": ["anti_matter_drives"],
        "description": "Ships phase-shift to dodge (+2 defense per ship)",
        "equipment": {"slot": "special", "size": 2, "defense": 2},
    },
    "transwarp_drive": {
        "id": "transwarp_drive", "name": "Transwarp Drives",
        "field": "power", "tier": 6, "tier_group": _t("power", 6),
        "cost": 1100, "prereqs": ["hyper_drives"],
        "description": "+6 ship speed, fuel range 20 pc",
        "speed_bonus": 6, "fuel_range": 20,
    },

    # ===================================================================
    # Chemistry — armor materials, fuel cells, atmospheres
    # ===================================================================
    "titanium_armor": {
        "id": "titanium_armor", "name": "Titanium Armor",
        "field": "chemistry", "tier": 1, "tier_group": _t("chemistry", 1),
        "cost": 80, "prereqs": [],
        "description": "Base composite plating (+2 hull)",
        "equipment": {"slot": "armor", "size": 1, "hull": 2},
    },
    "deuterium_fuel": {
        "id": "deuterium_fuel", "name": "Deuterium Fuel Cells",
        "field": "chemistry", "tier": 1, "tier_group": _t("chemistry", 1),
        "cost": 80, "prereqs": [],
        "description": "Compact reactor fuel (+1 parsec range)",
        "fuel_range": 1,
    },
    "tritanium_armor": {
        "id": "tritanium_armor", "name": "Tritanium Armor",
        "field": "chemistry", "tier": 2, "tier_group": _t("chemistry", 2),
        "cost": 200, "prereqs": ["titanium_armor"],
        "description": "Stronger hull alloy (+4 hull)",
        "equipment": {"slot": "armor", "size": 2, "hull": 4},
    },
    "irridium_fuel": {
        "id": "irridium_fuel", "name": "Irridium Fuel Cells",
        "field": "chemistry", "tier": 2, "tier_group": _t("chemistry", 2),
        "cost": 200, "prereqs": ["titanium_armor"],
        "description": "Longer-range fuel cells (+2 parsec range)",
        "fuel_range": 2,
    },
    "pulson_missile": {
        "id": "pulson_missile", "name": "Pulson Missile",
        "field": "chemistry", "tier": 2, "tier_group": _t("chemistry", 2),
        "cost": 200, "prereqs": ["titanium_armor"],
        "description": "Improved missile warhead (+4 attack/slot)",
        "equipment": {"slot": "weapon", "size": 3, "attack": 4},
    },
    "atmospheric_terraforming": {
        "id": "atmospheric_terraforming", "name": "Atmospheric Terraforming",
        "field": "chemistry", "tier": 3, "tier_group": _t("chemistry", 3),
        "cost": 400, "prereqs": ["tritanium_armor"],
        "description": "Reshape toxic / radiated worlds", "effect_stub": True,
    },
    "merculite_missile": {
        "id": "merculite_missile", "name": "Merculite Missile",
        "field": "chemistry", "tier": 3, "tier_group": _t("chemistry", 3),
        "cost": 400, "prereqs": ["tritanium_armor"],
        "description": "Advanced missile guidance (+5 attack/slot)",
        "equipment": {"slot": "weapon", "size": 3, "attack": 5},
    },
    "adamantium_chem": {
        "id": "adamantium_chem", "name": "Adamantium Chemistry",
        "field": "chemistry", "tier": 4, "tier_group": _t("chemistry", 4),
        "cost": 700, "prereqs": ["atmospheric_terraforming"],
        "description": "Synthesize ultra-hard alloys (+6 hull)",
        "equipment": {"slot": "armor", "size": 2, "hull": 6},
    },
    "irradiation_resistance": {
        "id": "irradiation_resistance", "name": "Irradiation Resistance",
        "field": "chemistry", "tier": 4, "tier_group": _t("chemistry", 4),
        "cost": 700, "prereqs": ["atmospheric_terraforming"],
        "description": "Colonize Radiated worlds", "effect_stub": True,
    },
    "neutronium_armor": {
        "id": "neutronium_armor", "name": "Neutronium Armor",
        "field": "chemistry", "tier": 5, "tier_group": _t("chemistry", 5),
        "cost": 1100, "prereqs": ["adamantium_chem"],
        "description": "Densest known armor (+10 hull)",
        "equipment": {"slot": "armor", "size": 3, "hull": 10},
    },
    "xentronium_armor": {
        "id": "xentronium_armor", "name": "Xentronium Armor",
        "field": "chemistry", "tier": 5, "tier_group": _t("chemistry", 5),
        "cost": 1100, "prereqs": ["adamantium_chem"],
        "description": "Pinnacle armor material (+14 hull)",
        "equipment": {"slot": "armor", "size": 3, "hull": 14},
    },

    # ===================================================================
    # Sociology — trade, government, diplomacy
    # ===================================================================
    "trade": {
        "id": "trade", "name": "Trade",
        "field": "sociology", "tier": 1, "tier_group": _t("sociology", 1),
        "cost": 60, "prereqs": [],
        "description": "Enables Marketplace",
    },
    "diplomatic_corps": {
        "id": "diplomatic_corps", "name": "Diplomatic Corps",
        "field": "sociology", "tier": 1, "tier_group": _t("sociology", 1),
        "cost": 60, "prereqs": [],
        "description": "Goodwill abroad (+1 spy defense)",
        "spy_defense": 1,
    },
    "governance": {
        "id": "governance", "name": "Governance",
        "field": "sociology", "tier": 2, "tier_group": _t("sociology", 2),
        "cost": 200, "prereqs": ["trade", "industrial_engineering"],
        "description": "Enables Capital",
    },
    "xeno_relations": {
        "id": "xeno_relations", "name": "Xeno Relations",
        "field": "sociology", "tier": 2, "tier_group": _t("sociology", 2),
        "cost": 200, "prereqs": ["trade"],
        "description": "Insight into alien minds (+1 spy offense)",
        "spy_offense": 1,
    },
    "financial_planning": {
        "id": "financial_planning", "name": "Financial Planning",
        "field": "sociology", "tier": 3, "tier_group": _t("sociology", 3),
        "cost": 300, "prereqs": ["governance"],
        "description": "Enables Stock Exchange",
    },
    "federation": {
        "id": "federation", "name": "Federation",
        "field": "sociology", "tier": 3, "tier_group": _t("sociology", 3),
        "cost": 300, "prereqs": ["governance"],
        "description": "Powerful alliance treaties", "effect_stub": True,
    },
    "virtual_reality_network": {
        "id": "virtual_reality_network", "name": "Virtual Reality Network",
        "field": "sociology", "tier": 4, "tier_group": _t("sociology", 4),
        "cost": 500, "prereqs": ["financial_planning"],
        "description": "Enables VR Network",
    },
    "galactic_currency_exchange": {
        "id": "galactic_currency_exchange", "name": "Galactic Currency Exchange",
        "field": "sociology", "tier": 4, "tier_group": _t("sociology", 4),
        "cost": 500, "prereqs": ["financial_planning"],
        "description": "Empire-wide BC boost", "effect_stub": True,
    },
    "galactic_unification": {
        "id": "galactic_unification", "name": "Galactic Unification",
        "field": "sociology", "tier": 5, "tier_group": _t("sociology", 5),
        "cost": 800, "prereqs": ["virtual_reality_network"],
        "description": "Bind worlds into one polity", "effect_stub": True,
    },
    "xeno_psychology": {
        "id": "xeno_psychology", "name": "Xeno Psychology",
        "field": "sociology", "tier": 5, "tier_group": _t("sociology", 5),
        "cost": 800, "prereqs": ["virtual_reality_network"],
        "description": "Read alien intent (+2 spy offense & defense)",
        "spy_offense": 2, "spy_defense": 2,
    },

    # ===================================================================
    # Computers — research, networks, security
    # ===================================================================
    "computer_science": {
        "id": "computer_science", "name": "Computer Science",
        "field": "computers", "tier": 1, "tier_group": _t("computers", 1),
        "cost": 80, "prereqs": [],
        "description": "Enables Research Lab",
    },
    "optronic_computer": {
        "id": "optronic_computer", "name": "Optronic Computer",
        "field": "computers", "tier": 1, "tier_group": _t("computers", 1),
        "cost": 80, "prereqs": [],
        "description": "Light-based processors (+1 research/scientist)",
        "research_per_scientist": 1,
    },
    "advanced_computers": {
        "id": "advanced_computers", "name": "Advanced Computers",
        "field": "computers", "tier": 2, "tier_group": _t("computers", 2),
        "cost": 200, "prereqs": ["computer_science"],
        "description": "Enables Supercomputer; +1 research per scientist",
        "research_per_scientist": 1,
    },
    "cyber_security_link": {
        "id": "cyber_security_link", "name": "Cyber Security Link",
        "field": "computers", "tier": 2, "tier_group": _t("computers", 2),
        "cost": 200, "prereqs": ["computer_science"],
        "description": "Hardened networks (+2 spy defense)",
        "spy_defense": 2,
    },
    "galactic_networks": {
        "id": "galactic_networks", "name": "Galactic Networks",
        "field": "computers", "tier": 3, "tier_group": _t("computers", 3),
        "cost": 400, "prereqs": ["advanced_computers"],
        "description": "Enables Galactic Cybernet; +1 research per scientist",
        "research_per_scientist": 1,
    },
    "holo_simulator": {
        "id": "holo_simulator", "name": "Holo Simulator",
        "field": "computers", "tier": 3, "tier_group": _t("computers", 3),
        "cost": 400, "prereqs": ["advanced_computers"],
        "description": "Drill simulation (+1 attack per ship)",
        "equipment": {"slot": "special", "size": 1, "attack": 1},
    },
    "positronic_computers": {
        "id": "positronic_computers", "name": "Positronic Computers",
        "field": "computers", "tier": 4, "tier_group": _t("computers", 4),
        "cost": 700, "prereqs": ["galactic_networks"],
        "description": "Enables Positronic Brain; +2 research per scientist",
        "research_per_scientist": 2,
    },
    "molecular_compression": {
        "id": "molecular_compression", "name": "Molecular Compression",
        "field": "computers", "tier": 4, "tier_group": _t("computers", 4),
        "cost": 700, "prereqs": ["galactic_networks"],
        "description": "Mass-energy storage", "effect_stub": True,
    },
    "cybertronic_computer": {
        "id": "cybertronic_computer", "name": "Cybertronic Computer",
        "field": "computers", "tier": 5, "tier_group": _t("computers", 5),
        "cost": 1000, "prereqs": ["positronic_computers"],
        "description": "Adaptive AI cores (+2 spy offense & defense)",
        "spy_offense": 2, "spy_defense": 2,
    },
    "achilles_targeting": {
        "id": "achilles_targeting", "name": "Achilles Targeting",
        "field": "computers", "tier": 5, "tier_group": _t("computers", 5),
        "cost": 1000, "prereqs": ["positronic_computers"],
        "description": "Hit critical systems (+2 attack/ship)",
        "equipment": {"slot": "special", "size": 2, "attack": 2},
    },

    # ===================================================================
    # Biology — farming, growth, terraforming, genetics
    # ===================================================================
    "agriculture": {
        "id": "agriculture", "name": "Agriculture",
        "field": "biology", "tier": 1, "tier_group": _t("biology", 1),
        "cost": 80, "prereqs": [],
        "description": "Enables Hydroponics; +1 food per farmer",
        "food_per_farmer": 1,
    },
    "microbiotics": {
        "id": "microbiotics", "name": "Microbiotics",
        "field": "biology", "tier": 1, "tier_group": _t("biology", 1),
        "cost": 80, "prereqs": [],
        "description": "Longer lives (+1 food per farmer)",
        "food_per_farmer": 1,
    },
    "soil_enrichment": {
        "id": "soil_enrichment", "name": "Soil Enrichment",
        "field": "biology", "tier": 2, "tier_group": _t("biology", 2),
        "cost": 150, "prereqs": ["agriculture"],
        "description": "Enables Enriched Soil; +1 food per farmer",
        "food_per_farmer": 1,
    },
    "heightened_intelligence": {
        "id": "heightened_intelligence", "name": "Heightened Intelligence",
        "field": "biology", "tier": 2, "tier_group": _t("biology", 2),
        "cost": 150, "prereqs": ["agriculture"],
        "description": "Smarter pop (+1 research/scientist)",
        "research_per_scientist": 1,
    },
    "cloning": {
        "id": "cloning", "name": "Cloning",
        "field": "biology", "tier": 3, "tier_group": _t("biology", 3),
        "cost": 300, "prereqs": ["soil_enrichment"],
        "description": "Enables Cloning Center; +1 food per farmer",
        "food_per_farmer": 1,
    },
    "telepathic_training": {
        "id": "telepathic_training", "name": "Telepathic Training",
        "field": "biology", "tier": 3, "tier_group": _t("biology", 3),
        "cost": 300, "prereqs": ["soil_enrichment"],
        "description": "Mind training (+1 spy offense & defense)",
        "spy_offense": 1, "spy_defense": 1,
    },
    "bio_terminators": {
        "id": "bio_terminators", "name": "Bio Terminators",
        "field": "biology", "tier": 3, "tier_group": _t("biology", 3),
        "cost": 300, "prereqs": ["soil_enrichment"],
        "description": "Anti-bio strike weapons", "effect_stub": True,
    },
    "terraforming": {
        "id": "terraforming", "name": "Terraforming",
        "field": "biology", "tier": 4, "tier_group": _t("biology", 4),
        "cost": 600, "prereqs": ["cloning"],
        "description": "Enables Terraforming; +2 food per farmer",
        "food_per_farmer": 2,
    },
    "biomorphic_fungi": {
        "id": "biomorphic_fungi", "name": "Biomorphic Fungi",
        "field": "biology", "tier": 4, "tier_group": _t("biology", 4),
        "cost": 600, "prereqs": ["cloning"],
        "description": "Pop on hostile worlds", "effect_stub": True,
    },
    "gaia_transformation": {
        "id": "gaia_transformation", "name": "Gaia Transformation",
        "field": "biology", "tier": 5, "tier_group": _t("biology", 5),
        "cost": 1000, "prereqs": ["terraforming"],
        "description": "Convert worlds to Gaia", "effect_stub": True,
    },
    "evolutionary_mutation": {
        "id": "evolutionary_mutation", "name": "Evolutionary Mutation",
        "field": "biology", "tier": 5, "tier_group": _t("biology", 5),
        "cost": 1000, "prereqs": ["terraforming"],
        "description": "Re-pick a race trait mid-game", "effect_stub": True,
    },

    # ===================================================================
    # Physics — ship weapons, scanners, exotic beams
    # ===================================================================
    "laser_cannons": {
        "id": "laser_cannons", "name": "Laser Cannons",
        "field": "physics", "tier": 1, "tier_group": _t("physics", 1),
        "cost": 100, "prereqs": [],
        "description": "Ship-mounted lasers (+1 attack/slot)",
        "equipment": {"slot": "weapon", "size": 1, "attack": 1},
    },
    "death_ray": {
        "id": "death_ray", "name": "Death Ray Projector",
        "field": "physics", "tier": 1, "tier_group": _t("physics", 1),
        "cost": 100, "prereqs": [],
        "description": "Heavy bombardment cannon (+3 attack)",
        "equipment": {"slot": "weapon", "size": 3, "attack": 3},
    },
    "phasors": {
        "id": "phasors", "name": "Phasors",
        "field": "physics", "tier": 2, "tier_group": _t("physics", 2),
        "cost": 250, "prereqs": ["laser_cannons"],
        "description": "Improved beam weapons (+2 attack/slot)",
        "equipment": {"slot": "weapon", "size": 2, "attack": 2},
    },
    "disruptor": {
        "id": "disruptor", "name": "Disruptor",
        "field": "physics", "tier": 2, "tier_group": _t("physics", 2),
        "cost": 250, "prereqs": ["laser_cannons"],
        "description": "Penetrating beam (+3 attack/slot)",
        "equipment": {"slot": "weapon", "size": 2, "attack": 3},
    },
    "tachyon_scanner": {
        "id": "tachyon_scanner", "name": "Tachyon Scanner",
        "field": "physics", "tier": 3, "tier_group": _t("physics", 3),
        "cost": 400, "prereqs": ["phasors"],
        "description": "Long-range fleet detection",
        "sensor_range": 16,
    },
    "mass_driver": {
        "id": "mass_driver", "name": "Mass Driver",
        "field": "physics", "tier": 3, "tier_group": _t("physics", 3),
        "cost": 400, "prereqs": ["phasors"],
        "description": "Kinetic shield-piercer (+2 attack/slot)",
        "equipment": {"slot": "weapon", "size": 2, "attack": 2},
    },
    "plasma_cannons": {
        "id": "plasma_cannons", "name": "Plasma Cannons",
        "field": "physics", "tier": 4, "tier_group": _t("physics", 4),
        "cost": 600, "prereqs": ["tachyon_scanner"],
        "description": "Heavy plasma weapon (+3 attack/slot)",
        "equipment": {"slot": "weapon", "size": 3, "attack": 3},
    },
    "stellar_converter": {
        "id": "stellar_converter", "name": "Stellar Converter",
        "field": "physics", "tier": 4, "tier_group": _t("physics", 4),
        "cost": 600, "prereqs": ["tachyon_scanner"],
        "description": "Capital ship superweapon (+12 attack)",
        "equipment": {"slot": "weapon", "size": 8, "attack": 12},
    },
    "proton_torpedo": {
        "id": "proton_torpedo", "name": "Proton Torpedo",
        "field": "physics", "tier": 5, "tier_group": _t("physics", 5),
        "cost": 1000, "prereqs": ["plasma_cannons"],
        "description": "Guided heavy missile (+5 attack/slot)",
        "equipment": {"slot": "weapon", "size": 4, "attack": 5},
    },
    "mauler_device": {
        "id": "mauler_device", "name": "Mauler Device",
        "field": "physics", "tier": 5, "tier_group": _t("physics", 5),
        "cost": 1000, "prereqs": ["plasma_cannons"],
        "description": "Heavy directed-energy gun (+7 attack/slot, big)",
        "equipment": {"slot": "weapon", "size": 4, "attack": 7},
    },
    "phasing_cloak": {
        "id": "phasing_cloak", "name": "Phasing Cloak",
        "field": "physics", "tier": 5, "tier_group": _t("physics", 5),
        "cost": 1000, "prereqs": ["plasma_cannons"],
        "description": "Phase-shift cloaking device",
        "equipment": {"slot": "special", "size": 3, "cloak": True},
    },

    # ===================================================================
    # Force Fields — shields, cloaking, planetary barriers
    # ===================================================================
    "class_i_shield": {
        "id": "class_i_shield", "name": "Class I Shield",
        "field": "force_fields", "tier": 1, "tier_group": _t("force_fields", 1),
        "cost": 100, "prereqs": [],
        "description": "Basic ship shielding (8 cap, +2/round)",
        "equipment": {"slot": "shield", "size": 1, "capacity": 8, "regen": 2},
    },
    "personal_shield": {
        "id": "personal_shield", "name": "Personal Shield",
        "field": "force_fields", "tier": 1, "tier_group": _t("force_fields", 1),
        "cost": 100, "prereqs": [],
        "description": "Marine ground shielding (+2 defense per defender)",
        "marine_defense": 2,
    },
    "class_iii_shield": {
        "id": "class_iii_shield", "name": "Class III Shield",
        "field": "force_fields", "tier": 2, "tier_group": _t("force_fields", 2),
        "cost": 250, "prereqs": ["class_i_shield"],
        "description": "Stronger deflectors (20 cap, +4/round)",
        "equipment": {"slot": "shield", "size": 1, "capacity": 20, "regen": 4},
    },
    "tractor_beam": {
        "id": "tractor_beam", "name": "Tractor Beam",
        "field": "force_fields", "tier": 2, "tier_group": _t("force_fields", 2),
        "cost": 250, "prereqs": ["class_i_shield"],
        "description": "Lock enemy ship engines",
        "equipment": {"slot": "special", "size": 2},
    },
    "class_v_shield": {
        "id": "class_v_shield", "name": "Class V Shield",
        "field": "force_fields", "tier": 3, "tier_group": _t("force_fields", 3),
        "cost": 450, "prereqs": ["class_iii_shield"],
        "description": "Heavy deflectors (40 cap, +6/round)",
        "equipment": {"slot": "shield", "size": 2, "capacity": 40, "regen": 6},
    },
    "planetary_barrier_shield": {
        "id": "planetary_barrier_shield", "name": "Planetary Barrier Shield",
        "field": "force_fields", "tier": 3, "tier_group": _t("force_fields", 3),
        "cost": 450, "prereqs": ["class_iii_shield"],
        "description": "Build planet-wide shield", "effect_stub": True,
    },
    "stasis_field": {
        "id": "stasis_field", "name": "Stasis Field",
        "field": "force_fields", "tier": 3, "tier_group": _t("force_fields", 3),
        "cost": 450, "prereqs": ["class_iii_shield"],
        "description": "Stasis emitter (+3 defense per ship)",
        "equipment": {"slot": "special", "size": 2, "defense": 3},
    },
    "class_vii_shield": {
        "id": "class_vii_shield", "name": "Class VII Shield",
        "field": "force_fields", "tier": 4, "tier_group": _t("force_fields", 4),
        "cost": 750, "prereqs": ["class_v_shield"],
        "description": "Capital shields (70 cap, +10/round)",
        "equipment": {"slot": "shield", "size": 2, "capacity": 70, "regen": 10},
    },
    "wide_area_jammer": {
        "id": "wide_area_jammer", "name": "Wide Area Jammer",
        "field": "force_fields", "tier": 4, "tier_group": _t("force_fields", 4),
        "cost": 750, "prereqs": ["class_v_shield"],
        "description": "Jams enemy targeting (+1 defense)",
        "equipment": {"slot": "special", "size": 2, "defense": 1},
    },
    "hard_shields": {
        "id": "hard_shields", "name": "Hard Shields",
        "field": "force_fields", "tier": 5, "tier_group": _t("force_fields", 5),
        "cost": 1100, "prereqs": ["class_vii_shield"],
        "description": "Capital-grade barrier (100 cap, +14/round)",
        "equipment": {"slot": "shield", "size": 3, "capacity": 100, "regen": 14},
    },
    "cloaking_field": {
        "id": "cloaking_field", "name": "Cloaking Field",
        "field": "force_fields", "tier": 5, "tier_group": _t("force_fields", 5),
        "cost": 1100, "prereqs": ["class_vii_shield"],
        "description": "Ship-wide cloak",
        "equipment": {"slot": "special", "size": 3, "cloak": True},
    },

    # ===================================================================
    # Espionage — spies + counter-intelligence
    # ===================================================================
    "spy_network": {
        "id": "spy_network", "name": "Spy Network",
        "field": "espionage", "tier": 1, "tier_group": _t("espionage", 1),
        "cost": 120, "prereqs": [],
        "description": "+1 spy skill & security",
        "spy_offense": 1, "spy_defense": 1,
    },
    "counter_intelligence": {
        "id": "counter_intelligence", "name": "Counter-Intelligence",
        "field": "espionage", "tier": 1, "tier_group": _t("espionage", 1),
        "cost": 120, "prereqs": [],
        "description": "+1 security; faster spy detection",
        "spy_defense": 1,
    },
    "stealth_suit": {
        "id": "stealth_suit", "name": "Stealth Suit",
        "field": "espionage", "tier": 2, "tier_group": _t("espionage", 2),
        "cost": 280, "prereqs": ["spy_network"],
        "description": "+2 spy skill; caught spies rarely identified",
        "spy_offense": 2, "stealth": True,
    },
    "subterfuge": {
        "id": "subterfuge", "name": "Subterfuge",
        "field": "espionage", "tier": 2, "tier_group": _t("espionage", 2),
        "cost": 280, "prereqs": ["spy_network"],
        "description": "Frame rival empires on capture", "effect_stub": True,
    },
    "mind_scan": {
        "id": "mind_scan", "name": "Mind Scan",
        "field": "espionage", "tier": 3, "tier_group": _t("espionage", 3),
        "cost": 420, "prereqs": ["spy_network"],
        "description": "+3 security; always unmask caught spies",
        "spy_defense": 3, "mind_scan": True,
    },
    "assassination": {
        "id": "assassination", "name": "Assassination",
        "field": "espionage", "tier": 3, "tier_group": _t("espionage", 3),
        "cost": 420, "prereqs": ["spy_network"],
        "description": "Eliminate enemy leaders", "effect_stub": True,
    },
    "neural_scrambler": {
        "id": "neural_scrambler", "name": "Neural Scrambler",
        "field": "espionage", "tier": 4, "tier_group": _t("espionage", 4),
        "cost": 640, "prereqs": ["stealth_suit", "mind_scan"],
        "description": "+3 spy skill & security",
        "spy_offense": 3, "spy_defense": 3,
    },
    "deep_cover": {
        "id": "deep_cover", "name": "Deep Cover",
        "field": "espionage", "tier": 4, "tier_group": _t("espionage", 4),
        "cost": 640, "prereqs": ["stealth_suit", "mind_scan"],
        "description": "Sleeper agents (+1 spy offense, stealth)",
        "spy_offense": 1, "stealth": True,
    },
}


# ---- Convenience accessors ---------------------------------------------

def techs_in_field(field: str) -> list[dict]:
    return sorted(
        (t for t in TECHS.values() if t.get("field") == field),
        key=lambda t: (t.get("tier", 0), t["name"].lower()),
    )


def alternatives_in_group(tech_id: str) -> list[str]:
    """Tech ids that share the same tier_group as ``tech_id`` (the
    alternatives a player picks between — including ``tech_id`` itself).
    Solo techs (no tier_group set) return just the tech id."""
    group = TECHS.get(tech_id, {}).get("tier_group")
    if not group:
        return [tech_id]
    return [t["id"] for t in TECHS.values() if t.get("tier_group") == group]


def tier_group_of(tech_id: str) -> str | None:
    return TECHS.get(tech_id, {}).get("tier_group")


# Order used by the Info-panel research list and the AI's "next available"
# fallback. Tier 1s first, then 2s, etc., so a sensible default research
# emerges when no personality has a strong opinion.
TECH_ORDER = [
    tid for tid, spec in sorted(
        TECHS.items(),
        key=lambda kv: (kv[1].get("tier", 99), kv[1].get("field", ""), kv[0]),
    )
]


def is_available(tech_id: str, unlocked: set[str] | list,
                 locked_out: set[str] | list = ()) -> bool:
    """A tech is researchable if it isn't already unlocked or locked-out
    and every prereq is satisfied. A prereq is satisfied when EITHER
    that specific tech is unlocked OR any alternative in the prereq's
    tier_group is unlocked — so picking a different branch at a prior
    tier still opens the next tier."""
    if tech_id not in TECHS:
        return False
    unlocked_set = set(unlocked)
    locked_set = set(locked_out)
    if tech_id in unlocked_set or tech_id in locked_set:
        return False
    for prereq_id in TECHS[tech_id]["prereqs"]:
        if prereq_id in unlocked_set:
            continue
        # Any alternative in the prereq's tier_group will do.
        group = TECHS.get(prereq_id, {}).get("tier_group")
        if group and any(
            t.get("tier_group") == group and t["id"] in unlocked_set
            for t in TECHS.values()
        ):
            continue
        return False
    return True


# ---- Effect helpers (MAX semantics across unlocked techs) --------------

def empire_speed_bonus(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("speed_bonus", 0))
    return best


BASE_FUEL_RANGE = 6


def empire_fuel_range(unlocked):
    best = BASE_FUEL_RANGE
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("fuel_range", 0))
    return best


BASE_SENSOR_RANGE = 6


def empire_sensor_range(unlocked):
    best = BASE_SENSOR_RANGE
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("sensor_range", 0))
    return best


def empire_attack_bonus(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("attack_bonus", 0))
    return best


def empire_hull_bonus(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("hull_bonus", 0))
    return best


def empire_spy_offense(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("spy_offense", 0))
    return best


def empire_spy_defense(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("spy_defense", 0))
    return best


def empire_has_stealth(unlocked):
    return any(TECHS.get(t, {}).get("stealth") for t in unlocked)


def empire_has_mind_scan(unlocked):
    return any(TECHS.get(t, {}).get("mind_scan") for t in unlocked)


def empire_industry_per_worker(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("industry_per_worker", 0))
    return best


def empire_food_per_farmer(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("food_per_farmer", 0))
    return best


def empire_research_per_scientist(unlocked):
    best = 0
    for t in unlocked:
        best = max(best, TECHS.get(t, {}).get("research_per_scientist", 0))
    return best


def empire_marine_attack_bonus(unlocked) -> int:
    """Ground-combat tech contribution to attack per marine. SUM across
    unlocked techs — Powered Armor and any future marine-attack gear
    stack."""
    total = 0
    for t in unlocked:
        total += TECHS.get(t, {}).get("marine_attack", 0)
    return total


def empire_marine_defense_bonus(unlocked) -> int:
    """Ground-combat tech contribution to defense per defending militia
    unit. SUM — Powered Armor and Personal Shield are distinct layers."""
    total = 0
    for t in unlocked:
        total += TECHS.get(t, {}).get("marine_defense", 0)
    return total

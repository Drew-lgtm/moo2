import random
from ecs.components import Position, Name, Planet, Orbiting, StarVisual, StarRef, Empire, Owner, Population, BuildState, TechState, Ship, ShipOwner, ShipAt, ShipInTransit
from ecs.palette import EMPIRE_COLOR_RGB
from ecs.economy import compute_max_population, default_assignment, normalize_assignment
from ecs.personalities import AI_PERSONALITY_CYCLE
from assets.star_name_pool import load_star_names, get_random_star_name
from assets.loader import list_race_names
from ecs.races import RACE_ORDER, effective_traits, trait_count, CUSTOM_RACE_NAME
from ecs.planet_features import (
    random_richness, random_gravity, maybe_special_feature,
    parse_specials, specials_to_blob,
)
from ecs.galaxy_age import (
    DEFAULT_AGE, normalize_age,
    planet_type_weights as age_type_weights,
    richness_weights_habitable as age_rich_hab,
    richness_weights_mining as age_rich_min,
)
from ecs.db import (
    init_db,
    get_connection,
    insert_star,
    insert_planet,
    insert_empire,
    get_stars,
    get_planets_for_star,
    get_empires,
    get_meta,
    set_meta,
    get_planet_buildings,
    get_planet_build_queue,
    get_empire_techs,
    get_empire_locked_techs,
    get_ships,
)

META_TURN = "turn"
META_SEED = "seed"
META_DIFFICULTY = "difficulty"
META_GALAXY_AGE = "galaxy_age"
DEFAULT_DIFFICULTY = "normal"

STAR_CLASSES = [
    {"class": "O", "image": "green_star.png",  "weight": 0.01},
    {"class": "B", "image": "blue_star.png",   "weight": 0.03},
    {"class": "A", "image": "white_star.png",  "weight": 0.08},
    {"class": "F", "image": "yellow_star.png", "weight": 0.12},
    {"class": "G", "image": "yellow_star2.png","weight": 0.20},
    {"class": "K", "image": "orange_star.png", "weight": 0.25},
    {"class": "M", "image": "red_star.png",    "weight": 0.31},
]

HABITABLE_TYPES = ["Terran", "Ocean", "Swamp", "Jungle", "Arid", "Desert", "Tundra", "Steppe", "Barren", "Gaia"]
HOSTILE_TYPES = ["Radiated", "Toxic", "Inferno", "Volcanic"]
UNINHABITABLE_TYPES = ["Asteroids", "Gas Giant"]

ALL_TYPES = HABITABLE_TYPES + HOSTILE_TYPES + UNINHABITABLE_TYPES

SIZE_WEIGHTS = {
    "Tiny": 0.15, "Small": 0.25, "Medium": 0.35, "Large": 0.2, "Huge": 0.05,
}

PLANET_TYPE_WEIGHTS = {
    "Terran": 0.09, "Ocean": 0.08, "Swamp": 0.06, "Jungle": 0.07,
    "Arid": 0.08, "Desert": 0.07, "Tundra": 0.07, "Steppe": 0.06,
    "Barren": 0.04, "Gaia": 0.01,
    "Radiated": 0.05, "Toxic": 0.05, "Inferno": 0.03, "Volcanic": 0.03,
    "Asteroids": 0.06, "Gas Giant": 0.07,
}

EMPIRE_COLORS = list(EMPIRE_COLOR_RGB.keys())


def weighted_choice(choices):
    items = list(choices.keys())
    weights = list(choices.values())
    return random.choices(items, weights=weights, k=1)[0]


def choose_star_class():
    return random.choices(STAR_CLASSES, weights=[s["weight"] for s in STAR_CLASSES], k=1)[0]


class GalaxyGenerator:
    def __init__(self, entity_mgr, component_mgr, width, height, num_stars=20, y_offset=0):
        self.entity_mgr = entity_mgr
        self.component_mgr = component_mgr
        self.width = width
        self.height = height
        # Stars are placed at y in [y_offset + 50, y_offset + height - 50]
        # so they don't sit behind the top status bar.
        self.y_offset = y_offset
        self.num_stars = num_stars
        self.turn = 1
        self.seed = None
        self.difficulty = DEFAULT_DIFFICULTY
        self.galaxy_age = DEFAULT_AGE

    def generate(self, num_empires=2, seed=None, player_empire=None,
                 difficulty=DEFAULT_DIFFICULTY, galaxy_age=DEFAULT_AGE):
        """Create a fresh galaxy in the DB, then load it into ECS.

        If ``player_empire`` is provided, it lands on the first generated
        empire slot. Remaining slots are filled with random race/color
        picks that avoid the player's choices.
        """
        init_db()
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        self.seed = seed
        self.turn = 1
        self.difficulty = difficulty
        self.galaxy_age = normalize_age(galaxy_age)
        random.seed(seed)
        with get_connection() as conn:
            self._place_stars_and_planets(conn)
            self._assign_empires(conn, num_empires, player_empire)
            set_meta(conn, META_SEED, seed)
            set_meta(conn, META_TURN, self.turn)
            set_meta(conn, META_DIFFICULTY, self.difficulty)
            set_meta(conn, META_GALAXY_AGE, self.galaxy_age)
            conn.commit()
        self.load_from_db()

    def advance_turn(self):
        self.turn += 1
        with get_connection() as conn:
            set_meta(conn, META_TURN, self.turn)
            conn.commit()
        return self.turn

    def _place_stars_and_planets(self, conn):
        used_names = set()
        available_names = load_star_names()

        # Age-modified generation tables — computed once per generate().
        type_weights = age_type_weights(self.galaxy_age)
        rich_hab = age_rich_hab(self.galaxy_age)
        rich_min = age_rich_min(self.galaxy_age)

        MIN_STAR_DISTANCE = 60
        placed_positions = []

        placed = 0
        for _ in range(self.num_stars):
            for _attempt in range(100):
                x = random.randint(50, self.width - 50)
                y = random.randint(self.y_offset + 50, self.y_offset + self.height - 50)
                if all(((x - px) ** 2 + (y - py) ** 2) ** 0.5 >= MIN_STAR_DISTANCE for px, py in placed_positions):
                    placed_positions.append((x, y))
                    break
            else:
                continue

            name = get_random_star_name(used_names, available_names)
            used_names.add(name)

            star_info = choose_star_class()
            size = random.randint(20, 40)
            star_id = insert_star(conn, name, x, y, star_info["class"], star_info["image"], size)

            num_planets = random.choices([0, 1, 2, 3, 4, 5], weights=[0.05, 0.2, 0.3, 0.25, 0.15, 0.05])[0]
            for _ in range(num_planets):
                planet_type = weighted_choice(type_weights)
                planet_size = weighted_choice(SIZE_WEIGHTS)
                colonizable = planet_type in HABITABLE_TYPES
                richness = random_richness(
                    planet_type,
                    weights_habitable=rich_hab,
                    weights_mining=rich_min,
                )
                gravity = random_gravity(planet_size)
                feature = maybe_special_feature()
                special_blob = specials_to_blob([feature] if feature else [])
                insert_planet(
                    conn, star_id, planet_type, planet_size, colonizable,
                    richness=richness, gravity=gravity, special=special_blob,
                )
            placed += 1

        if placed < self.num_stars:
            print(f"[galaxy] Only placed {placed}/{self.num_stars} stars (min-distance constraint).")

    def _assign_empires(self, conn, num_empires, player_empire=None):
        stars = list(get_stars(conn))
        random.shuffle(stars)

        MIN_START_DISTANCE = 150
        chosen = []
        for star in stars:
            x, y = star["x"], star["y"]
            too_close = any(((x - s["x"]) ** 2 + (y - s["y"]) ** 2) ** 0.5 < MIN_START_DISTANCE for s in chosen)
            if too_close:
                continue
            chosen.append(star)
            if len(chosen) >= num_empires:
                break

        used_colors: set[str] = set()
        used_races: set[str] = set()
        # Prefer the curated RACE_ORDER catalog (15 races with bundled traits)
        # but fall back to filesystem scan if the catalog is somehow empty.
        all_races = list(RACE_ORDER) or list_race_names() or ["Humans"]

        for idx, star in enumerate(chosen):
            star_id = star["id"]
            conn.execute("DELETE FROM planets WHERE star_id = ?", (star_id,))

            if idx == 0 and player_empire is not None:
                emp_name = player_empire.name
                race = player_empire.race
                color = player_empire.color
                is_player = True
                personality = "balanced"
                custom_traits_str = ",".join(player_empire.custom_traits)
            else:
                color_pool = [c for c in EMPIRE_COLORS if c not in used_colors] or EMPIRE_COLORS
                race_pool = [r for r in all_races if r not in used_races] or all_races
                color = random.choice(color_pool)
                race = random.choice(race_pool)
                emp_name = f"Empire {idx + 1}"
                is_player = False
                # Cycle through AI personalities so up to 4 distinct AIs get
                # one each before any repeats. AI index = idx (with offset
                # depending on whether slot 0 was the player).
                ai_index = idx - 1 if player_empire is not None else idx
                personality = AI_PERSONALITY_CYCLE[ai_index % len(AI_PERSONALITY_CYCLE)]
                custom_traits_str = ""

            used_colors.add(color)
            used_races.add(race)

            tech = 1
            emp_id = insert_empire(
                conn, emp_name, race, color, star_id, tech,
                is_player=is_player, personality=personality,
                custom_traits=custom_traits_str,
            )

            # Apply trait bonuses that fire once at empire creation.
            traits = effective_traits(race, custom_traits_str)
            if "rich_homeworld" in traits:
                conn.execute(
                    "UPDATE empires SET bc = bc + 50 WHERE id = ?", (emp_id,)
                )

            home_max_pop = compute_max_population("Terran", "Medium")
            home_max_pop += 2 * trait_count(traits, "subterranean")
            home_farmers, home_workers, home_scientists = default_assignment("Terran", 2)
            # Homeworld is always Abundant / Normal — predictable starts.
            insert_planet(
                conn, star_id, "Terran", "Medium", True,
                owner_empire_id=emp_id,
                population=2,
                max_population=home_max_pop,
                farmers=home_farmers,
                workers=home_workers,
                scientists=home_scientists,
                richness="Abundant", gravity="Normal", special="",
            )

            type_weights = age_type_weights(self.galaxy_age)
            rich_hab = age_rich_hab(self.galaxy_age)
            rich_min = age_rich_min(self.galaxy_age)
            for _ in range(random.randint(1, 2)):
                pt = weighted_choice(type_weights)
                ps = weighted_choice(SIZE_WEIGHTS)
                rich = random_richness(pt, weights_habitable=rich_hab, weights_mining=rich_min)
                grav = random_gravity(ps)
                feat = maybe_special_feature()
                spec_blob = specials_to_blob([feat] if feat else [])
                insert_planet(
                    conn, star_id, pt, ps, pt in HABITABLE_TYPES,
                    richness=rich, gravity=grav, special=spec_blob,
                )

    def load_from_db(self):
        """Reconstruct ECS state from the DB without mutating it."""
        with get_connection() as conn:
            turn_str = get_meta(conn, META_TURN)
            seed_str = get_meta(conn, META_SEED)
            difficulty_str = get_meta(conn, META_DIFFICULTY)
            age_str = get_meta(conn, META_GALAXY_AGE)
            self.turn = int(turn_str) if turn_str is not None else 1
            self.seed = int(seed_str) if seed_str is not None else None
            self.difficulty = difficulty_str or DEFAULT_DIFFICULTY
            self.galaxy_age = normalize_age(age_str) if age_str else DEFAULT_AGE

            star_entity_by_db_id: dict[int, int] = {}
            for star in get_stars(conn):
                star_entity = self.entity_mgr.create_entity()
                star_entity_by_db_id[star["id"]] = star_entity
                self.component_mgr.add_component(star_entity, Position(star["x"], star["y"]))
                self.component_mgr.add_component(star_entity, Name(star["name"]))
                self.component_mgr.add_component(
                    star_entity, StarVisual(star["image"], star["size"], star["class"])
                )
                self.component_mgr.add_component(star_entity, StarRef(star["id"]))

                for planet in get_planets_for_star(star["id"], conn):
                    planet_entity = self.entity_mgr.create_entity()
                    # New columns may be missing on saves predating the
                    # richness/gravity/special migration — fall back to
                    # defaults if the row lookup raises.
                    try:
                        richness = planet["richness"] or "Abundant"
                    except (IndexError, KeyError):
                        richness = "Abundant"
                    try:
                        gravity = planet["gravity"] or "Normal"
                    except (IndexError, KeyError):
                        gravity = "Normal"
                    try:
                        special_blob = planet["special"] or ""
                    except (IndexError, KeyError):
                        special_blob = ""
                    self.component_mgr.add_component(
                        planet_entity,
                        Planet(
                            id=planet["id"],
                            planet_type=planet["type"],
                            size=planet["size"],
                            colonizable=bool(planet["colonizable"]),
                            richness=richness,
                            gravity=gravity,
                            special=parse_specials(special_blob),
                            original_race=(planet["original_race"]
                                            if "original_race" in planet.keys()
                                            else ""),
                            assimilation_progress=(
                                planet["assimilation_progress"]
                                if "assimilation_progress" in planet.keys()
                                else 100
                            ),
                            guerrilla_turns=(planet["guerrilla_turns"]
                                              if "guerrilla_turns" in planet.keys()
                                              else 0),
                            plague_turns=(planet["plague_turns"]
                                           if "plague_turns" in planet.keys()
                                           else 0),
                        ),
                    )
                    self.component_mgr.add_component(planet_entity, Orbiting(star_entity))
                    if planet["owner_empire_id"] is not None:
                        self.component_mgr.add_component(planet_entity, Owner(planet["owner_empire_id"]))
                    max_pop = planet["max_population"] or 0
                    if max_pop > 0:
                        pop = Population(
                            current=planet["population"] or 0,
                            max=max_pop,
                            growth_progress=planet["growth_progress"] or 0.0,
                            farmers=planet["farmers"] or 0,
                            workers=planet["workers"] or 0,
                            scientists=planet["scientists"] or 0,
                        )
                        # Old saves predate the worker columns: derive a default
                        # split from planet type instead of treating everyone as idle.
                        if pop.current > 0 and (pop.farmers + pop.workers + pop.scientists) == 0:
                            pop.farmers, pop.workers, pop.scientists = default_assignment(
                                planet["type"], pop.current
                            )
                        else:
                            normalize_assignment(pop)
                        self.component_mgr.add_component(planet_entity, pop)
                        completed = get_planet_buildings(conn, planet["id"])
                        queue = get_planet_build_queue(conn, planet["id"])
                        self.component_mgr.add_component(
                            planet_entity,
                            BuildState(
                                current_project=planet["current_project"],
                                progress=planet["project_progress"] or 0,
                                completed=completed,
                                queue=queue,
                                autobuild=(planet["autobuild"]
                                            if "autobuild" in planet.keys()
                                            else ""),
                            ),
                        )

            for emp in get_empires(conn):
                empire_entity = self.entity_mgr.create_entity()
                # custom_traits is a TEXT column; old rows might be NULL.
                try:
                    raw_traits = emp["custom_traits"] or ""
                except (IndexError, KeyError):
                    raw_traits = ""
                self.component_mgr.add_component(
                    empire_entity,
                    Empire(
                        id=emp["id"],
                        name=emp["name"],
                        race_type=emp["race_type"],
                        color=emp["color"],
                        tech_level=emp["tech_level"],
                        home_star_id=emp["home_star_id"],
                        bc=emp["bc"] or 0,
                        research_points=emp["research_points"] or 0,
                        is_player=bool(emp["is_player"]),
                        personality=emp["personality"] or "balanced",
                        custom_traits=raw_traits,
                    ),
                )
                self.component_mgr.add_component(
                    empire_entity,
                    TechState(
                        empire_id=emp["id"],
                        current_target=emp["tech_target"],
                        progress=emp["tech_progress"] or 0,
                        unlocked=get_empire_techs(conn, emp["id"]),
                        locked_out=get_empire_locked_techs(conn, emp["id"]),
                    ),
                )

            # Ships — created in production_tick on completion of a
            # type="ship" project. Each row reconstructs into a ship
            # entity with Ship + ShipOwner + (ShipAt | ShipInTransit).
            for ship_row in get_ships(conn):
                ship_entity = self.entity_mgr.create_entity()
                # `specials` is comma-separated tech ids; missing on
                # ships from older saves before the loadout migration.
                specials_str = ship_row["specials"] if "specials" in ship_row.keys() else ""
                specials_list = [s for s in (specials_str or "").split(",") if s]
                self.component_mgr.add_component(
                    ship_entity, Ship(
                        id=ship_row["id"],
                        ship_class=ship_row["ship_class"],
                        armor_tech=ship_row["armor_tech"] if "armor_tech" in ship_row.keys() else None,
                        shield_tech=ship_row["shield_tech"] if "shield_tech" in ship_row.keys() else None,
                        weapon_tech=ship_row["weapon_tech"] if "weapon_tech" in ship_row.keys() else None,
                        weapon_count=ship_row["weapon_count"] if "weapon_count" in ship_row.keys() else 0,
                        specials=specials_list,
                    )
                )
                self.component_mgr.add_component(
                    ship_entity, ShipOwner(empire_id=ship_row["owner_empire_id"])
                )
                if ship_row["dest_star_id"] is None:
                    star_eid = star_entity_by_db_id.get(ship_row["current_star_id"])
                    if star_eid is not None:
                        self.component_mgr.add_component(ship_entity, ShipAt(star_entity=star_eid))
                else:
                    from_eid = star_entity_by_db_id.get(ship_row["current_star_id"])
                    to_eid = star_entity_by_db_id.get(ship_row["dest_star_id"])
                    if from_eid is not None and to_eid is not None:
                        # Recompute total_turns from positions + class so the
                        # animation has a baseline (DB only stores remaining).
                        from ecs.fleet import turns_for as _turns_for
                        from_pos = self.component_mgr.get_component(from_eid, Position)
                        to_pos = self.component_mgr.get_component(to_eid, Position)
                        total = _turns_for(ship_row["ship_class"], from_pos, to_pos) if from_pos and to_pos else 0
                        self.component_mgr.add_component(
                            ship_entity,
                            ShipInTransit(
                                from_star_entity=from_eid,
                                to_star_entity=to_eid,
                                turns_remaining=ship_row["turns_remaining"] or 0,
                                total_turns=total,
                            ),
                        )

            # Outposts — restore claim components on the star entities.
            # Missing table (very old DBs) → silently skip.
            try:
                from ecs.db import get_outposts
                from ecs.components import Outpost
                for op in get_outposts(conn):
                    star_eid = star_entity_by_db_id.get(op["star_id"])
                    if star_eid is None:
                        continue
                    self.component_mgr.add_component(
                        star_eid, Outpost(empire_id=op["empire_id"])
                    )
            except Exception:
                pass

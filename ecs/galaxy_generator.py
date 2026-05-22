import random
from ecs.components import Position, Name, Planet, Orbiting, StarVisual, Empire, Owner
from assets.star_name_pool import load_star_names, get_random_star_name
from ecs.db import (
    init_db,
    get_connection,
    insert_star,
    insert_planet,
    insert_empire,
    get_stars,
    get_planets_for_star,
    get_empires,
)

STAR_CLASSES = [
    {"class": "O", "image": "green_star.png",  "weight": 0.01},
    {"class": "B", "image": "blue_star.png",   "weight": 0.03},
    {"class": "A", "image": "white_star.png",  "weight": 0.08},
    {"class": "F", "image": "yellow_star.png", "weight": 0.12},
    {"class": "G", "image": "yellow_star2.png","weight": 0.20},
    {"class": "K", "image": "orange_star.png", "weight": 0.25},
    {"class": "M", "image": "red_star.png",    "weight": 0.31},
]

HABITABLE_TYPES = ["Terran", "Ocean", "Jungle", "Arid", "Desert", "Tundra", "Steppe", "Barren", "Gaia"]
HOSTILE_TYPES = ["Radiated", "Toxic", "Inferno", "Volcanic"]
UNINHABITABLE_TYPES = ["Asteroids", "Gas Giant"]

ALL_TYPES = HABITABLE_TYPES + HOSTILE_TYPES + UNINHABITABLE_TYPES

SIZE_WEIGHTS = {
    "Tiny": 0.15, "Small": 0.25, "Medium": 0.35, "Large": 0.2, "Huge": 0.05,
}

PLANET_TYPE_WEIGHTS = {
    "Terran": 0.10, "Ocean": 0.10, "Jungle": 0.08, "Arid": 0.08, "Desert": 0.07,
    "Tundra": 0.07, "Steppe": 0.06, "Barren": 0.04, "Gaia": 0.01,
    "Radiated": 0.05, "Toxic": 0.05, "Inferno": 0.03, "Volcanic": 0.03,
    "Asteroids": 0.06, "Gas Giant": 0.07,
}

EMPIRE_COLORS = ["blue", "red", "green", "yellow", "purple", "orange"]


def weighted_choice(choices):
    items = list(choices.keys())
    weights = list(choices.values())
    return random.choices(items, weights=weights, k=1)[0]


def choose_star_class():
    return random.choices(STAR_CLASSES, weights=[s["weight"] for s in STAR_CLASSES], k=1)[0]


class GalaxyGenerator:
    def __init__(self, entity_mgr, component_mgr, width, height, num_stars=20):
        self.entity_mgr = entity_mgr
        self.component_mgr = component_mgr
        self.width = width
        self.height = height
        self.num_stars = num_stars

    def generate(self, num_empires=2):
        """Create a fresh galaxy in the DB, then load it into ECS."""
        init_db()
        with get_connection() as conn:
            self._place_stars_and_planets(conn)
            self._assign_empires(conn, num_empires)
            conn.commit()
        self.load_from_db()

    def _place_stars_and_planets(self, conn):
        used_names = set()
        available_names = load_star_names()

        MIN_STAR_DISTANCE = 60
        placed_positions = []

        placed = 0
        for _ in range(self.num_stars):
            for _attempt in range(100):
                x = random.randint(50, self.width - 50)
                y = random.randint(50, self.height - 50)
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
                planet_type = weighted_choice(PLANET_TYPE_WEIGHTS)
                planet_size = weighted_choice(SIZE_WEIGHTS)
                colonizable = planet_type in HABITABLE_TYPES
                insert_planet(conn, star_id, planet_type, planet_size, colonizable)
            placed += 1

        if placed < self.num_stars:
            print(f"[galaxy] Only placed {placed}/{self.num_stars} stars (min-distance constraint).")

    def _assign_empires(self, conn, num_empires):
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

        for idx, star in enumerate(chosen):
            star_id = star["id"]

            conn.execute("DELETE FROM planets WHERE star_id = ?", (star_id,))

            race = "Human"
            color = EMPIRE_COLORS[idx % len(EMPIRE_COLORS)]
            emp_name = f"Empire {idx + 1}"
            tech = 1
            emp_id = insert_empire(conn, emp_name, race, color, star_id, tech)

            insert_planet(conn, star_id, "Terran", "Medium", True, owner_empire_id=emp_id)

            for _ in range(random.randint(1, 2)):
                pt = weighted_choice(PLANET_TYPE_WEIGHTS)
                ps = weighted_choice(SIZE_WEIGHTS)
                insert_planet(conn, star_id, pt, ps, pt in HABITABLE_TYPES)

    def load_from_db(self):
        """Reconstruct ECS state from the DB without mutating it."""
        with get_connection() as conn:
            star_entity_by_db_id = {}

            for star in get_stars(conn):
                star_entity = self.entity_mgr.create_entity()
                star_entity_by_db_id[star["id"]] = star_entity
                self.component_mgr.add_component(star_entity, Position(star["x"], star["y"]))
                self.component_mgr.add_component(star_entity, Name(star["name"]))
                self.component_mgr.add_component(
                    star_entity, StarVisual(star["image"], star["size"], star["class"])
                )

                for planet in get_planets_for_star(star["id"], conn):
                    planet_entity = self.entity_mgr.create_entity()
                    self.component_mgr.add_component(
                        planet_entity,
                        Planet(planet["type"], planet["size"], bool(planet["colonizable"])),
                    )
                    self.component_mgr.add_component(planet_entity, Orbiting(star_entity))
                    if planet["owner_empire_id"] is not None:
                        self.component_mgr.add_component(planet_entity, Owner(planet["owner_empire_id"]))

            for emp in get_empires(conn):
                empire_entity = self.entity_mgr.create_entity()
                self.component_mgr.add_component(
                    empire_entity,
                    Empire(
                        emp["name"],
                        emp["race_type"],
                        emp["color"],
                        emp["tech_level"],
                        emp["home_star_id"],
                    ),
                )

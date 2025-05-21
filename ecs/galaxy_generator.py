import random
from ecs.components import Position, Name, Planet, Orbiting, StarVisual
from assets.star_name_pool import load_star_names, get_random_star_name
from ecs.db import init_db, insert_star, insert_planet, get_stars, get_planets_for_star

STAR_CLASSES = [
    {"class": "O", "image": "green_star.png",  "weight": 0.01},
    {"class": "B", "image": "blue_star.png",   "weight": 0.03},
    {"class": "A", "image": "white_star.png",  "weight": 0.08},
    {"class": "F", "image": "yellow_star.png", "weight": 0.12},
    {"class": "G", "image": "yellow_star2.png","weight": 0.20},
    {"class": "K", "image": "orange_star.png", "weight": 0.25},
    {"class": "M", "image": "red_star.png",    "weight": 0.31}
]

HABITABLE_TYPES = ["Terran", "Ocean", "Jungle", "Arid", "Desert", "Tundra", "Steppe", "Barren", "Gaia"]
HOSTILE_TYPES = ["Radiated", "Toxic", "Inferno", "Volcanic"]
UNINHABITABLE_TYPES = ["Asteroids", "Gas Giant"]

ALL_TYPES = HABITABLE_TYPES + HOSTILE_TYPES + UNINHABITABLE_TYPES

SIZE_WEIGHTS = {
    "Tiny": 0.15, "Small": 0.25, "Medium": 0.35, "Large": 0.2, "Huge": 0.05
}

PLANET_TYPE_WEIGHTS = {
    "Terran": 0.10, "Ocean": 0.10, "Jungle": 0.08, "Arid": 0.08, "Desert": 0.07,
    "Tundra": 0.07, "Steppe": 0.06, "Barren": 0.04, "Gaia": 0.01,
    "Radiated": 0.05, "Toxic": 0.05, "Inferno": 0.03, "Volcanic": 0.03,
    "Asteroids": 0.06, "Gas Giant": 0.07
}

def weighted_choice(choices):
    from random import choices as pick
    items = list(choices.keys())
    weights = list(choices.values())
    return pick(items, weights=weights, k=1)[0]

def choose_star_class():
    from random import choices
    return choices(STAR_CLASSES, weights=[s["weight"] for s in STAR_CLASSES], k=1)[0]

class GalaxyGenerator:
    def __init__(self, entity_mgr, component_mgr, width, height, num_stars=20):
        self.entity_mgr = entity_mgr
        self.component_mgr = component_mgr
        self.width = width
        self.height = height
        self.num_stars = num_stars

    def generate(self):
        init_db()
        used_names = set()
        available_names = load_star_names()

        MIN_STAR_DISTANCE = 60
        placed_positions = []

        for _ in range(self.num_stars):
            for attempt in range(100):
                x = random.randint(50, self.width - 50)
                y = random.randint(50, self.height - 50)
                if all(((x - px)**2 + (y - py)**2)**0.5 >= MIN_STAR_DISTANCE for px, py in placed_positions):
                    placed_positions.append((x, y))
                    break
            else:
                continue

            name = get_random_star_name(used_names, available_names)
            used_names.add(name)

            star_info = choose_star_class()
            image = star_info["image"]
            star_class = star_info["class"]
            size = random.randint(20, 40)

            star_id = insert_star(name, x, y, star_class, image, size)

            num_planets = random.choices([0,1,2,3,4,5], weights=[0.05,0.2,0.3,0.25,0.15,0.05])[0]
            for _ in range(num_planets):
                planet_type = weighted_choice(PLANET_TYPE_WEIGHTS)
                planet_size = weighted_choice(SIZE_WEIGHTS)
                colonizable = planet_type in HABITABLE_TYPES
                insert_planet(star_id, planet_type, planet_size, colonizable)

        self.load_from_db()

    def load_from_db(self):
        for star_row in get_stars():
            db_id, name, x, y, star_class, image, size = star_row
            star_entity = self.entity_mgr.create_entity()
            self.component_mgr.add_component(star_entity, Position(x, y))
            self.component_mgr.add_component(star_entity, Name(name))
            self.component_mgr.add_component(star_entity, StarVisual(image, size, star_class))

            for planet_row in get_planets_for_star(db_id):
                _, _, planet_type, planet_size, colonizable = planet_row
                planet_entity = self.entity_mgr.create_entity()
                self.component_mgr.add_component(planet_entity, Planet(planet_type, planet_size, bool(colonizable)))
                self.component_mgr.add_component(planet_entity, Orbiting(star_entity))

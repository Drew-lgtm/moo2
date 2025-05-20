import random
from ecs.components import Position, Name, Owner, Planet, Orbiting, StarVisual
from assets.star_name_pool import load_star_names, get_random_star_name

STAR_IMAGES = ["white_star.png", "red_star.png", "blue_star.png"]
STAR_SIZE_RANGE = (20, 40)
STAR_CLASSES = [
    {"class": "O", "image": "green_star.png",  "weight": 0.01}, # should be blue but what the heck
    {"class": "B", "image": "blue_star.png",  "weight": 0.03},
    {"class": "A", "image": "white_star.png", "weight": 0.08},
    {"class": "F", "image": "yellow_star.png", "weight": 0.12},
    {"class": "G", "image": "yellow_star2.png", "weight": 0.20},
    {"class": "K", "image": "orange_star.png",   "weight": 0.25},
    {"class": "M", "image": "red_star.png",   "weight": 0.31}
]
def choose_star_class():
    from random import choices
    classes = [entry["class"] for entry in STAR_CLASSES]
    weights = [entry["weight"] for entry in STAR_CLASSES]
    return choices(STAR_CLASSES, weights=weights, k=1)[0]


# Planet environment categories
HABITABLE_TYPES = ["Terran", "Ocean", "Jungle", "Arid", "Desert", "Tundra", "Steppe", "Barren", "Gaia"]
HOSTILE_TYPES = ["Radiated", "Toxic", "Inferno", "Volcanic"]
UNINHABITABLE_TYPES = ["Asteroids", "Gas Giant"]

ALL_TYPES = HABITABLE_TYPES + HOSTILE_TYPES + UNINHABITABLE_TYPES

# Rarity
SIZE_WEIGHTS = {
    "Tiny": 0.15,
    "Small": 0.25,
    "Medium": 0.35,
    "Large": 0.2,
    "Huge": 0.05
}

PLANET_TYPE_WEIGHTS = {
    # Habitable (more common)
    "Terran": 0.10,
    "Ocean": 0.10,
    "Jungle": 0.08,
    "Arid": 0.08,
    "Desert": 0.07,
    "Tundra": 0.07,
    "Steppe": 0.06,
    "Barren": 0.04,
    "Gaia": 0.01,  # Rare

    # Hostile (uncommon, needs tech)
    "Radiated": 0.05,
    "Toxic": 0.05,
    "Inferno": 0.03,
    "Volcanic": 0.03,

    # Uninhabitable (rare, strategic)
    "Asteroids": 0.06,
    "Gas Giant": 0.07,
}


def weighted_choice(choices):
    from random import choices as pick
    items = list(choices.keys())
    weights = list(choices.values())
    return pick(items, weights=weights, k=1)[0]

class GalaxyGenerator:
    def __init__(self, entity_mgr, component_mgr, width, height, num_stars=20):
        self.entity_mgr = entity_mgr
        self.component_mgr = component_mgr
        self.width = width
        self.height = height
        self.num_stars = num_stars

    def generate(self):
        used_names = set()
        available_names = load_star_names()

        MIN_STAR_DISTANCE = 60  # pixels between star centers
        placed_positions = []

        for _ in range(self.num_stars):
            for attempt in range(100):  # Try 100 times to place this star
                x = random.randint(50, self.width - 50)
                y = random.randint(50, self.height - 50)

                too_close = any(
                    (abs(x - px) ** 2 + abs(y - py) ** 2) ** 0.5 < MIN_STAR_DISTANCE
                    for px, py in placed_positions
                )
                if not too_close:
                    placed_positions.append((x, y))
                    break
            else:
                continue  # If no suitable spot found after 100 tries, skip this star

            name = get_random_star_name(used_names, available_names)
            used_names.add(name)

            star_entity = self.entity_mgr.create_entity()
            self.component_mgr.add_component(star_entity, Position(x, y))
            self.component_mgr.add_component(star_entity, Name(name))

            # Planet generation for star system
            star_info = choose_star_class()
            image_name = star_info["image"]
            star_class = star_info["class"]
            size = random.randint(*STAR_SIZE_RANGE)
            self.component_mgr.add_component(star_entity, StarVisual(image_name, size, star_class))

            num_planets = random.choices([0, 1, 2, 3, 4, 5], weights=[0.05, 0.2, 0.3, 0.25, 0.15, 0.05])[0]
            for _ in range(num_planets):
                planet_type = weighted_choice(PLANET_TYPE_WEIGHTS)
                planet_size = weighted_choice(SIZE_WEIGHTS)
                colonizable = planet_type in HABITABLE_TYPES

                planet_entity = self.entity_mgr.create_entity()
                self.component_mgr.add_component(planet_entity, Planet(planet_type, planet_size, colonizable))
                self.component_mgr.add_component(planet_entity, Orbiting(star_entity))

            # Debug
            print(f"{name} has {num_planets} planet(s)")

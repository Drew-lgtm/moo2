"""Shared color palettes used across scenes.

Kept here so SystemView and the panel scenes don't drift apart.
"""

# Per-type planet colors. Aim for thematic, immediately-readable hues
# against the black system-view background: cold biomes lean blue/white,
# hot ones red/orange, fertile ones green, hostile ones sickly. Used as
# both the system-view planet disc and the small status dot in colony /
# panel rows.
PLANET_COLORS = {
    # Habitable (cool, life-friendly).
    "Terran":    (90, 150, 220),   # earth blue with continents
    "Ocean":     (40, 110, 210),   # deep ocean blue
    "Jungle":    (40, 150, 60),    # lush dark green
    "Swamp":     (100, 120, 70),   # muddy olive
    "Steppe":    (170, 200, 130),  # pale grass
    "Arid":      (200, 150, 80),   # warm tan
    "Desert":    (240, 210, 90),   # golden yellow sand
    "Tundra":    (220, 230, 250),  # icy frost white-blue
    "Barren":    (140, 130, 120),  # rocky brown-grey
    "Gaia":      (60, 170, 80),    # rich saturated golf-course green
    # Hostile (visually warn the player they're not freebies).
    "Radiated":  (200, 80, 200),   # sickly magenta glow
    "Toxic":     (190, 80, 60),    # noxious red-brown
    "Volcanic":  (200, 60, 30),    # molten dark red
    "Inferno":   (255, 90, 30),    # blazing fire orange
    # Uncolonisable.
    "Asteroids": (130, 120, 110),  # cold rocky grey
    "Gas Giant": (200, 170, 130),  # Jupiter-like banded tan
}
PLANET_COLOR_DEFAULT = (200, 200, 200)


EMPIRE_COLOR_RGB = {
    "blue":   (80, 130, 255),
    "red":    (240, 60, 60),
    "green":  (60, 200, 80),
    "yellow": (240, 220, 80),
    "purple": (180, 80, 220),
    "orange": (240, 140, 60),
    "white":  (235, 235, 245),
    "cyan":   (80, 220, 220),
    "pink":   (240, 130, 200),
}
EMPIRE_COLOR_DEFAULT = (180, 180, 180)


def planet_color(planet_type: str):
    return PLANET_COLORS.get(planet_type, PLANET_COLOR_DEFAULT)


def empire_color(color_name: str):
    return EMPIRE_COLOR_RGB.get(color_name, EMPIRE_COLOR_DEFAULT)

"""Shared color palettes used across scenes.

Kept here so SystemView and the panel scenes don't drift apart.
"""

PLANET_COLORS = {
    "Terran":    (100, 200, 255),
    "Ocean":     (80, 160, 255),
    "Jungle":    (50, 180, 50),
    "Arid":      (210, 180, 100),
    "Desert":    (230, 200, 120),
    "Tundra":    (180, 180, 220),
    "Steppe":    (160, 200, 140),
    "Barren":    (150, 150, 150),
    "Gaia":      (0, 255, 0),
    "Radiated":  (255, 100, 255),
    "Toxic":     (255, 80, 80),
    "Inferno":   (255, 50, 0),
    "Volcanic":  (255, 100, 0),
    "Asteroids": (100, 100, 100),
    "Gas Giant": (120, 120, 255),
}
PLANET_COLOR_DEFAULT = (200, 200, 200)


EMPIRE_COLOR_RGB = {
    "blue":   (80, 130, 255),
    "red":    (240, 60, 60),
    "green":  (60, 200, 80),
    "yellow": (240, 220, 80),
    "purple": (180, 80, 220),
    "orange": (240, 140, 60),
}
EMPIRE_COLOR_DEFAULT = (180, 180, 180)


def planet_color(planet_type: str):
    return PLANET_COLORS.get(planet_type, PLANET_COLOR_DEFAULT)


def empire_color(color_name: str):
    return EMPIRE_COLOR_RGB.get(color_name, EMPIRE_COLOR_DEFAULT)

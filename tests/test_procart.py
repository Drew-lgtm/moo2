"""Procedural placeholder art: every planet biome and ship hull renders,
and a given world always looks the same."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from ecs.palette import PLANET_COLORS
from ecs.ships import SHIPS


@pytest.fixture(autouse=True)
def _display():
    pygame.display.quit()
    pygame.init()
    pygame.display.set_mode((320, 240))
    from assets.procart import clear_cache
    clear_cache()
    yield
    clear_cache()
    pygame.display.quit()


def _png(surface):
    return pygame.image.tostring(surface, "RGBA")


# ---- planets -----------------------------------------------------------

def test_every_biome_renders():
    from assets.procart import planet_surface
    for biome in PLANET_COLORS:
        surf = planet_surface(biome, 14, seed=3)
        assert surf.get_size() == (30, 30), biome


def test_unknown_biome_still_renders():
    """Never crash on a biome the art module hasn't heard of."""
    from assets.procart import planet_surface
    assert planet_surface("Klingon Paradise", 10, seed=1) is not None


def test_tiny_and_large_radii_are_safe():
    from assets.procart import planet_surface
    for r in (1, 2, 3, 60):
        assert planet_surface("Terran", r, seed=1) is not None


def test_same_planet_always_looks_the_same():
    """Seeded from the planet id, so a world is stable across redraws and
    across save/load."""
    from assets.procart import planet_surface, clear_cache
    first = _png(planet_surface("Terran", 12, seed=7))
    clear_cache()
    assert _png(planet_surface("Terran", 12, seed=7)) == first


def test_different_planets_look_different():
    from assets.procart import planet_surface
    a = _png(planet_surface("Terran", 12, seed=7))
    b = _png(planet_surface("Terran", 12, seed=8))
    assert a != b


def test_biomes_are_visually_distinct():
    from assets.procart import planet_surface
    a = _png(planet_surface("Ocean", 12, seed=1))
    b = _png(planet_surface("Inferno", 12, seed=1))
    assert a != b


def test_repeat_calls_are_cached():
    from assets.procart import planet_surface
    assert planet_surface("Gaia", 10, seed=2) is planet_surface("Gaia", 10, seed=2)


# ---- ships -------------------------------------------------------------

def test_every_ship_class_has_a_silhouette():
    from assets.procart import ship_surface
    for cls in SHIPS:
        surf = ship_surface(cls, 24, (200, 80, 80))
        assert surf.get_size() == (24, 24), cls


def test_hull_classes_are_visually_distinct():
    from assets.procart import ship_surface
    frigate = _png(ship_surface("frigate", 24, (200, 80, 80)))
    doom = _png(ship_surface("doom_star", 24, (200, 80, 80)))
    assert frigate != doom


def test_empire_colour_changes_the_sprite():
    from assets.procart import ship_surface
    red = _png(ship_surface("cruiser", 24, (200, 60, 60)))
    blue = _png(ship_surface("cruiser", 24, (60, 60, 200)))
    assert red != blue


def test_unknown_hull_falls_back():
    from assets.procart import ship_surface
    assert ship_surface("alien_mothership", 20, (255, 255, 255)) is not None

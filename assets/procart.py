"""Procedurally generated placeholder art.

Most of the shipped PNGs are 0-byte stubs, and hand-drawn art isn't
coming soon, so we draw what we need instead: biome-tinted planet discs
and per-hull ship silhouettes. Generated once and cached, so the cost is
a handful of surfaces at startup rather than per frame.

Everything here is **deterministic** — a planet's surface detail is
seeded from its id, so the same world looks the same every time you open
it (and across save/load). Nothing here reads game state; callers pass in
the type, size and seed they want.
"""
from __future__ import annotations

import math
import random

import pygame

from ecs.palette import planet_color


_planet_cache: dict[tuple, pygame.Surface] = {}
_ship_cache: dict[tuple, pygame.Surface] = {}


# ---- helpers -----------------------------------------------------------

def _shade(color, factor: float):
    """Lighten (factor>1) or darken (factor<1) an RGB colour, clamped."""
    return tuple(max(0, min(255, int(c * factor))) for c in color[:3])


def _biome_detail(planet_type: str) -> str:
    """Which surface treatment a biome gets."""
    t = planet_type
    if t in ("Gas Giant",):
        return "bands"
    if t in ("Asteroids",):
        return "rubble"
    if t in ("Ocean", "Terran", "Gaia", "Swamp", "Jungle"):
        return "continents"
    if t in ("Barren", "Radiated", "Toxic", "Inferno", "Volcanic"):
        return "craters"
    return "mottle"          # Desert, Tundra, Arid, Steppe, …


# ---- planets -----------------------------------------------------------

def planet_surface(planet_type: str, radius: int, seed: int = 0) -> pygame.Surface:
    """A round planet ``radius`` px in radius, tinted for its biome, with
    light surface detail and day/night shading. Cached per
    (type, radius, seed)."""
    key = (planet_type, radius, seed)
    cached = _planet_cache.get(key)
    if cached is not None:
        return cached

    r = max(3, int(radius))
    size = r * 2 + 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = r + 1
    base = planet_color(planet_type)
    rng = random.Random(seed * 7919 + hash(planet_type) % 10007)

    # Body.
    pygame.draw.circle(surf, base, (cx, cy), r)

    detail = _biome_detail(planet_type)
    dark = _shade(base, 0.72)
    light = _shade(base, 1.25)

    if detail == "bands":
        # Horizontal cloud bands, thickest near the equator.
        for i in range(-r, r, max(2, r // 4)):
            band_w = int(math.sqrt(max(0, r * r - i * i)))
            if band_w <= 1:
                continue
            tone = light if (i // max(2, r // 4)) % 2 == 0 else dark
            pygame.draw.line(surf, tone, (cx - band_w, cy + i),
                             (cx + band_w, cy + i), max(1, r // 6))
    elif detail == "continents":
        for _ in range(max(2, r // 3)):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(0, r * 0.62)
            blob_r = max(2, int(rng.uniform(r * 0.18, r * 0.42)))
            px = int(cx + math.cos(a) * d)
            py = int(cy + math.sin(a) * d)
            pygame.draw.circle(surf, light, (px, py), blob_r)
    elif detail == "craters":
        for _ in range(max(3, r // 2)):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(0, r * 0.7)
            cr = max(1, int(rng.uniform(1, max(2, r * 0.2))))
            px = int(cx + math.cos(a) * d)
            py = int(cy + math.sin(a) * d)
            pygame.draw.circle(surf, dark, (px, py), cr)
    elif detail == "rubble":
        # Asteroid belts: a scatter of rocks instead of a solid body.
        surf.fill((0, 0, 0, 0))
        for _ in range(max(5, r)):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(r * 0.25, r)
            rock = max(1, int(rng.uniform(1, max(2, r * 0.25))))
            px = int(cx + math.cos(a) * d * 0.9)
            py = int(cy + math.sin(a) * d * 0.45)
            pygame.draw.circle(surf, base if rng.random() < 0.6 else dark,
                               (px, py), rock)
    else:  # mottle
        for _ in range(max(3, r // 2)):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(0, r * 0.66)
            blob = max(1, int(rng.uniform(1, max(2, r * 0.3))))
            px = int(cx + math.cos(a) * d)
            py = int(cy + math.sin(a) * d)
            pygame.draw.circle(surf, dark if rng.random() < 0.5 else light,
                               (px, py), blob)

    if detail != "rubble":
        # Day/night terminator: a soft dark crescent on the lower-right,
        # clipped to the disc so the planet still reads as a sphere.
        shadow = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(shadow, (0, 0, 0, 90), (cx + r // 3, cy + r // 4), r)
        mask = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255, 255), (cx, cy), r)
        shadow.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        surf.blit(shadow, (0, 0))
        # Rim light on the sunward edge.
        pygame.draw.circle(surf, _shade(base, 1.4), (cx, cy), r, 1)

    _planet_cache[key] = surf
    return surf


# ---- ships -------------------------------------------------------------
#
# Silhouettes are unit polygons in a -1..1 box, pointing right (+x), so a
# hull reads the same at any size. Bigger classes get busier outlines.

_HULLS: dict[str, list[tuple[float, float]]] = {
    "frigate":       [(1.0, 0.0), (-0.6, -0.55), (-0.3, 0.0), (-0.6, 0.55)],
    "carrier":       [(0.9, -0.3), (0.9, 0.3), (-0.2, 0.75), (-0.9, 0.5),
                      (-0.9, -0.5), (-0.2, -0.75)],
    "cruiser":       [(1.0, 0.0), (0.1, -0.5), (-0.7, -0.6), (-0.45, 0.0),
                      (-0.7, 0.6), (0.1, 0.5)],
    "battleship":    [(1.0, -0.15), (1.0, 0.15), (0.2, 0.6), (-0.8, 0.55),
                      (-0.55, 0.0), (-0.8, -0.55), (0.2, -0.6)],
    "dreadnought":   [(1.0, 0.0), (0.5, -0.35), (0.55, -0.7), (-0.3, -0.75),
                      (-0.85, -0.4), (-0.6, 0.0), (-0.85, 0.4),
                      (-0.3, 0.75), (0.55, 0.7), (0.5, 0.35)],
    "titan":         [(1.0, 0.0), (0.6, -0.45), (0.7, -0.8), (-0.2, -0.9),
                      (-0.9, -0.5), (-0.65, 0.0), (-0.9, 0.5),
                      (-0.2, 0.9), (0.7, 0.8), (0.6, 0.45)],
    "doom_star":     [(1.0, 0.25), (1.0, -0.25), (0.35, -0.75), (-0.45, -0.95),
                      (-1.0, -0.45), (-0.75, 0.0), (-1.0, 0.45),
                      (-0.45, 0.95), (0.35, 0.75)],
    # Civilians read as blunt, unarmed shapes.
    "colony_ship":   [(0.8, -0.45), (0.8, 0.45), (-0.8, 0.6), (-0.8, -0.6)],
    "outpost_ship":  [(0.75, -0.4), (0.75, 0.4), (-0.75, 0.55), (-0.75, -0.55)],
    "freighter":     [(0.85, -0.35), (0.85, 0.35), (-0.85, 0.5), (-0.85, -0.5)],
    "troop_transport": [(0.9, 0.0), (0.2, -0.6), (-0.85, -0.5),
                        (-0.85, 0.5), (0.2, 0.6)],
    "scout":         [(1.0, 0.0), (-0.7, -0.4), (-0.4, 0.0), (-0.7, 0.4)],
}
_DEFAULT_HULL = _HULLS["frigate"]


def ship_surface(ship_class: str, size: int, color) -> pygame.Surface:
    """A ship silhouette ``size`` px wide in the empire's colour, pointing
    right. Cached per (class, size, colour)."""
    col = tuple(color[:3])
    key = (ship_class, size, col)
    cached = _ship_cache.get(key)
    if cached is not None:
        return cached

    s = max(6, int(size))
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    half = s / 2.0
    poly = _HULLS.get(ship_class, _DEFAULT_HULL)
    pts = [(half + x * (half - 1), half + y * (half - 1)) for x, y in poly]

    pygame.draw.polygon(surf, col, pts)
    pygame.draw.polygon(surf, _shade(col, 0.45), pts, max(1, s // 16))
    # A bright spine suggests a hull rather than a flat blob.
    pygame.draw.line(surf, _shade(col, 1.5),
                     (half * 0.2, half), (half * 1.6, half),
                     max(1, s // 14))

    _ship_cache[key] = surf
    return surf


def clear_cache():
    """Drop cached surfaces (used by tests; the display mode changing
    invalidates converted surfaces)."""
    _planet_cache.clear()
    _ship_cache.clear()

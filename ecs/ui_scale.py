"""Display scaling — crisp text and hairlines at any panel resolution.

The game was originally drawn on a fixed 1200x800 canvas that pygame
stretched to fill the display (``pygame.SCALED``). That stretch is
*fractional* on every common laptop panel — 1920x1080 needs 1.35x,
2560x1440 needs 1.8x, 2880x1800 needs 2.25x — so every glyph and every
one-pixel line was resampled into a soft grey smear. The old workaround
was to set ``bold=True`` on every font so strokes survived the blur,
which made text heavy and muddy rather than legible.

Instead we now render **1:1 at the panel's native resolution** (no
resampling at all) and scale the interface itself:

- ``SCALE`` is the panel height over the 800px design height.
- ``s(px)`` converts a design-space measurement to device pixels.
- ``get_font(size)`` returns a cached font scaled the same way, at
  regular weight — thin strokes are safe now that nothing is resampled.

Net effect: text occupies the same physical space it always did, but
every stroke lands on a real pixel, so it reads sharp instead of soft.
"""
from __future__ import annotations

import pygame


# The canvas the UI was laid out against. Scaling is relative to this.
DESIGN_WIDTH = 1200
DESIGN_HEIGHT = 800

# Clamped so a very small panel can't shrink text below legibility and a
# 4K panel can't blow the layout apart.
MIN_SCALE = 0.85
MAX_SCALE = 2.50

SCALE = 1.0
_font_cache: dict[tuple[str, int, bool], pygame.font.Font] = {}


def detect_scale(screen_width: int, screen_height: int) -> float:
    """UI scale for a panel of this size, relative to the design canvas.

    Driven by height (the dimension that limits a 16:9 or 16:10 laptop),
    then held back slightly by width so an ultrawide doesn't overflow
    horizontally.
    """
    by_height = screen_height / DESIGN_HEIGHT
    by_width = screen_width / DESIGN_WIDTH
    scale = min(by_height, by_width * 1.15)
    return max(MIN_SCALE, min(MAX_SCALE, scale))


def set_scale(scale: float):
    """Adopt a new UI scale and drop cached fonts built at the old one."""
    global SCALE
    SCALE = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
    _font_cache.clear()


def s(px: float) -> int:
    """Design-space pixels -> device pixels, rounded to a whole pixel so
    edges stay sharp."""
    return int(round(px * SCALE))


def line_width(px: float = 1) -> int:
    """Stroke width in device pixels, never thinner than a hairline.

    A 1px design stroke stays 1px until the scale is high enough to carry
    a genuine 2px line, so borders read as crisp rules rather than fuzzy
    bands.
    """
    return max(1, int(px * SCALE))


def get_font(size: int, bold: bool = False,
             name: str = "Arial") -> pygame.font.Font:
    """A cached UI font, scaled to the display.

    Regular weight by default: at native resolution thin strokes render
    cleanly, and regular text is markedly easier to read than the bold
    everything the fractional-scaling era required. Pass ``bold=True``
    only for genuine emphasis (titles, the active selection).
    """
    px = max(9, s(size))
    key = (name, px, bold)
    font = _font_cache.get(key)
    if font is None:
        font = pygame.font.SysFont(name, px, bold=bold)
        _font_cache[key] = font
    return font

"""UI scaling: the game renders 1:1 at the panel's native resolution and
scales the interface, instead of stretching a fixed canvas (which blurred
every glyph and hairline on any non-integer scale factor)."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from ecs import ui_scale
from ecs.ui_scale import (
    detect_scale, set_scale, s, line_width, get_font,
    DESIGN_WIDTH, DESIGN_HEIGHT, MIN_SCALE, MAX_SCALE,
)


@pytest.fixture(autouse=True)
def _restore_scale():
    pygame.init()
    original = ui_scale.SCALE
    yield
    set_scale(original)


# ---- scale detection ---------------------------------------------------

def test_design_resolution_is_unscaled():
    assert detect_scale(DESIGN_WIDTH, DESIGN_HEIGHT) == pytest.approx(1.0)


def test_bigger_panels_scale_up():
    """A 1080p laptop must not render 14px text — it would be tiny."""
    assert detect_scale(1920, 1080) > 1.2
    assert detect_scale(2880, 1800) > detect_scale(1920, 1080)


def test_scale_is_clamped_both_ways():
    assert detect_scale(320, 240) >= MIN_SCALE
    assert detect_scale(7680, 4320) <= MAX_SCALE


def test_ultrawide_is_held_back_by_height():
    """A short, very wide panel shouldn't blow the layout up vertically."""
    assert detect_scale(3440, 1440) <= detect_scale(2560, 1440) * 1.2


# ---- measurements ------------------------------------------------------

def test_s_returns_whole_pixels():
    set_scale(1.35)
    for px in (1, 7, 14, 56, 300):
        assert isinstance(s(px), int)


def test_s_scales_proportionally():
    set_scale(2.0)
    assert s(10) == 20
    set_scale(1.0)
    assert s(10) == 10


def test_hairlines_never_vanish():
    for scale in (0.85, 1.0, 1.35, 2.5):
        set_scale(scale)
        assert line_width(1) >= 1


# ---- fonts -------------------------------------------------------------

def test_fonts_are_regular_weight_by_default():
    """The old code forced bold everywhere to survive the blur; at native
    resolution regular weight is finer and more legible."""
    set_scale(1.0)
    regular = get_font(14)
    bold = get_font(14, bold=True)
    assert regular is not bold
    # Bold really is heavier: the same string renders wider.
    assert bold.size("Colonies")[0] >= regular.size("Colonies")[0]


def test_fonts_scale_with_the_display():
    set_scale(1.0)
    small = get_font(14).size("Colonies")[0]
    set_scale(2.0)
    big = get_font(14).size("Colonies")[0]
    assert big > small


def test_fonts_are_cached():
    set_scale(1.0)
    assert get_font(14) is get_font(14)


def test_changing_scale_rebuilds_fonts():
    set_scale(1.0)
    before = get_font(14)
    set_scale(1.8)
    assert get_font(14) is not before


def test_font_never_shrinks_below_legible():
    set_scale(MIN_SCALE)
    assert get_font(9).get_height() > 0
    assert s(9) >= 1

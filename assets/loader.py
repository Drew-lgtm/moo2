import os
import pygame
import random

ASSETS_DIR = os.path.join(os.path.dirname(__file__), '.')

_image_cache = {}


def _placeholder_surface(size):
    """Solid-fill fallback used when an asset is missing or unreadable."""
    surf = pygame.Surface(size, pygame.SRCALPHA)
    w, h = size
    surf.fill((40, 40, 60, 200))
    pygame.draw.rect(surf, (140, 140, 180), surf.get_rect(), 1)
    # Diagonal slash to make the placeholder visually obvious.
    pygame.draw.line(surf, (140, 140, 180), (0, 0), (w, h), 1)
    pygame.draw.line(surf, (140, 140, 180), (0, h), (w, 0), 1)
    return surf


def load_image(path, size=(32, 32)):
    """Load and scale an image, returning a placeholder Surface if the file
    is missing, zero-byte (asset never filled in), or otherwise unreadable.

    Several stock assets in this repo are 0-byte placeholders, so callers
    can't assume every PNG is loadable.
    """
    key = (path, size)
    if key in _image_cache:
        return _image_cache[key]
    full_path = os.path.join(ASSETS_DIR, path)
    try:
        if not os.path.exists(full_path) or os.path.getsize(full_path) <= 0:
            raise FileNotFoundError(f"empty or missing asset: {path}")
        image = pygame.image.load(full_path).convert_alpha()
        _image_cache[key] = pygame.transform.scale(image, size)
    except (pygame.error, FileNotFoundError, OSError):
        _image_cache[key] = _placeholder_surface(size)
    return _image_cache[key]


_race_portrait_cache: dict[str, str | None] = {}
_cached_race_names: list[str] | None = None


def _is_usable_png(full_path: str) -> bool:
    """A PNG is "usable" if it exists, has non-zero size, and pygame can
    decode it. The size check alone catches the 0-byte placeholders that
    ship with this repo without paying for a load."""
    try:
        return os.path.exists(full_path) and os.path.getsize(full_path) > 0
    except OSError:
        return False


def list_race_names() -> list[str]:
    """Return display names for every race that has a usable portrait in
    assets/races/. Zero-byte placeholders are skipped so the race grid
    only shows races that actually render. Cached after first scan."""
    global _cached_race_names
    if _cached_race_names is not None:
        return list(_cached_race_names)
    races_dir = os.path.join(ASSETS_DIR, "races")
    names = []
    for fname in sorted(os.listdir(races_dir)):
        if not fname.lower().endswith(".png"):
            continue
        if not _is_usable_png(os.path.join(races_dir, fname)):
            continue
        stem = os.path.splitext(fname)[0]
        names.append(stem if stem[0].isupper() else stem.capitalize())
    _cached_race_names = names
    return list(names)


def find_race_portrait(race_name: str) -> str | None:
    """Return a relative path like 'races/humans.png' matching race_name,
    or None if no usable portrait exists. Case-insensitive prefix match
    against assets/races/*.png; zero-byte files are ignored.
    """
    if race_name in _race_portrait_cache:
        return _race_portrait_cache[race_name]
    target = race_name.lower()
    races_dir = os.path.join(ASSETS_DIR, "races")
    for fname in os.listdir(races_dir):
        if not fname.lower().endswith(".png"):
            continue
        if not fname.lower().startswith(target):
            continue
        if not _is_usable_png(os.path.join(races_dir, fname)):
            continue
        _race_portrait_cache[race_name] = f"races/{fname}"
        return _race_portrait_cache[race_name]
    _race_portrait_cache[race_name] = None
    return None


def load_random_background(folder="backgrounds"):
    files = [
        f for f in os.listdir(os.path.join(ASSETS_DIR, folder))
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    if not files:
        raise FileNotFoundError("No background images found in assets/backgrounds")

    chosen = random.choice(files)
    full_path = os.path.join(ASSETS_DIR, folder, chosen)
    return pygame.image.load(full_path).convert()

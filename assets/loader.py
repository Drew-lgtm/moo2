import os
import pygame
import random

ASSETS_DIR = os.path.join(os.path.dirname(__file__), '.')

_image_cache = {}

def load_image(path, size=(32, 32)):
    key = (path, size)
    if key not in _image_cache:
        full_path = os.path.join(ASSETS_DIR, path)
        image = pygame.image.load(full_path).convert_alpha()
        _image_cache[key] = pygame.transform.scale(image, size)
    return _image_cache[key]

_race_portrait_cache: dict[str, str | None] = {}
_cached_race_names: list[str] | None = None


def list_race_names() -> list[str]:
    """Return display names for every race that has a portrait in
    assets/races/. Lower-case file stems are title-cased; ones already
    capitalized are left alone. Cached after first scan."""
    global _cached_race_names
    if _cached_race_names is not None:
        return list(_cached_race_names)
    races_dir = os.path.join(ASSETS_DIR, "races")
    names = []
    for fname in sorted(os.listdir(races_dir)):
        if not fname.lower().endswith(".png"):
            continue
        stem = os.path.splitext(fname)[0]
        names.append(stem if stem[0].isupper() else stem.capitalize())
    _cached_race_names = names
    return list(names)


def find_race_portrait(race_name: str) -> str | None:
    """Return a relative path like 'races/humans.png' matching race_name.

    Case-insensitive prefix match against assets/races/*.png. Returns None
    if nothing matches. Cached because it scans the directory each miss.
    """
    if race_name in _race_portrait_cache:
        return _race_portrait_cache[race_name]
    target = race_name.lower()
    races_dir = os.path.join(ASSETS_DIR, "races")
    for fname in os.listdir(races_dir):
        if not fname.lower().endswith(".png"):
            continue
        if fname.lower().startswith(target):
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

import os
import pygame
import random

ASSETS_DIR = os.path.join(os.path.dirname(__file__), '.')

_image_cache = {}

def load_image(path, size=(32, 32)):
    if path not in _image_cache:
        full_path = os.path.join(ASSETS_DIR, path)
        image = pygame.image.load(full_path).convert_alpha()
        _image_cache[path] = pygame.transform.scale(image, size)
    return _image_cache[path]

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

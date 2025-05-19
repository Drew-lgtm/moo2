import os
import random

STAR_NAMES_FILE = os.path.join(os.path.dirname(__file__), "star_names.txt")

RESERVED_NAMES = {
    "Altair",    # Alkari
    "Antares",   # Final battle location
    "Orion",     # Guardian system
    "Mentar",    # Psilon
    "Ursa",      # Bulrathi
    "Sssla",     # Sakkra
    "Nazin",     # Darlok
    "Klackon",   # Klackons
    "Silicoid",  # Silicoids
    "Gnol",      # Gnolams
    "Sol",       # Humans
    "Marklar",   # Meklar
    "Cryslon",   # Silicoid
    "Fieras",    # Mrrshan
    "Trilar"     # Trillian
}

def load_star_names():
    with open(STAR_NAMES_FILE, "r") as f:
        all_names = [line.strip() for line in f if line.strip()]
    return [name for name in all_names if name not in RESERVED_NAMES]

def get_random_star_name(used_names, available_names):
    candidates = [name for name in available_names if name not in used_names]
    return random.choice(candidates) if candidates else f"Star {random.randint(1000, 9999)}"

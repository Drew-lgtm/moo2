import shutil
from pathlib import Path

SAVE_DIR = Path("saves")
ACTIVE_DB = Path("galaxy.db")

def init_save_slots(num_slots=9):
    SAVE_DIR.mkdir(exist_ok=True)
    for i in range(1, num_slots + 1):
        slot_path = SAVE_DIR / f"slot{i}.db"
        if not slot_path.exists():
            slot_path.touch()

def save_to_slot(slot_number):
    slot_file = SAVE_DIR / f"slot{slot_number}.db"
    if ACTIVE_DB.exists():
        shutil.copy2(ACTIVE_DB, slot_file)
        print(f"Game saved to slot {slot_number}")

def load_from_slot(slot_number):
    slot_file = SAVE_DIR / f"slot{slot_number}.db"
    if slot_file.exists() and slot_file.stat().st_size > 0:
        shutil.copy2(slot_file, ACTIVE_DB)
        print(f"Game loaded from slot {slot_number}")
        return True
    else:
        print(f"Save slot {slot_number} is empty or invalid.")
        return False

def save_autosave():
    autosave_path = SAVE_DIR / "autosave.db"
    if ACTIVE_DB.exists():
        shutil.copy2(ACTIVE_DB, autosave_path)

def load_autosave():
    autosave_path = SAVE_DIR / "autosave.db"
    if autosave_path.exists() and autosave_path.stat().st_size > 0:
        shutil.copy2(autosave_path, ACTIVE_DB)
        print("Autosave loaded.")
        return True
    return False

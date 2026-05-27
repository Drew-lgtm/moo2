import shutil
import sqlite3
import datetime
from pathlib import Path

SAVE_DIR = Path("saves")
ACTIVE_DB = Path("galaxy.db")
NUM_SLOTS = 5


def init_save_slots():
    SAVE_DIR.mkdir(exist_ok=True)


def _slot_path(slot_number) -> Path:
    if slot_number == "auto":
        return SAVE_DIR / "autosave.db"
    return SAVE_DIR / f"slot{slot_number}.db"


def save_to_slot(slot_number):
    slot_file = _slot_path(slot_number)
    if ACTIVE_DB.exists():
        shutil.copy2(ACTIVE_DB, slot_file)
        print(f"Game saved to slot {slot_number}")


def load_from_slot(slot_number):
    slot_file = _slot_path(slot_number)
    if slot_file.exists() and slot_file.stat().st_size > 0:
        shutil.copy2(slot_file, ACTIVE_DB)
        print(f"Game loaded from slot {slot_number}")
        return True
    else:
        print(f"Save slot {slot_number} is empty or invalid.")
        return False


def save_autosave():
    autosave_path = _slot_path("auto")
    if ACTIVE_DB.exists():
        shutil.copy2(ACTIVE_DB, autosave_path)


def load_autosave():
    if load_from_slot("auto"):
        print("Autosave loaded.")
        return True
    return False


# ---- slot metadata (for the save/load GUI) ----------------------------

def slot_info(slot_number) -> dict | None:
    """Read display metadata from a save slot without touching the
    active game. Returns None for an empty slot, or a dict with
    empire / race / turn / colonies / ships / saved_at (and
    ``corrupt`` if the file can't be read)."""
    path = _slot_path(slot_number)
    if not path.exists() or path.stat().st_size == 0:
        return None
    saved_at = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    info = {"slot": slot_number, "saved_at": saved_at}
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        emp = cur.execute(
            "SELECT id, name, race_type FROM empires WHERE is_player = 1"
        ).fetchone()
        if emp is not None:
            info["empire"] = emp["name"]
            info["race"] = emp["race_type"]
            colonies = cur.execute(
                "SELECT COUNT(*) AS c FROM planets WHERE owner_empire_id = ?",
                (emp["id"],),
            ).fetchone()
            info["colonies"] = colonies["c"] if colonies else 0
            try:
                ships = cur.execute(
                    "SELECT COUNT(*) AS c FROM ships WHERE owner_empire_id = ?",
                    (emp["id"],),
                ).fetchone()
                info["ships"] = ships["c"] if ships else 0
            except sqlite3.Error:
                info["ships"] = 0
        else:
            info["empire"], info["race"], info["colonies"], info["ships"] = "?", "?", 0, 0
        turn = cur.execute("SELECT value FROM meta WHERE key = 'turn'").fetchone()
        info["turn"] = int(turn["value"]) if turn and turn["value"] else 0
        conn.close()
    except sqlite3.Error:
        return {"slot": slot_number, "saved_at": saved_at, "corrupt": True}
    return info


def list_slots() -> list[tuple]:
    """Return [(slot_number, info_or_None), ...] for the numbered slots."""
    return [(i, slot_info(i)) for i in range(1, NUM_SLOTS + 1)]

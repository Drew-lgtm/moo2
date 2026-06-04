import sqlite3
from pathlib import Path

DB_PATH = Path("galaxy.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS stars (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            x INTEGER,
            y INTEGER,
            class TEXT,
            image TEXT,
            size INTEGER
        );

        CREATE TABLE IF NOT EXISTS empires (
            id INTEGER PRIMARY KEY,
            name TEXT,
            race_type TEXT,
            color TEXT,
            home_star_id INTEGER,
            tech_level INTEGER,
            bc INTEGER DEFAULT 0,
            research_points INTEGER DEFAULT 0,
            is_player INTEGER DEFAULT 0,
            tech_target TEXT,
            tech_progress INTEGER DEFAULT 0,
            personality TEXT DEFAULT 'balanced',
            custom_traits TEXT DEFAULT '',
            FOREIGN KEY(home_star_id) REFERENCES stars(id)
        );

        CREATE TABLE IF NOT EXISTS empire_techs (
            empire_id INTEGER NOT NULL,
            tech_id TEXT NOT NULL,
            PRIMARY KEY(empire_id, tech_id),
            FOREIGN KEY(empire_id) REFERENCES empires(id)
        );

        CREATE TABLE IF NOT EXISTS empire_locked_techs (
            empire_id INTEGER NOT NULL,
            tech_id TEXT NOT NULL,
            PRIMARY KEY(empire_id, tech_id)
        );

        CREATE TABLE IF NOT EXISTS planets (
            id INTEGER PRIMARY KEY,
            star_id INTEGER,
            type TEXT,
            size TEXT,
            colonizable BOOLEAN,
            owner_empire_id INTEGER,
            population INTEGER DEFAULT 0,
            max_population INTEGER DEFAULT 0,
            current_project TEXT,
            project_progress INTEGER DEFAULT 0,
            growth_progress REAL DEFAULT 0,
            farmers INTEGER DEFAULT 0,
            workers INTEGER DEFAULT 0,
            scientists INTEGER DEFAULT 0,
            richness TEXT DEFAULT 'Abundant',
            gravity TEXT DEFAULT 'Normal',
            special TEXT DEFAULT '',
            autobuild TEXT DEFAULT '',
            original_race TEXT DEFAULT '',
            assimilation_progress INTEGER DEFAULT 100,
            guerrilla_turns INTEGER DEFAULT 0,
            FOREIGN KEY(star_id) REFERENCES stars(id),
            FOREIGN KEY(owner_empire_id) REFERENCES empires(id)
        );

        CREATE TABLE IF NOT EXISTS planet_buildings (
            planet_id INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            PRIMARY KEY(planet_id, project_id),
            FOREIGN KEY(planet_id) REFERENCES planets(id)
        );

        CREATE TABLE IF NOT EXISTS planet_build_queue (
            planet_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            PRIMARY KEY(planet_id, position),
            FOREIGN KEY(planet_id) REFERENCES planets(id)
        );

        CREATE TABLE IF NOT EXISTS ships (
            id INTEGER PRIMARY KEY,
            owner_empire_id INTEGER,
            ship_class TEXT,
            current_star_id INTEGER,
            dest_star_id INTEGER,
            turns_remaining INTEGER DEFAULT 0,
            armor_tech TEXT,
            shield_tech TEXT,
            weapon_tech TEXT,
            weapon_count INTEGER DEFAULT 0,
            specials TEXT DEFAULT '',
            FOREIGN KEY(owner_empire_id) REFERENCES empires(id),
            FOREIGN KEY(current_star_id) REFERENCES stars(id),
            FOREIGN KEY(dest_star_id) REFERENCES stars(id)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS diplomacy (
            empire_a INTEGER NOT NULL,
            empire_b INTEGER NOT NULL,
            attitude INTEGER DEFAULT 0,
            at_war INTEGER DEFAULT 0,
            treaties TEXT DEFAULT '',
            PRIMARY KEY(empire_a, empire_b)
        );

        CREATE TABLE IF NOT EXISTS diplomacy_pending (
            empire_a INTEGER NOT NULL,
            empire_b INTEGER NOT NULL,
            treaty TEXT NOT NULL,
            ends_turn INTEGER NOT NULL,
            PRIMARY KEY(empire_a, empire_b, treaty)
        );

        CREATE TABLE IF NOT EXISTS empire_explored (
            empire_id INTEGER NOT NULL,
            star_id INTEGER NOT NULL,
            PRIMARY KEY(empire_id, star_id)
        );

        CREATE TABLE IF NOT EXISTS spies (
            empire_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS spy_missions (
            attacker INTEGER NOT NULL,
            target INTEGER NOT NULL,
            mission TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY(attacker, target, mission)
        );

        CREATE TABLE IF NOT EXISTS leaders (
            id INTEGER PRIMARY KEY,
            name TEXT,
            category TEXT,
            skill TEXT,
            level INTEGER DEFAULT 1,
            hire_cost INTEGER DEFAULT 0,
            salary INTEGER DEFAULT 0,
            owner_empire_id INTEGER,
            assigned_planet_id INTEGER,
            assigned_ship_id INTEGER
        );

        -- Persistent hall of fame: NOT wiped by clear_galaxy, so it
        -- survives across games.
        CREATE TABLE IF NOT EXISTS hall_of_fame (
            id INTEGER PRIMARY KEY,
            empire_name TEXT,
            race TEXT,
            score INTEGER DEFAULT 0,
            outcome TEXT,
            turn INTEGER
        );
        """)
        _migrate_empires(conn)
        _migrate_planets(conn)
        _migrate_ships(conn)
        conn.commit()


def _migrate_empires(conn):
    """Add columns introduced after the initial schema to existing DBs."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(empires)")}
    if "bc" not in existing:
        conn.execute("ALTER TABLE empires ADD COLUMN bc INTEGER DEFAULT 0")
    if "research_points" not in existing:
        conn.execute("ALTER TABLE empires ADD COLUMN research_points INTEGER DEFAULT 0")
    if "is_player" not in existing:
        conn.execute("ALTER TABLE empires ADD COLUMN is_player INTEGER DEFAULT 0")
    if "tech_target" not in existing:
        conn.execute("ALTER TABLE empires ADD COLUMN tech_target TEXT")
    if "tech_progress" not in existing:
        conn.execute("ALTER TABLE empires ADD COLUMN tech_progress INTEGER DEFAULT 0")
    if "personality" not in existing:
        conn.execute("ALTER TABLE empires ADD COLUMN personality TEXT DEFAULT 'balanced'")
    if "custom_traits" not in existing:
        conn.execute("ALTER TABLE empires ADD COLUMN custom_traits TEXT DEFAULT ''")


def _migrate_ships(conn):
    """Add loadout columns introduced after the initial schema."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(ships)")}
    if "armor_tech" not in existing:
        conn.execute("ALTER TABLE ships ADD COLUMN armor_tech TEXT")
    if "shield_tech" not in existing:
        conn.execute("ALTER TABLE ships ADD COLUMN shield_tech TEXT")
    if "weapon_tech" not in existing:
        conn.execute("ALTER TABLE ships ADD COLUMN weapon_tech TEXT")
    if "weapon_count" not in existing:
        conn.execute("ALTER TABLE ships ADD COLUMN weapon_count INTEGER DEFAULT 0")
    if "specials" not in existing:
        conn.execute("ALTER TABLE ships ADD COLUMN specials TEXT DEFAULT ''")


def _migrate_planets(conn):
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(planets)")}
    if "owner_empire_id" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN owner_empire_id INTEGER")
    if "population" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN population INTEGER DEFAULT 0")
    if "max_population" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN max_population INTEGER DEFAULT 0")
    if "current_project" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN current_project TEXT")
    if "project_progress" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN project_progress INTEGER DEFAULT 0")
    if "growth_progress" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN growth_progress REAL DEFAULT 0")
    if "farmers" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN farmers INTEGER DEFAULT 0")
    if "workers" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN workers INTEGER DEFAULT 0")
    if "scientists" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN scientists INTEGER DEFAULT 0")
    if "richness" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN richness TEXT DEFAULT 'Abundant'")
    if "gravity" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN gravity TEXT DEFAULT 'Normal'")
    if "special" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN special TEXT DEFAULT ''")
    if "autobuild" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN autobuild TEXT DEFAULT ''")
    if "original_race" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN original_race TEXT DEFAULT ''")
    if "assimilation_progress" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN assimilation_progress INTEGER DEFAULT 100")
    if "guerrilla_turns" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN guerrilla_turns INTEGER DEFAULT 0")


def insert_star(conn, name, x, y, star_class, image, size):
    cursor = conn.execute(
        "INSERT INTO stars (name, x, y, class, image, size) VALUES (?, ?, ?, ?, ?, ?)",
        (name, x, y, star_class, image, size),
    )
    return cursor.lastrowid


def insert_planet(conn, star_id, planet_type, size, colonizable, owner_empire_id=None,
                  population=0, max_population=0,
                  farmers=0, workers=0, scientists=0,
                  richness="Abundant", gravity="Normal", special=""):
    cursor = conn.execute(
        "INSERT INTO planets (star_id, type, size, colonizable, owner_empire_id, "
        "population, max_population, farmers, workers, scientists, "
        "richness, gravity, special) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (star_id, planet_type, size, colonizable, owner_empire_id,
         population, max_population, farmers, workers, scientists,
         richness, gravity, special),
    )
    return cursor.lastrowid


def update_planet_workers(conn, planet_id, farmers, workers, scientists):
    conn.execute(
        "UPDATE planets SET farmers = ?, workers = ?, scientists = ? WHERE id = ?",
        (farmers, workers, scientists, planet_id),
    )


def update_planet_owner(conn, planet_id, owner_empire_id):
    """Set or clear the planet's owner. Called when a Colony Ship lands."""
    conn.execute(
        "UPDATE planets SET owner_empire_id = ? WHERE id = ?",
        (owner_empire_id, planet_id),
    )


def update_planet_population(conn, planet_id, current, max_population, growth_progress=0.0):
    conn.execute(
        "UPDATE planets SET population = ?, max_population = ?, growth_progress = ? WHERE id = ?",
        (current, max_population, growth_progress, planet_id),
    )


def update_planet_conquest(conn, planet_id, original_race, assimilation_progress,
                           guerrilla_turns):
    conn.execute(
        "UPDATE planets SET original_race = ?, assimilation_progress = ?, "
        "guerrilla_turns = ? WHERE id = ?",
        (original_race, assimilation_progress, guerrilla_turns, planet_id),
    )


def update_planet_autobuild(conn, planet_id, autobuild):
    conn.execute(
        "UPDATE planets SET autobuild = ? WHERE id = ?",
        (autobuild, planet_id),
    )


def update_planet_build(conn, planet_id, current_project, progress):
    conn.execute(
        "UPDATE planets SET current_project = ?, project_progress = ? WHERE id = ?",
        (current_project, progress, planet_id),
    )


def insert_planet_building(conn, planet_id, project_id):
    conn.execute(
        "INSERT OR IGNORE INTO planet_buildings (planet_id, project_id) VALUES (?, ?)",
        (planet_id, project_id),
    )


def delete_planet_building(conn, planet_id, project_id):
    conn.execute(
        "DELETE FROM planet_buildings WHERE planet_id = ? AND project_id = ?",
        (planet_id, project_id),
    )


def get_planet_buildings(conn, planet_id):
    return [
        row["project_id"]
        for row in conn.execute(
            "SELECT project_id FROM planet_buildings WHERE planet_id = ?",
            (planet_id,),
        )
    ]


def get_planet_build_queue(conn, planet_id):
    return [
        row["project_id"]
        for row in conn.execute(
            "SELECT project_id FROM planet_build_queue "
            "WHERE planet_id = ? ORDER BY position",
            (planet_id,),
        )
    ]


def save_planet_build_queue(conn, planet_id, project_ids):
    conn.execute("DELETE FROM planet_build_queue WHERE planet_id = ?", (planet_id,))
    for position, project_id in enumerate(project_ids):
        conn.execute(
            "INSERT INTO planet_build_queue (planet_id, position, project_id) "
            "VALUES (?, ?, ?)",
            (planet_id, position, project_id),
        )


def insert_empire(conn, name, race_type, color, home_star_id, tech_level, *,
                  is_player=False, personality="balanced", custom_traits="") -> int:
    cursor = conn.execute(
        "INSERT INTO empires (name, race_type, color, home_star_id, tech_level, "
        "is_player, personality, custom_traits) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, race_type, color, home_star_id, tech_level,
         1 if is_player else 0, personality, custom_traits),
    )
    result = cursor.lastrowid
    assert result is not None
    return result


def update_empire_economy(conn, empire_id, bc, research_points):
    conn.execute(
        "UPDATE empires SET bc = ?, research_points = ? WHERE id = ?",
        (bc, research_points, empire_id),
    )


def update_empire_tech(conn, empire_id, tech_target, tech_progress):
    conn.execute(
        "UPDATE empires SET tech_target = ?, tech_progress = ? WHERE id = ?",
        (tech_target, tech_progress, empire_id),
    )


def insert_empire_tech(conn, empire_id, tech_id):
    conn.execute(
        "INSERT OR IGNORE INTO empire_techs (empire_id, tech_id) VALUES (?, ?)",
        (empire_id, tech_id),
    )


def get_empire_techs(conn, empire_id):
    return [
        row["tech_id"]
        for row in conn.execute(
            "SELECT tech_id FROM empire_techs WHERE empire_id = ?",
            (empire_id,),
        )
    ]


def insert_empire_locked_tech(conn, empire_id, tech_id):
    conn.execute(
        "INSERT OR IGNORE INTO empire_locked_techs (empire_id, tech_id) VALUES (?, ?)",
        (empire_id, tech_id),
    )


def get_empire_locked_techs(conn, empire_id):
    return [
        row["tech_id"]
        for row in conn.execute(
            "SELECT tech_id FROM empire_locked_techs WHERE empire_id = ?",
            (empire_id,),
        )
    ]


def insert_ship(conn, owner_empire_id, ship_class, current_star_id, *,
                armor_tech=None, shield_tech=None, weapon_tech=None,
                weapon_count=0, specials="") -> int:
    """Insert a ship with its frozen loadout. The loadout is captured at
    construction time so older hulls don't auto-benefit from later
    research — you have to actually build the new generation."""
    cursor = conn.execute(
        "INSERT INTO ships (owner_empire_id, ship_class, current_star_id, "
        "armor_tech, shield_tech, weapon_tech, weapon_count, specials) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (owner_empire_id, ship_class, current_star_id,
         armor_tech, shield_tech, weapon_tech, weapon_count, specials),
    )
    result = cursor.lastrowid
    assert result is not None
    return result


def get_ships(conn):
    return conn.execute("SELECT * FROM ships").fetchall()


def update_ship_transit(conn, ship_id, current_star_id, dest_star_id, turns_remaining):
    conn.execute(
        "UPDATE ships SET current_star_id = ?, dest_star_id = ?, turns_remaining = ? WHERE id = ?",
        (current_star_id, dest_star_id, turns_remaining, ship_id),
    )


def delete_ship(conn, ship_id):
    conn.execute("DELETE FROM ships WHERE id = ?", (ship_id,))


def get_stars(conn=None):
    if conn is None:
        with get_connection() as c:
            return c.execute("SELECT * FROM stars").fetchall()
    return conn.execute("SELECT * FROM stars").fetchall()


def get_planets_for_star(star_id, conn=None):
    sql = "SELECT * FROM planets WHERE star_id = ?"
    if conn is None:
        with get_connection() as c:
            return c.execute(sql, (star_id,)).fetchall()
    return conn.execute(sql, (star_id,)).fetchall()


def get_empires(conn=None):
    if conn is None:
        with get_connection() as c:
            return c.execute("SELECT * FROM empires").fetchall()
    return conn.execute("SELECT * FROM empires").fetchall()


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def insert_hall_of_fame(conn, empire_name, race, score, outcome, turn):
    conn.execute(
        "INSERT INTO hall_of_fame (empire_name, race, score, outcome, turn) "
        "VALUES (?, ?, ?, ?, ?)",
        (empire_name, race, score, outcome, turn),
    )


def get_hall_of_fame(limit=12):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM hall_of_fame ORDER BY score DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def clear_galaxy():
    # init_db is idempotent and ensures every table exists before we try
    # to wipe it — important on first-ever new game when galaxy.db hasn't
    # been created yet.
    init_db()
    with get_connection() as conn:
        for table in ("planet_build_queue", "planet_buildings", "ships",
                      "empire_techs", "planets", "empires", "stars", "meta",
                      "diplomacy", "diplomacy_pending", "empire_explored",
                      "spies", "spy_missions", "leaders", "empire_locked_techs"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

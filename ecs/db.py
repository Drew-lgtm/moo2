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
            FOREIGN KEY(home_star_id) REFERENCES stars(id)
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
            FOREIGN KEY(star_id) REFERENCES stars(id),
            FOREIGN KEY(owner_empire_id) REFERENCES empires(id)
        );

        CREATE TABLE IF NOT EXISTS planet_buildings (
            planet_id INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            PRIMARY KEY(planet_id, project_id),
            FOREIGN KEY(planet_id) REFERENCES planets(id)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        _migrate_empires(conn)
        _migrate_planets(conn)
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


def _migrate_planets(conn):
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(planets)")}
    if "population" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN population INTEGER DEFAULT 0")
    if "max_population" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN max_population INTEGER DEFAULT 0")
    if "current_project" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN current_project TEXT")
    if "project_progress" not in existing:
        conn.execute("ALTER TABLE planets ADD COLUMN project_progress INTEGER DEFAULT 0")


def insert_star(conn, name, x, y, star_class, image, size):
    cursor = conn.execute(
        "INSERT INTO stars (name, x, y, class, image, size) VALUES (?, ?, ?, ?, ?, ?)",
        (name, x, y, star_class, image, size),
    )
    return cursor.lastrowid


def insert_planet(conn, star_id, planet_type, size, colonizable, owner_empire_id=None,
                  population=0, max_population=0):
    cursor = conn.execute(
        "INSERT INTO planets (star_id, type, size, colonizable, owner_empire_id, population, max_population) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (star_id, planet_type, size, colonizable, owner_empire_id, population, max_population),
    )
    return cursor.lastrowid


def update_planet_population(conn, planet_id, current, max_population):
    conn.execute(
        "UPDATE planets SET population = ?, max_population = ? WHERE id = ?",
        (current, max_population, planet_id),
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


def get_planet_buildings(conn, planet_id):
    return [
        row["project_id"]
        for row in conn.execute(
            "SELECT project_id FROM planet_buildings WHERE planet_id = ?",
            (planet_id,),
        )
    ]


def insert_empire(conn, name, race_type, color, home_star_id, tech_level, *, is_player=False) -> int:
    cursor = conn.execute(
        "INSERT INTO empires (name, race_type, color, home_star_id, tech_level, is_player) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, race_type, color, home_star_id, tech_level, 1 if is_player else 0),
    )
    result = cursor.lastrowid
    assert result is not None
    return result


def update_empire_economy(conn, empire_id, bc, research_points):
    conn.execute(
        "UPDATE empires SET bc = ?, research_points = ? WHERE id = ?",
        (bc, research_points, empire_id),
    )


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


def clear_galaxy():
    with get_connection() as conn:
        conn.execute("DELETE FROM planets")
        conn.execute("DELETE FROM empires")
        conn.execute("DELETE FROM stars")
        conn.execute("DELETE FROM meta")
        conn.commit()

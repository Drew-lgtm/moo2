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
            FOREIGN KEY(home_star_id) REFERENCES stars(id)
        );

        CREATE TABLE IF NOT EXISTS planets (
            id INTEGER PRIMARY KEY,
            star_id INTEGER,
            type TEXT,
            size TEXT,
            colonizable BOOLEAN,
            owner_empire_id INTEGER,
            FOREIGN KEY(star_id) REFERENCES stars(id),
            FOREIGN KEY(owner_empire_id) REFERENCES empires(id)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        conn.commit()


def insert_star(conn, name, x, y, star_class, image, size):
    cursor = conn.execute(
        "INSERT INTO stars (name, x, y, class, image, size) VALUES (?, ?, ?, ?, ?, ?)",
        (name, x, y, star_class, image, size),
    )
    return cursor.lastrowid


def insert_planet(conn, star_id, planet_type, size, colonizable, owner_empire_id=None):
    cursor = conn.execute(
        "INSERT INTO planets (star_id, type, size, colonizable, owner_empire_id) VALUES (?, ?, ?, ?, ?)",
        (star_id, planet_type, size, colonizable, owner_empire_id),
    )
    return cursor.lastrowid


def insert_empire(conn, name, race_type, color, home_star_id, tech_level) -> int:
    cursor = conn.execute(
        "INSERT INTO empires (name, race_type, color, home_star_id, tech_level) VALUES (?, ?, ?, ?, ?)",
        (name, race_type, color, home_star_id, tech_level),
    )
    result = cursor.lastrowid
    assert result is not None
    return result


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

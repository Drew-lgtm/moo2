import sqlite3
from pathlib import Path

DB_PATH = Path("galaxy.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executescript("""
        CREATE TABLE IF NOT EXISTS stars (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            x INTEGER,
            y INTEGER,
            class TEXT,
            image TEXT,
            size INTEGER
        );

        CREATE TABLE IF NOT EXISTS planets (
            id INTEGER PRIMARY KEY,
            star_id INTEGER,
            type TEXT,
            size TEXT,
            colonizable BOOLEAN,
            FOREIGN KEY(star_id) REFERENCES stars(id)
        );
        """)
        conn.commit()

def insert_star(name, x, y, star_class, image, size):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO stars (name, x, y, class, image, size)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, x, y, star_class, image, size))
        return cursor.lastrowid

def insert_planet(star_id, planet_type, size, colonizable):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO planets (star_id, type, size, colonizable)
            VALUES (?, ?, ?, ?)
        """, (star_id, planet_type, size, colonizable))

def get_stars():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM stars").fetchall()

def get_planets_for_star(star_id):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM planets WHERE star_id = ?", (star_id,)).fetchall()

def clear_galaxy():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM planets")
        cursor.execute("DELETE FROM stars")
        conn.commit()

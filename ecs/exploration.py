"""Per-empire star exploration (fog of war).

Each empire knows a set of star DB ids it has "explored" — visited with
a ship or settled. Unexplored stars still appear on the galaxy map (you
can see the light) but their name, planets, and ownership are hidden
until a ship visits.

Star-chart diplomacy (diplomacy screen) merges two empires' explored
sets, so a Scout-heavy empire can trade map knowledge.

State persists in the ``empire_explored`` table and is rebuilt into an
``Exploration`` object on ``game.exploration``.
"""
from __future__ import annotations

from ecs.db import get_connection
from ecs.components import Owner, Orbiting, StarRef, ShipAt, ShipOwner, Empire


class Exploration:
    def __init__(self):
        # empire_id -> set of explored star DB ids
        self.explored: dict[int, set[int]] = {}

    def explored_stars(self, empire_id: int) -> set[int]:
        return self.explored.setdefault(empire_id, set())

    def is_explored(self, empire_id: int, star_db_id: int) -> bool:
        return star_db_id in self.explored.get(empire_id, ())

    def mark(self, empire_id: int, star_db_id: int):
        self.explored.setdefault(empire_id, set()).add(star_db_id)

    def merge(self, a: int, b: int):
        """Star-chart exchange: both empires end up knowing the union of
        their explored stars."""
        union = self.explored_stars(a) | self.explored_stars(b)
        self.explored[a] = set(union)
        self.explored[b] = set(union)

    def reveal_from_world(self, component_mgr):
        """Mark every star where an empire currently has a colony or a
        parked ship as explored for that empire. Called each turn (and
        once at game start) so visiting a system reveals it."""
        # Map star entity -> star DB id once.
        star_db = {
            eid: ref.db_id for eid, ref in component_mgr.get_all(StarRef)
        }

        # Colonies reveal their star.
        for planet_entity, owner in component_mgr.get_all(Owner):
            orbit = component_mgr.get_component(planet_entity, Orbiting)
            if orbit is None:
                continue
            db_id = star_db.get(orbit.star_entity)
            if db_id is not None:
                self.mark(owner.empire_id, db_id)

        # Parked ships reveal their star.
        for ship_entity, at in component_mgr.get_all(ShipAt):
            ship_owner = component_mgr.get_component(ship_entity, ShipOwner)
            if ship_owner is None:
                continue
            db_id = star_db.get(at.star_entity)
            if db_id is not None:
                self.mark(ship_owner.empire_id, db_id)

    # -- persistence ----------------------------------------------------

    def save(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM empire_explored")
            for empire_id, stars in self.explored.items():
                for star_id in stars:
                    conn.execute(
                        "INSERT OR IGNORE INTO empire_explored (empire_id, star_id) VALUES (?, ?)",
                        (empire_id, star_id),
                    )
            conn.commit()

    def load(self):
        self.explored.clear()
        with get_connection() as conn:
            for row in conn.execute("SELECT empire_id, star_id FROM empire_explored"):
                self.explored.setdefault(row["empire_id"], set()).add(row["star_id"])


def exploration_tick(game, new_turn: int):
    """Turn callback: reveal newly-visited stars, then persist."""
    expl = getattr(game, "exploration", None)
    if expl is None:
        return
    expl.reveal_from_world(game.component_mgr)
    expl.save()

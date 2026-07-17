"""Manual ship designs — player-authored blueprints.

A design names a loadout for a hull class: armor, shield, weapon +
mount + count, and specials. When a design-backed build order completes
(see ``ecs.economy.production_tick``), the spawned ship freezes exactly
that loadout — unlike the auto-build path which snapshots the empire's
current best gear.

Designs coexist with auto-build: the Build screen offers "Quick Build"
(auto-loadout) plus every saved design for the hull. State hangs off
``game.ship_designs`` and persists via the ``ship_designs`` table.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ecs.db import (
    get_connection, insert_ship_design, get_ship_designs, delete_ship_design,
)
from ecs.ships import SHIPS
from ecs.ship_design import (
    stats_from_ship, hull_space_budget, design_space_used, MOUNTS,
)


DESIGN_PROJECT_PREFIX = "design:"


def design_project_id(design_id: int) -> str:
    """The build-queue project id for a design-backed order."""
    return f"{DESIGN_PROJECT_PREFIX}{design_id}"


def parse_design_project(project_id) -> int | None:
    """Return the design id if ``project_id`` is a design order, else None."""
    if isinstance(project_id, str) and project_id.startswith(DESIGN_PROJECT_PREFIX):
        try:
            return int(project_id[len(DESIGN_PROJECT_PREFIX):])
        except ValueError:
            return None
    return None


def design_project_spec(project_id, mgr) -> dict | None:
    """Resolve a ``design:<id>`` build project into a project-shaped dict
    (name / cost / type / ship_class / design_id), mirroring the PROJECTS
    entries so the build loop can treat it uniformly. Cost is the hull
    class's build cost. Returns None for non-design ids or unknown/dead
    designs."""
    did = parse_design_project(project_id)
    if did is None or mgr is None:
        return None
    design = mgr.get(did)
    if design is None:
        return None
    return {
        "id": project_id,
        "name": design.name,
        "cost": SHIPS.get(design.ship_class, {}).get("cost", 50),
        "type": "ship",
        "ship_class": design.ship_class,
        "design_id": design.id,
    }


@dataclass
class ShipDesign:
    """One saved blueprint. Field names mirror the Ship component so
    ``stats_from_ship`` can read a design directly (duck-typed)."""
    id: int
    empire_id: int
    name: str
    ship_class: str
    armor_tech: str | None = None
    shield_tech: str | None = None
    weapon_tech: str | None = None
    weapon_count: int = 0
    weapon_mount: str = "normal"
    specials: list[str] = field(default_factory=list)

    def space_used(self) -> int:
        return design_space_used(
            self.armor_tech, self.shield_tech, self.weapon_tech,
            self.weapon_count, self.weapon_mount, self.specials,
        )

    def space_total(self, unlocked=None) -> int:
        return hull_space_budget(self.ship_class, self.specials, unlocked)

    def fits(self, unlocked=None) -> bool:
        return self.space_used() <= self.space_total(unlocked)

    def stats(self) -> dict:
        """Combat stats for display: base hull + equipment, attack (with
        mount), shield capacity/regen, defense. Reuses the same decoder
        the combat resolver uses so the designer shows true numbers."""
        s = stats_from_ship(self)
        base_hull = SHIPS.get(self.ship_class, {}).get("hull", 0)
        base = SHIPS.get(self.ship_class, {})
        return {
            "attack": s["attack"],
            "missile_attack": s.get("missile_attack", 0) + base.get("fighter_attack", 0),
            "point_defense": s.get("point_defense", 0),
            "hull": base_hull + s["hull"],
            "shield_capacity": s["shield_capacity"],
            "shield_regen": s["shield_regen"],
            "defense": s["defense"],
        }

    def ship_fields(self) -> dict:
        """kwargs for ``insert_ship`` / seeding a Ship component."""
        return {
            "armor_tech": self.armor_tech,
            "shield_tech": self.shield_tech,
            "weapon_tech": self.weapon_tech,
            "weapon_count": self.weapon_count,
            "weapon_mount": self.weapon_mount,
            "specials": list(self.specials),
        }


class ShipDesignManager:
    def __init__(self):
        self.designs: dict[int, ShipDesign] = {}
        self._next_id = 1

    # -- queries --------------------------------------------------------

    def get(self, design_id: int) -> ShipDesign | None:
        return self.designs.get(design_id)

    def for_empire(self, empire_id: int) -> list[ShipDesign]:
        return [d for d in self.designs.values() if d.empire_id == empire_id]

    def for_empire_class(self, empire_id: int, ship_class: str) -> list[ShipDesign]:
        return [d for d in self.for_empire(empire_id)
                if d.ship_class == ship_class]

    # -- mutations ------------------------------------------------------

    def create(self, empire_id: int, name: str, ship_class: str, *,
               armor_tech=None, shield_tech=None, weapon_tech=None,
               weapon_count=0, weapon_mount="normal", specials=None) -> ShipDesign:
        design = ShipDesign(
            id=self._next_id, empire_id=empire_id, name=name,
            ship_class=ship_class, armor_tech=armor_tech,
            shield_tech=shield_tech, weapon_tech=weapon_tech,
            weapon_count=weapon_count,
            weapon_mount=weapon_mount if weapon_mount in MOUNTS else "normal",
            specials=list(specials or []),
        )
        self.designs[design.id] = design
        self._next_id += 1
        return design

    def delete(self, design_id: int):
        self.designs.pop(design_id, None)

    # -- persistence ----------------------------------------------------

    def save(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM ship_designs")
            for d in self.designs.values():
                # Preserve the id so build-order references (design:<id>)
                # stay valid across a save/load.
                conn.execute(
                    "INSERT INTO ship_designs (id, empire_id, name, ship_class, "
                    "armor_tech, shield_tech, weapon_tech, weapon_count, "
                    "weapon_mount, specials) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (d.id, d.empire_id, d.name, d.ship_class, d.armor_tech,
                     d.shield_tech, d.weapon_tech, d.weapon_count,
                     d.weapon_mount, ",".join(d.specials)),
                )
            conn.commit()

    def load(self):
        self.designs.clear()
        self._next_id = 1
        for row in get_ship_designs():
            specials = [s for s in (row["specials"] or "").split(",") if s]
            try:
                mount = row["weapon_mount"] or "normal"
            except (IndexError, KeyError):
                mount = "normal"
            d = ShipDesign(
                id=row["id"], empire_id=row["empire_id"], name=row["name"],
                ship_class=row["ship_class"], armor_tech=row["armor_tech"],
                shield_tech=row["shield_tech"], weapon_tech=row["weapon_tech"],
                weapon_count=row["weapon_count"] or 0,
                weapon_mount=mount, specials=specials,
            )
            self.designs[d.id] = d
            self._next_id = max(self._next_id, d.id + 1)

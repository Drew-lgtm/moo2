"""Leaders / Heroes — MOO2-style colony and ship officers.

Leaders appear at random in a shared **hiring pool**. There are two
kinds:

- **Colony leaders** are assigned to one of your colonies and boost that
  planet's output (Farmer / Industrialist / Scientist specialists, or a
  Governor who lifts everything a little).
- **Ship leaders** are assigned to one of your warships and boost it in
  battle (Weapons Master → attack, Battle Tactician → hull).

You hire a leader for a one-off fee, then pay a per-turn salary. Each
empire can retain at most ``MAX_LEADERS_PER_EMPIRE`` leaders. If a leader
can't be paid, they quit. Leaders whose colony is lost or ship destroyed
fall idle until reassigned.

State hangs off ``game.leaders`` and persists via the ``leaders`` table.
"""
from __future__ import annotations

import random

from ecs.db import get_connection
from ecs.components import Empire, Owner, Ship, ShipOwner


# ---- tuning ------------------------------------------------------------

MAX_LEADERS_PER_EMPIRE = 5
POOL_CAP = 4                  # candidates available for hire at once
CANDIDATE_CHANCE = 0.30       # chance per turn a new candidate appears

# Skill catalogs. Colony skills give an additive output fraction per
# level (e.g. Farmer L2 = +40% food on the assigned planet). Ship skills
# give a flat combat bonus per level on the assigned ship.
COLONY_SKILLS = {
    "farming":   {"name": "Farmer",       "per_level": 0.20},
    "industry":  {"name": "Industrialist", "per_level": 0.20},
    "research":  {"name": "Scientist",     "per_level": 0.20},
    "governor":  {"name": "Governor",      "per_level": 0.08},  # all stats
}
SHIP_SKILLS = {
    "weapons":   {"name": "Weapons Master",  "per_level": 2},   # +attack
    "tactics":   {"name": "Battle Tactician", "per_level": 2},  # +hull
}

# Military hulls a ship leader can captain.
WARSHIP_CLASSES = {"frigate", "carrier", "cruiser", "battleship", "dreadnought", "troop_transport"}

_FIRST_NAMES = [
    "Talia", "Marcus", "Vex", "Soren", "Kira", "Dax", "Lyra", "Orin",
    "Zara", "Cael", "Nyx", "Rhea", "Jax", "Mira", "Tobias", "Esha",
    "Garruk", "Vella", "Ren", "Sable",
]
_LAST_NAMES = [
    "Vance", "Korr", "Solari", "Drael", "Voss", "Maru", "Tann", "Quell",
    "Ardent", "Strand", "Holloway", "Vire", "Castellan", "Brask", "Onyx",
    "Wren", "Dross", "Kael", "Sunder", "Marlo",
]


class Leader:
    __slots__ = ("id", "name", "category", "skill", "level", "hire_cost",
                 "salary", "owner_empire_id", "assigned_planet_id",
                 "assigned_ship_id")

    def __init__(self, id, name, category, skill, level, hire_cost, salary,
                 owner_empire_id=None, assigned_planet_id=None, assigned_ship_id=None):
        self.id = id
        self.name = name
        self.category = category          # "colony" | "ship"
        self.skill = skill
        self.level = level
        self.hire_cost = hire_cost
        self.salary = salary
        self.owner_empire_id = owner_empire_id
        self.assigned_planet_id = assigned_planet_id
        self.assigned_ship_id = assigned_ship_id

    @property
    def skill_name(self) -> str:
        table = COLONY_SKILLS if self.category == "colony" else SHIP_SKILLS
        return table.get(self.skill, {}).get("name", self.skill.title())

    def effect_text(self) -> str:
        if self.category == "colony":
            per = COLONY_SKILLS.get(self.skill, {}).get("per_level", 0)
            pct = int(per * self.level * 100)
            stat = {"farming": "food", "industry": "industry",
                    "research": "research", "governor": "all output"}.get(self.skill, "output")
            return f"+{pct}% {stat}"
        per = SHIP_SKILLS.get(self.skill, {}).get("per_level", 0)
        stat = "attack" if self.skill == "weapons" else "hull"
        return f"+{per * self.level} {stat}"


# ---- effect helpers (read by economy + combat) -------------------------

def colony_effect(leader: Leader) -> tuple[float, float, float, float]:
    """Additive output fractions (food, industry, research, bc) for a
    colony leader. Governor lifts all four a little."""
    per = COLONY_SKILLS.get(leader.skill, {}).get("per_level", 0) * leader.level
    if leader.skill == "farming":
        return (per, 0.0, 0.0, 0.0)
    if leader.skill == "industry":
        return (0.0, per, 0.0, 0.0)
    if leader.skill == "research":
        return (0.0, 0.0, per, 0.0)
    if leader.skill == "governor":
        return (per, per, per, per)
    return (0.0, 0.0, 0.0, 0.0)


def ship_effect(leader: Leader) -> tuple[int, int]:
    """(attack_bonus, hull_bonus) for a ship leader."""
    per = SHIP_SKILLS.get(leader.skill, {}).get("per_level", 0) * leader.level
    if leader.skill == "weapons":
        return (per, 0)
    if leader.skill == "tactics":
        return (0, per)
    return (0, 0)


class LeadersManager:
    def __init__(self):
        self.leaders: dict[int, Leader] = {}
        self._next_id = 1
        self.log: list[str] = []

    # -- queries --------------------------------------------------------

    def pool(self) -> list[Leader]:
        return [l for l in self.leaders.values() if l.owner_empire_id is None]

    def for_empire(self, empire_id: int) -> list[Leader]:
        return [l for l in self.leaders.values() if l.owner_empire_id == empire_id]

    def count_for(self, empire_id: int) -> int:
        return sum(1 for l in self.leaders.values() if l.owner_empire_id == empire_id)

    def salary_total(self, empire_id: int) -> int:
        return sum(l.salary for l in self.leaders.values() if l.owner_empire_id == empire_id)

    def colony_leader_for_planet(self, planet_id: int) -> Leader | None:
        for l in self.leaders.values():
            if l.category == "colony" and l.assigned_planet_id == planet_id:
                return l
        return None

    def ship_leader_for_ship(self, ship_id: int) -> Leader | None:
        for l in self.leaders.values():
            if l.category == "ship" and l.assigned_ship_id == ship_id:
                return l
        return None

    # -- mutations ------------------------------------------------------

    def _log(self, msg: str):
        self.log.append(msg)
        if len(self.log) > 60:
            self.log = self.log[-60:]

    def generate_candidate(self) -> Leader:
        category = random.choice(["colony", "ship"])
        skill = random.choice(list((COLONY_SKILLS if category == "colony" else SHIP_SKILLS)))
        level = random.randint(1, 3)
        name = f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"
        hire_cost = 80 + level * 90
        salary = 4 + level * 6
        leader = Leader(self._next_id, name, category, skill, level, hire_cost, salary)
        self.leaders[self._next_id] = leader
        self._next_id += 1
        return leader

    def hire(self, leader_id: int, empire_id: int) -> bool:
        leader = self.leaders.get(leader_id)
        if leader is None or leader.owner_empire_id is not None:
            return False
        if self.count_for(empire_id) >= MAX_LEADERS_PER_EMPIRE:
            return False
        leader.owner_empire_id = empire_id
        leader.assigned_planet_id = None
        leader.assigned_ship_id = None
        return True

    def assign_colony(self, leader_id: int, planet_id: int | None):
        leader = self.leaders.get(leader_id)
        if leader is None or leader.category != "colony":
            return
        # One leader per colony — bump any existing occupant off first.
        if planet_id is not None:
            other = self.colony_leader_for_planet(planet_id)
            if other is not None and other.id != leader_id:
                other.assigned_planet_id = None
        leader.assigned_planet_id = planet_id

    def assign_ship(self, leader_id: int, ship_id: int | None):
        leader = self.leaders.get(leader_id)
        if leader is None or leader.category != "ship":
            return
        if ship_id is not None:
            other = self.ship_leader_for_ship(ship_id)
            if other is not None and other.id != leader_id:
                other.assigned_ship_id = None
        leader.assigned_ship_id = ship_id

    def dismiss(self, leader_id: int):
        """Fire a leader entirely (removed from the game)."""
        self.leaders.pop(leader_id, None)

    # -- persistence ----------------------------------------------------

    def save(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM leaders")
            for l in self.leaders.values():
                conn.execute(
                    "INSERT INTO leaders (id, name, category, skill, level, hire_cost, "
                    "salary, owner_empire_id, assigned_planet_id, assigned_ship_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (l.id, l.name, l.category, l.skill, l.level, l.hire_cost,
                     l.salary, l.owner_empire_id, l.assigned_planet_id, l.assigned_ship_id),
                )
            conn.commit()

    def load(self):
        self.leaders.clear()
        with get_connection() as conn:
            for row in conn.execute("SELECT * FROM leaders"):
                self.leaders[row["id"]] = Leader(
                    row["id"], row["name"], row["category"], row["skill"],
                    row["level"], row["hire_cost"], row["salary"],
                    row["owner_empire_id"], row["assigned_planet_id"],
                    row["assigned_ship_id"],
                )
        self._next_id = (max(self.leaders) + 1) if self.leaders else 1


# ---- per-turn tick -----------------------------------------------------

def _owned_planet_ids(cm, empire_id: int) -> set[int]:
    out: set[int] = set()
    from ecs.components import Planet
    for eid, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        planet = cm.get_component(eid, Planet)
        if planet is not None:
            out.add(planet.id)
    return out


def _owned_ship_ids(cm, empire_id: int) -> set[int]:
    out: set[int] = set()
    for ship_entity, owner in cm.get_all(ShipOwner):
        if owner.empire_id != empire_id:
            continue
        s = cm.get_component(ship_entity, Ship)
        if s is not None:
            out.add(s.id)
    return out


def leaders_tick(game, new_turn: int):
    """Turn callback: validate assignments, pay salaries (fire the
    unpayable), and occasionally float a new candidate into the pool."""
    mgr = getattr(game, "leaders", None)
    if mgr is None:
        return
    cm = game.component_mgr

    empires = [emp for _eid, emp in cm.get_all(Empire)]

    # 1. Validate assignments against current holdings.
    for emp in empires:
        planets = _owned_planet_ids(cm, emp.id)
        ships = _owned_ship_ids(cm, emp.id)
        for l in mgr.for_empire(emp.id):
            if l.assigned_planet_id is not None and l.assigned_planet_id not in planets:
                l.assigned_planet_id = None
            if l.assigned_ship_id is not None and l.assigned_ship_id not in ships:
                l.assigned_ship_id = None

    # 2. Pay salaries; fire the most expensive leaders we can't afford.
    from ecs.db import update_empire_economy
    with get_connection() as conn:
        for emp in empires:
            roster = sorted(mgr.for_empire(emp.id), key=lambda l: l.salary, reverse=True)
            while roster and mgr.salary_total(emp.id) > emp.bc:
                quitter = roster.pop(0)
                mgr.dismiss(quitter.id)
                if emp.is_player:
                    mgr._log(f"{quitter.name} quit — you couldn't make payroll.")
            total = mgr.salary_total(emp.id)
            if total > 0:
                emp.bc = max(0, emp.bc - total)
                update_empire_economy(conn, emp.id, emp.bc, emp.research_points)
        conn.commit()

    # 3. Refresh the hiring pool.
    if len(mgr.pool()) < POOL_CAP and random.random() < CANDIDATE_CHANCE:
        cand = mgr.generate_candidate()
        mgr._log(f"A new {cand.skill_name} ({cand.effect_text()}) is available for hire.")

    mgr.save()

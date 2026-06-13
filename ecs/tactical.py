"""Tactical hex-grid combat — MOO2-style.

A battle is a single-star engagement between two or more empires. The
strategic combat layer (``ecs/combat.py``) detects the engagement; if
the player is one of the participants, it queues a ``TacticalBattle``
on ``game.pending_tactical_battles`` instead of auto-resolving. The
galaxy scene routes to the tactical scene, which lets the player drive
ship movement and weapons fire one round at a time. AI-vs-AI battles
the player isn't in stay on the strategic resolver.

**Stage 1 scope** (this commit):
- 14×7 hex grid, MOO2-like dimensions
- Click to select, click empty hex to move, click enemy to attack
- One move + one attack per ship per round
- Basic enemy AI: each enemy ship moves toward the nearest player
  ship and attacks if any opposing ship is within reach
- Auto button falls back to strategic resolve
- Battle ends when one side has zero ships standing

**Future stages** (not yet implemented):
- Initiative order + action points per ship
- Weapon range falloff
- Shield / armor / hull damage layers
- Missiles, fighters, point defense
- Planetary defense as stationary unit
- Special equipment (cloak, transporter, stasis)

State here is in-memory only — a tactical battle resolves within a
single turn and never spans a save/load boundary, just like MOO2.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# Grid dimensions. MOO2 used roughly 14×7; we keep that.
GRID_COLS = 14
GRID_ROWS = 7

# Pointy-top hex layout in pixels. ``HEX_SIZE`` is the centre-to-corner
# radius (inradius is ``HEX_SIZE * sqrt(3)/2``).
HEX_SIZE = 36
HEX_WIDTH = HEX_SIZE * math.sqrt(3)
HEX_HEIGHT = HEX_SIZE * 2.0
HEX_V_SPACING = HEX_SIZE * 1.5

# Random multiplier on damage rolls so battles aren't fully deterministic.
DAMAGE_MIN_MULT = 0.7
DAMAGE_MAX_MULT = 1.3

# Maximum hexes a ship can step per move action. Stage 1 doesn't model
# AP, but caps movement so a frigate can't traverse the whole grid in
# one click. Distance is the offset-hex axial distance.
MAX_MOVE_PER_ROUND = 4


@dataclass
class TacticalShip:
    """A combatant on the tactical grid. Backed by an ECS ship entity in
    the strategic layer — we keep the entity id so post-battle the same
    ship can be destroyed (or not) up there."""
    entity_id: int
    empire_id: int
    ship_class: str
    name: str
    col: int
    row: int
    hull: int
    max_hull: int
    attack: int
    speed: int = MAX_MOVE_PER_ROUND
    has_moved: bool = False
    has_fired: bool = False
    destroyed: bool = False


@dataclass
class TacticalBattle:
    """One star-system engagement. Built by ``combat.combat_tick`` when
    the player is involved; consumed by the tactical scene."""
    star_entity: int
    star_name: str
    turn: int
    ships: list[TacticalShip] = field(default_factory=list)
    player_id: int = 0
    round: int = 1
    # Set when the battle resolves. ``destroyed_entity_ids`` feeds back
    # into the strategic layer's destruction pass.
    finished: bool = False
    winner_id: int | None = None

    # -- queries -----------------------------------------------------

    def ships_for(self, empire_id: int) -> list[TacticalShip]:
        return [s for s in self.ships if s.empire_id == empire_id and not s.destroyed]

    def ship_at(self, col: int, row: int) -> TacticalShip | None:
        for s in self.ships:
            if s.destroyed:
                continue
            if s.col == col and s.row == row:
                return s
        return None

    def empires_present(self) -> set[int]:
        return {s.empire_id for s in self.ships if not s.destroyed}

    def destroyed_entity_ids(self) -> list[int]:
        return [s.entity_id for s in self.ships if s.destroyed]

    # -- mechanics ---------------------------------------------------

    def move_ship(self, ship: TacticalShip, col: int, row: int) -> bool:
        """Move ``ship`` to ``(col, row)`` if it's a legal step this
        round. Returns True on success. The hex must be in-grid, empty,
        and within the ship's per-round step budget; the ship must not
        have moved already this round."""
        if ship.destroyed or ship.has_moved:
            return False
        if not (0 <= col < GRID_COLS and 0 <= row < GRID_ROWS):
            return False
        if self.ship_at(col, row) is not None:
            return False
        if hex_distance(ship.col, ship.row, col, row) > ship.speed:
            return False
        ship.col, ship.row = col, row
        ship.has_moved = True
        return True

    def attack(self, attacker: TacticalShip, target: TacticalShip,
               rng: random.Random | None = None) -> int:
        """Resolve one shot. Returns damage dealt. Sets ``has_fired``
        on the attacker; marks the target ``destroyed`` if hull <= 0.
        Stage 1: no range falloff, no shields, no point defense — pure
        attack × random multiplier vs hull."""
        if attacker.destroyed or target.destroyed:
            return 0
        if attacker.has_fired:
            return 0
        rng = rng or random
        roll = rng.uniform(DAMAGE_MIN_MULT, DAMAGE_MAX_MULT)
        dmg = max(1, int(round(attacker.attack * roll)))
        target.hull -= dmg
        attacker.has_fired = True
        if target.hull <= 0:
            target.hull = 0
            target.destroyed = True
        return dmg

    def end_round(self):
        """Reset per-round flags. Increment the round counter. Check
        for a winner — if only one empire still has live ships, the
        battle is over."""
        for s in self.ships:
            s.has_moved = False
            s.has_fired = False
        self.round += 1
        empires = self.empires_present()
        if len(empires) <= 1:
            self.finished = True
            self.winner_id = next(iter(empires), None)


# ---- hex math ----------------------------------------------------------

def hex_to_pixel(col: int, row: int, origin_x: float, origin_y: float
                 ) -> tuple[float, float]:
    """Centre pixel for hex ``(col, row)`` in an even-row offset layout."""
    x_offset = (HEX_WIDTH / 2.0) if (row % 2) else 0.0
    px = origin_x + col * HEX_WIDTH + x_offset + HEX_WIDTH / 2.0
    py = origin_y + row * HEX_V_SPACING + HEX_HEIGHT / 2.0
    return (px, py)


def pixel_to_hex(px: float, py: float, origin_x: float, origin_y: float
                 ) -> tuple[int, int]:
    """Click-resolution: walk all hexes and pick the one whose centre
    is closest. O(GRID_COLS * GRID_ROWS) — trivial for a 14×7 grid."""
    best, best_d2 = (-1, -1), float("inf")
    for col in range(GRID_COLS):
        for row in range(GRID_ROWS):
            cx, cy = hex_to_pixel(col, row, origin_x, origin_y)
            d2 = (cx - px) ** 2 + (cy - py) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best = (col, row)
    return best


def hex_distance(c1: int, r1: int, c2: int, r2: int) -> int:
    """Step distance between two offset-coord hexes. Convert each pair
    to cube coordinates and use the standard cube max-coordinate
    formula. Even-row offset (row 0 NOT shifted)."""
    def offset_to_cube(col, row):
        # Even-row offset to cube — even rows are non-shifted, odd rows
        # are shifted right by half a width.
        x = col - (row - (row & 1)) // 2
        z = row
        y = -x - z
        return (x, y, z)
    x1, y1, z1 = offset_to_cube(c1, r1)
    x2, y2, z2 = offset_to_cube(c2, r2)
    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


# ---- AI -----------------------------------------------------------------

def ai_take_turn(battle: TacticalBattle, controlling_empire_id: int,
                 rng: random.Random | None = None) -> list[str]:
    """One AI side acts: every ship moves toward the nearest live
    opposing ship and fires if any opponent is within
    ``MAX_MOVE_PER_ROUND`` after the move. Returns a list of log
    strings so the scene can show what happened.

    Crude on purpose — Stage 1 is about establishing the play loop,
    not chess-grade tactics. Later stages can swap this for a proper
    A* + scoring search.
    """
    rng = rng or random
    log: list[str] = []
    own = battle.ships_for(controlling_empire_id)
    if not own:
        return log

    for ship in own:
        if ship.destroyed:
            continue
        enemies = [s for s in battle.ships
                   if s.empire_id != controlling_empire_id and not s.destroyed]
        if not enemies:
            return log
        # Pick the nearest enemy as our target this turn.
        target = min(enemies, key=lambda e: hex_distance(
            ship.col, ship.row, e.col, e.row))
        dist = hex_distance(ship.col, ship.row, target.col, target.row)
        # Move closer if needed. Pick the best in-range hex that's
        # empty and minimises distance to target.
        if dist > 1 and not ship.has_moved:
            best_dest = None
            best_remaining = dist
            for col in range(GRID_COLS):
                for row in range(GRID_ROWS):
                    if hex_distance(ship.col, ship.row, col, row) > ship.speed:
                        continue
                    if battle.ship_at(col, row) is not None:
                        continue
                    d = hex_distance(col, row, target.col, target.row)
                    if d < best_remaining:
                        best_remaining = d
                        best_dest = (col, row)
            if best_dest is not None:
                battle.move_ship(ship, *best_dest)
        # Now fire if the target is still alive — no range falloff yet.
        if not target.destroyed and not ship.has_fired:
            dmg = battle.attack(ship, target, rng)
            log.append(
                f"{ship.name} hits {target.name} for {dmg}"
                + (" — DESTROYED!" if target.destroyed else "")
            )
    return log

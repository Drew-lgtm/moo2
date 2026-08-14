"""Tactical hex-grid combat — MOO2-style.

A battle is a single-star engagement between two or more empires. The
strategic combat layer (``ecs/combat.py``) detects the engagement; if
the player is one of the participants, it queues a ``TacticalBattle``
on ``game.pending_engagements``. The Combat Options screen lets the
player pick Attack / Auto / Retreat; the tactical scene only runs on
Attack. AI-vs-AI battles the player isn't in stay on the strategic
resolver.

**Stage 2 model** (current):
- 14×7 hex grid, MOO2-like dimensions
- Per-ship movement points spent per hex moved; each ship can fire
  *once* per round (so AP only constrains movement, not attacks)
- Range bands with damage falloff:
  - 1..SHORT_RANGE hexes → full damage
  - SHORT_RANGE+1..LONG_RANGE → ``LONG_RANGE_MULT`` damage
  - beyond LONG_RANGE → can't fire
- Damage flows through three layers: shields (regen) → armor (flat
  reduction per hit) → hull (death at 0)
- Initiative — higher-speed side goes first, displayed in the panel
- Stationary stations represent planetary defense (Star Base /
  Battlestation / Star Fortress). Stations occupy hexes, have high
  shield+armor+hull and big guns, but never move. Damage to a station
  is forgotten at battle end — strategically they remain in place
  per the existing chain of orbital defense buildings.
- Auto button falls back to strategic resolve
- Battle ends when one side has zero standing combatants

**Future stages** (Stage 3+, not yet implemented):
- Missiles flying across the grid, point defense, fighters
- Special equipment (cloak, transporter, stasis, displacement)
- Retreat as a tactical action with relocation cost
- Mounts (Normal / Heavy / Point-Defense weapon variants)

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

# Damage-roll spread lives in the canonical model (ecs/battle.py). Re-
# exported here for any legacy importer; do not redefine — one source.
from ecs.battle import DAMAGE_MIN_MULT, DAMAGE_MAX_MULT  # noqa: F401

# Per-class movement points. MOO2 had this driven by drive tech + a
# ship's tactical-combat speed stat; for Stage 2 we map ship class to
# a flat value. Small ships dart, capital ships lumber.
SHIP_AP = {
    "scout":           7,
    "frigate":          6,
    "freighter":        4,
    "outpost_ship":     3,
    "colony_ship":      3,
    "troop_transport":  4,
    "carrier":          5,
    "cruiser":          5,
    "battleship":       4,
    "dreadnought":      3,
    "titan":            3,
    "doom_star":        2,
}
# Default if a class isn't listed (custom ships, future classes).
DEFAULT_AP = 5

# Range bands in hexes. Computed via cube-distance ``hex_distance``.
SHORT_RANGE = 4   # 1..SHORT_RANGE: full damage
LONG_RANGE = 8    # SHORT_RANGE+1..LONG_RANGE: long-range falloff
LONG_RANGE_MULT = 0.5


def weapon_range_mult(distance: int) -> float:
    """Damage multiplier for a shot at ``distance`` hexes. Returns 0
    when the target is out of range — callers should treat this as
    "can't fire" rather than "deals nothing"."""
    if distance <= 0:
        return 1.0
    if distance <= SHORT_RANGE:
        return 1.0
    if distance <= LONG_RANGE:
        return LONG_RANGE_MULT
    return 0.0


@dataclass
class TacticalShip:
    """A combatant on the tactical grid. Backed by an ECS ship entity in
    the strategic layer for normal ships; stations have ``is_station``
    set and don't map to any ECS entity (their building lives on the
    planet — see ``combat.py`` for placement).
    """
    entity_id: int
    empire_id: int
    ship_class: str
    name: str
    col: int
    row: int
    hull: int
    max_hull: int
    attack: int
    # Movement allowance per round, spent one-for-one per hex.
    speed: int = DEFAULT_AP
    moves_left: int = DEFAULT_AP
    # Defensive layers in front of the hull.
    shield_max: int = 0
    shield_current: int = 0
    shield_regen: int = 0
    armor: int = 0
    # Interceptable ordnance (missile weapons + carrier fighters) and this
    # ship's own interception rating, which feeds its SIDE's per-round
    # interception pool (see TacticalBattle.intercept) — the same
    # side-pooled model the strategic resolver uses.
    missile_attack: int = 0
    point_defense: int = 0
    # Crew veteran rank name (see ecs.veterancy) — display only, so the
    # post-battle report can show what ranks fought.
    veteran_rank: str = "Green"
    # Stationary defensive platforms (Star Base / Battlestation /
    # Star Fortress) — can fire, can be damaged, but never move and
    # don't persist damage into the strategic layer.
    is_station: bool = False
    has_fired: bool = False
    destroyed: bool = False

    @property
    def has_moved(self) -> bool:
        # Backwards-compatible read for code that still asks "moved?"
        # — a ship has effectively moved this round once it can't move
        # any further (no AP left).
        return self.moves_left < self.speed


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
    # Per-empire fire breakdown accumulated as shots resolve, mirroring
    # ecs.battle.resolve_auto's collector so the combat report shows the
    # same numbers whether a battle was played out or auto-resolved:
    # {empire_id: {"beam": int, "missile": int, "intercepted": int}}
    fire_stats: dict = field(default_factory=dict)

    # Per-round point-defense budget per side, spent as incoming ordnance
    # arrives and refreshed in end_round. Pooled per SIDE (not per ship) so
    # a dedicated PD escort actually screens the ships it's escorting —
    # and so a hand-played battle intercepts exactly like an auto-resolved
    # one (ecs.battle.resolve_auto uses the same side-pooled model).
    pd_pool: dict = field(default_factory=dict)

    def intercept(self, empire_id: int, incoming: int) -> int:
        """Spend ``empire_id``'s remaining interception on ``incoming``
        missile/fighter damage. Returns how much was shot down."""
        if incoming <= 0:
            return 0
        if empire_id not in self.pd_pool:
            self.pd_pool[empire_id] = sum(
                s.point_defense for s in self.ships
                if s.empire_id == empire_id and not s.destroyed)
        stopped = min(incoming, self.pd_pool[empire_id])
        self.pd_pool[empire_id] -= stopped
        return stopped

    def tally_fire(self, empire_id: int, key: str, amount: int):
        if not amount:
            return
        row = self.fire_stats.setdefault(
            empire_id, {"beam": 0, "missile": 0, "intercepted": 0})
        row[key] += amount

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
        """Move ``ship`` to ``(col, row)`` if it has enough movement
        points left. Returns True on success. Each hex stepped costs
        one MP. Stations (``is_station``) never move regardless of
        speed value."""
        if ship.destroyed or ship.is_station:
            return False
        if not (0 <= col < GRID_COLS and 0 <= row < GRID_ROWS):
            return False
        if self.ship_at(col, row) is not None:
            return False
        cost = hex_distance(ship.col, ship.row, col, row)
        if cost == 0:
            return False
        if cost > ship.moves_left:
            return False
        ship.col, ship.row = col, row
        ship.moves_left -= cost
        return True

    def attack(self, attacker: TacticalShip, target: TacticalShip,
               rng: random.Random | None = None) -> dict:
        """Resolve one shot. Returns a result dict::

            {"fired": bool, "damage": int, "to_shield": int,
             "to_hull": int, "destroyed": bool, "reason": str | None}

        ``fired`` is False if the attacker can't fire — either already
        fired this round, attacker/target dead, or out of range — and
        ``reason`` carries a short human-readable cause for the UI.

        Damage layers: raw ← attack × random × range-multiplier; armor
        applies as flat reduction (min 1 damage gets through); the
        residual drains shields first, then hull.
        """
        if attacker.destroyed or target.destroyed:
            return {"fired": False, "damage": 0, "to_shield": 0,
                    "to_hull": 0, "destroyed": False, "reason": "no target"}
        if attacker.has_fired:
            return {"fired": False, "damage": 0, "to_shield": 0,
                    "to_hull": 0, "destroyed": False,
                    "reason": "already fired this round"}
        dist = hex_distance(attacker.col, attacker.row, target.col, target.row)
        range_mult = weapon_range_mult(dist)
        if range_mult <= 0:
            return {"fired": False, "damage": 0, "to_shield": 0,
                    "to_hull": 0, "destroyed": False,
                    "reason": "out of range"}
        # Damage math routes through the canonical model in ecs.battle so
        # a tactical shot and an auto-resolved shot use identical rules.
        from ecs import battle as _battle
        rng = rng or random
        raw = _battle.roll_damage(attacker.attack, rng, range_mult)
        # Missile / fighter ordnance is interceptable: the TARGET's
        # point-defense shoots some of it down before it lands, drawing
        # down a per-round budget (mirrors the strategic resolver).
        intercepted = 0
        self.tally_fire(attacker.empire_id, "beam", raw)
        if attacker.missile_attack > 0:
            missile_raw = _battle.roll_damage(attacker.missile_attack, rng,
                                              range_mult)
            self.tally_fire(attacker.empire_id, "missile", missile_raw)
            intercepted = self.intercept(target.empire_id, missile_raw)
            self.tally_fire(target.empire_id, "intercepted", intercepted)
            raw += missile_raw - intercepted
        view = _combatant_view(target)
        result = _battle.apply_hit(view, raw) if raw > 0 else {
            "damage": 0, "to_shield": 0, "to_hull": 0, "destroyed": False}
        target.shield_current = view.shield
        target.hull = view.hull
        target.destroyed = view.destroyed
        attacker.has_fired = True
        return {"fired": True, "damage": result["damage"],
                "to_shield": result["to_shield"], "to_hull": result["to_hull"],
                "intercepted": intercepted,
                "destroyed": view.destroyed, "reason": None}

    def end_round(self):
        """Reset per-round flags. Regenerate each ship's shield up to
        its max. Increment the round counter. If only one empire still
        has live combatants, mark the battle finished."""
        for s in self.ships:
            if s.destroyed:
                continue
            s.has_fired = False
            s.moves_left = s.speed
            if s.shield_max > 0:
                s.shield_current = min(s.shield_max,
                                        s.shield_current + s.shield_regen)
        # Interceptors rearm: recomputed lazily from the surviving ships,
        # so losses shrink a side's screen.
        self.pd_pool.clear()
        self.round += 1
        empires = self.empires_present()
        if len(empires) <= 1:
            self.finished = True
            self.winner_id = next(iter(empires), None)

    def initiative_order(self) -> list[int]:
        """Empire ids sorted by combined speed of standing ships,
        highest first. Just for display in the side panel."""
        scores: dict[int, int] = {}
        for s in self.ships:
            if s.destroyed:
                continue
            scores[s.empire_id] = scores.get(s.empire_id, 0) + s.speed
        return [eid for eid, _ in sorted(scores.items(),
                                          key=lambda r: -r[1])]


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

def _combatant_view(ship: "TacticalShip"):
    """A ``battle.Combatant`` mirror of a TacticalShip, so the canonical
    damage functions can operate on it. Field names differ (TacticalShip
    predates the unified model) — this bridges them. The caller copies
    the mutated shield/hull/destroyed back onto the ship."""
    from ecs.battle import Combatant
    return Combatant(
        key=ship, empire_id=ship.empire_id, attack=ship.attack,
        hull=ship.hull, hull_max=ship.max_hull,
        shield=ship.shield_current, shield_max=ship.shield_max,
        shield_regen=ship.shield_regen, defense=ship.armor,
        # Carry the interceptable ordnance + PD through, so an
        # auto-resolved tactical battle applies the same missile-vs-
        # point-defense rules as a hand-played one.
        missile_attack=ship.missile_attack, point_defense=ship.point_defense,
    )


def auto_resolve(tbattle: TacticalBattle, rng: random.Random | None = None,
                 hostile_fn=None):
    """Resolve a whole tactical battle non-interactively via the shared
    ``battle.resolve_auto``. Mutates the TacticalShips in place (hull /
    shield / destroyed) and stamps ``finished`` + ``winner_id``.

    Stations participate as ordinary combatants here (the fortress can be
    overwhelmed within a tactical engagement); strategic indestructibility
    is a separate concern handled by the orbital-defense building chain.
    """
    from ecs import battle as _battle
    rng = rng or random
    by_eid: dict[int, list] = {}
    for s in tbattle.ships:
        if s.destroyed:
            continue
        by_eid.setdefault(s.empire_id, []).append(_combatant_view(s))

    # Who actually fights whom. Defaults to "everyone present is an enemy"
    # (fine for the usual two-sided engagement), but the caller should pass
    # the real diplomacy predicate so a neutral third empire parked at a
    # contested star isn't shot down in someone else's battle.
    hostile = hostile_fn or (lambda a, b: a != b)

    # Collect the same fire breakdown a hand-played battle records, so the
    # post-battle report is populated either way.
    stats: dict = {}
    _battle.resolve_auto(by_eid, {}, hostile, rng, stats=stats)
    for eid, row in stats.items():
        for key, amount in row.items():
            tbattle.tally_fire(eid, key, amount)
    for side in by_eid.values():
        for c in side:
            ship = c.key
            ship.hull = c.hull
            ship.shield_current = c.shield
            if c.destroyed:
                ship.destroyed = True
    tbattle.finished = True
    empires = tbattle.empires_present()
    tbattle.winner_id = next(iter(empires), None) if len(empires) == 1 else None


def battle_report(tbattle: TacticalBattle,
                  attack_by_eid_before: dict[int, int]) -> dict:
    """Build a combat-report row (same schema as the strategic
    ``combat.py`` log entry) from a resolved TacticalBattle. Shared by
    the tactical scene's finalise and the Combat Options auto-resolve so
    the post-battle summary looks identical whichever path ran."""
    sides = []
    empires = {s.empire_id for s in tbattle.ships}
    for eid in empires:
        by_class: dict[str, int] = {}
        veterans: dict[str, int] = {}
        total = 0
        lost = 0
        for s in tbattle.ships:
            if s.empire_id != eid:
                continue
            # Stations are planetary structures, not fleet — they're
            # re-manned from the orbital-defense building each turn, so
            # they never count as a ship loss in the report.
            if s.is_station:
                continue
            by_class[s.ship_class] = by_class.get(s.ship_class, 0) + 1
            veterans[s.veteran_rank] = veterans.get(s.veteran_rank, 0) + 1
            total += 1
            if s.destroyed:
                lost += 1
        fire = tbattle.fire_stats.get(eid, {})
        # Stations aren't fleet losses, but their firepower IS this side's
        # planetary defense — reporting 0 made a station-only defender look
        # like it never fought.
        station_attack = sum(s.attack + s.missile_attack for s in tbattle.ships
                             if s.empire_id == eid and s.is_station)
        sides.append({
            "empire_id": eid,
            "attack": attack_by_eid_before.get(eid, 0),
            "defense": station_attack,
            "ships_before": by_class,
            "total_before": total,
            "lost": lost,
            "remaining": total - lost,
            # Same observability keys the strategic path records, so the
            # player's OWN battles show the fire/interception breakdown.
            "beam_fired": fire.get("beam", 0),
            "missile_fired": fire.get("missile", 0),
            "intercepted": fire.get("intercepted", 0),
            "veterans": veterans,
        })
    return {
        "turn": tbattle.turn,
        "star_entity": tbattle.star_entity,
        "sides": sides,
        "losses_by_empire": {s["empire_id"]: s["lost"] for s in sides if s["lost"]},
        "attack_by_empire": {s["empire_id"]: s["attack"] for s in sides},
        "observed": False,
    }


def ai_take_turn(battle: TacticalBattle, controlling_empire_id: int,
                 rng: random.Random | None = None) -> list[str]:
    """One AI side acts: every ship picks the nearest opponent, moves
    into SHORT_RANGE if it can, then fires (if the target is now in
    LONG_RANGE at worst). Stations skip the movement step. Returns
    log lines so the scene can show what happened.

    Crude on purpose — later stages can swap for an A* + scoring
    search if we want craftier AI.
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
        target = min(enemies, key=lambda e: hex_distance(
            ship.col, ship.row, e.col, e.row))
        # Move (stations can't, ships try to close to SHORT_RANGE).
        if not ship.is_station and ship.moves_left > 0:
            dist = hex_distance(ship.col, ship.row, target.col, target.row)
            if dist > SHORT_RANGE:
                # Pick the reachable empty hex with the lowest distance
                # to the target. Try to land inside SHORT_RANGE when
                # possible; otherwise just close as much as we can.
                best_dest = None
                best_remaining = dist
                for col in range(GRID_COLS):
                    for row in range(GRID_ROWS):
                        cost = hex_distance(ship.col, ship.row, col, row)
                        if cost == 0 or cost > ship.moves_left:
                            continue
                        if battle.ship_at(col, row) is not None:
                            continue
                        d = hex_distance(col, row, target.col, target.row)
                        if d < best_remaining:
                            best_remaining = d
                            best_dest = (col, row)
                if best_dest is not None:
                    battle.move_ship(ship, *best_dest)
        # Fire if in range.
        if not target.destroyed and not ship.has_fired:
            result = battle.attack(ship, target, rng)
            if result["fired"]:
                tag = " — DESTROYED!" if result["destroyed"] else ""
                detail = []
                if result["to_shield"]:
                    detail.append(f"{result['to_shield']} shield")
                if result["to_hull"]:
                    detail.append(f"{result['to_hull']} hull")
                detail_s = ", ".join(detail) if detail else f"{result['damage']}"
                log.append(
                    f"{ship.name} hits {target.name} ({detail_s}){tag}"
                )
    return log

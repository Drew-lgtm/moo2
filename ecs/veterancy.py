"""Ship veterancy — crews learn from battle.

MOO2 ships climb a rank ladder (Green → Regular → Veteran → Elite →
Ultra-Elite) as they survive combat and rack up kills. Higher ranks
sharpen a ship's guns and toughen its hull, so a long-lived fleet is
worth more than its raw tonnage — and worth protecting.

A ship earns experience when it SURVIVES a battle (a flat amount) plus a
bonus per enemy ship its side destroyed. The rank a ship fights at is
its stored experience at the start of the battle (you earn the reward
for *this* fight afterward). Colony-less pseudo-empire craft (Antaran
raiders, space monsters — negative ECS ids, never in the DB) don't bank
experience; they're transient.

State: ``Ship.experience`` (int), persisted in the ships table.
"""
from __future__ import annotations

from ecs.components import Ship
from ecs.db import get_connection, update_ship_experience


# Experience needed to reach each rank, and the rank names.
RANK_THRESHOLDS = [0, 100, 300, 700, 1500]
RANK_NAMES = ["Green", "Regular", "Veteran", "Elite", "Ultra-Elite"]

# Experience awarded to each surviving ship: a flat share for showing up,
# plus a bounty per enemy ship its side destroyed.
XP_PER_BATTLE = 20
XP_PER_KILL = 40

# Per-rank combat bonuses (index 0..4).
_ATTACK_PER_RANK = 1     # +1 attack per rank  -> +0..+4
_HULL_PER_RANK = 2       # +2 hull per rank    -> +0..+8


def rank_index(xp: int) -> int:
    idx = 0
    for i, threshold in enumerate(RANK_THRESHOLDS):
        if xp >= threshold:
            idx = i
    return idx


def rank_name(xp: int) -> str:
    return RANK_NAMES[rank_index(xp)]


def attack_bonus(xp: int) -> int:
    return rank_index(xp) * _ATTACK_PER_RANK


def hull_bonus(xp: int) -> int:
    return rank_index(xp) * _HULL_PER_RANK


def ship_experience(ship) -> int:
    return getattr(ship, "experience", 0) or 0


def battle_xp(enemies_killed: int) -> int:
    return XP_PER_BATTLE + XP_PER_KILL * max(0, enemies_killed)


def grant_combat_xp(game, ship_entities, enemies_killed: int):
    """Award post-battle experience to the given surviving ship entities
    and persist it. No-ops for ECS-only (negative-id) pseudo-empire ships,
    which aren't in the DB and don't level up."""
    gain = battle_xp(enemies_killed)
    if gain <= 0 or not ship_entities:
        return
    cm = game.component_mgr
    updates = []
    for e in ship_entities:
        ship = cm.get_component(e, Ship)
        if ship is None or ship.id is None or ship.id < 0:
            continue
        ship.experience = ship_experience(ship) + gain
        updates.append((ship.id, ship.experience))
    if updates:
        with get_connection() as conn:
            for sid, xp in updates:
                update_ship_experience(conn, sid, xp)
            conn.commit()


def award_battle_veterancy(game, battle):
    """Award post-battle XP from a resolved tactical battle (duck-typed:
    ``battle.ships`` with ``entity_id``/``empire_id``/``is_station`` and
    ``battle.destroyed_entity_ids()``). Used by the player's tactical /
    auto-resolve finishers, which bypass the strategic XP path."""
    destroyed = set(battle.destroyed_entity_ids())
    survivors: dict[int, list[int]] = {}
    losses: dict[int, int] = {}
    for s in battle.ships:
        if getattr(s, "is_station", False):
            continue  # planetary stations aren't ships and don't level up
        if s.entity_id in destroyed:
            losses[s.empire_id] = losses.get(s.empire_id, 0) + 1
        else:
            survivors.setdefault(s.empire_id, []).append(s.entity_id)
    for eid, ships in survivors.items():
        enemies = sum(c for o, c in losses.items() if o != eid)
        grant_combat_xp(game, ships, enemies)

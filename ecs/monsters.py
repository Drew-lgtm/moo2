"""Space monsters — system guardians.

Master of Orion 2 seeds the galaxy with monsters (Space Dragons,
Amoebas, Crystals, Hydras, Eels) squatting on juicy systems. You can't
settle the system until you bring a fleet and kill the guardian — a
risk/reward gate on the best real estate, and an early target for a
young navy.

Model (mirrors the Antaran pseudo-empire pattern, ecs/antaran.py):

- A **Monster pseudo-empire** (id 9002) exists only to name/colour the
  guardians in combat. It owns no colonies, so the economy / council /
  endgame loops that key off owned planets ignore it — with ONE
  exception now handled: ``endgame.check_endgame`` used to scrap the
  fleet of every colony-less empire, which would delete guardians (and
  Antaran raiders); it now skips pseudo-empires.
- Guardians are **ECS-only ships** (negative ids) owned by the monster
  empire, hostile to all via ``combat._hostile``. Unlike Antaran raids
  (transient), guardians **persist**: a small ``space_monsters`` table
  records each one and whether it's still alive, so a killed guardian
  stays dead across save/load.

State: ``game.space_monsters`` is a list of live-guardian dicts::

    {"id": db_row_id, "star_entity": int, "star_db_id": int,
     "name": str, "entities": [ship_entity, ...]}
"""
from __future__ import annotations

from ecs.components import (
    Empire, Owner, Planet, Orbiting, StarRef, Name,
    Ship, ShipOwner, ShipAt, ShipInTransit,
)
from ecs.db import (
    get_connection, insert_space_monster, get_space_monsters,
    mark_space_monster_dead, update_space_monster_ships, update_empire_economy,
)
from ecs.antaran import is_antaran
from ecs.turn_log import log as turn_log, CAT_COMBAT


MONSTER_EMPIRE_ID = 9002
MONSTER_RACE = "Monster"
MONSTER_COLOR = "red"

# Each guarded system holds a small pack of tough hulls with apex,
# tech-independent gear — a real fight for a young navy, clearable by a
# committed mid-game fleet.
GUARDIAN_HULL = "battleship"
GUARDIAN_LOADOUT = {
    "armor_tech": "xentronium_armor",
    "shield_tech": "class_vii_shield",
    "weapon_tech": "death_ray",
    "weapon_count": 2,
    "weapon_mount": "heavy",
}
GUARDIAN_SHIPS_PER = 2

MONSTER_NAMES = ["Space Dragon", "Space Amoeba", "Space Crystal",
                 "Space Hydra", "Space Eel"]

# Roughly one guardian per this many star systems (at least one on any
# map big enough to have a spare rich system).
STARS_PER_GUARDIAN = 12

# Bounty paid to whoever clears a guardian — a meaningful early leg-up.
KILL_REWARD_BC = 400
KILL_REWARD_RESEARCH = 200

# ECS-only ship ids for guardians count down from here so they never
# collide with real (positive, DB-assigned) ship ids. Derived from the
# guardian's DB row id so they're stable across a save/load.
_MONSTER_SHIP_ID_BASE = -8000


def is_monster(empire_id) -> bool:
    return empire_id == MONSTER_EMPIRE_ID


def is_pseudo_empire(empire_id) -> bool:
    """The colony-less, hostile-to-all factions (Antaran raiders, space
    monsters). They must be filtered out of every real-empire loop —
    diplomacy, espionage, events, council, UI counts."""
    return is_antaran(empire_id) or is_monster(empire_id)


def ensure_monster_empire(game):
    """Create the Monster pseudo-empire ECS entity if absent (never
    persisted to the empires table — recreated on demand)."""
    cm = game.component_mgr
    for eid, emp in cm.get_all(Empire):
        if emp.id == MONSTER_EMPIRE_ID:
            return eid
    e = game.entity_mgr.create_entity()
    cm.add_component(e, Empire(
        id=MONSTER_EMPIRE_ID, name="Space Monsters", race_type=MONSTER_RACE,
        color=MONSTER_COLOR, tech_level=99, home_star_id=None,
        is_player=False,
    ))
    return e


def _guardian_count(num_systems: int) -> int:
    return max(1, num_systems // STARS_PER_GUARDIAN)


def _guardian_ship_id(row_id: int, index: int) -> int:
    return _MONSTER_SHIP_ID_BASE - row_id * 10 - index


def _create_guardian_ships(game, star_entity: int, row_id: int,
                           count: int = GUARDIAN_SHIPS_PER) -> list[int]:
    """Spawn ``count`` of this guardian's ECS ships at ``star_entity``."""
    cm = game.component_mgr
    entities = []
    for i in range(count):
        e = game.entity_mgr.create_entity()
        cm.add_component(e, Ship(
            id=_guardian_ship_id(row_id, i), ship_class=GUARDIAN_HULL,
            armor_tech=GUARDIAN_LOADOUT["armor_tech"],
            shield_tech=GUARDIAN_LOADOUT["shield_tech"],
            weapon_tech=GUARDIAN_LOADOUT["weapon_tech"],
            weapon_count=GUARDIAN_LOADOUT["weapon_count"],
            weapon_mount=GUARDIAN_LOADOUT["weapon_mount"],
            specials=[],
        ))
        cm.add_component(e, ShipOwner(empire_id=MONSTER_EMPIRE_ID))
        cm.add_component(e, ShipAt(star_entity=star_entity))
        entities.append(e)
    return entities


def _candidate_stars(cm):
    """Unowned star systems with at least one colonisable planet, best
    first. Score = number of colonisable planets; ties broken by star
    entity id for determinism. Home systems (any owned planet) excluded."""
    planets_by_star: dict[int, list[int]] = {}
    owned_stars: set[int] = set()
    for planet_entity, orbit in cm.get_all(Orbiting):
        planet = cm.get_component(planet_entity, Planet)
        if planet is None:
            continue
        planets_by_star.setdefault(orbit.star_entity, []).append(planet_entity)
        if cm.get_component(planet_entity, Owner) is not None:
            owned_stars.add(orbit.star_entity)

    scored = []
    for star_entity, planets in planets_by_star.items():
        if star_entity in owned_stars:
            continue
        colonizable = sum(
            1 for pe in planets
            if cm.get_component(pe, Planet).colonizable)
        if colonizable <= 0:
            continue
        scored.append((colonizable, star_entity))
    # Best (most colonisable) first; deterministic tiebreak by entity id.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [se for _score, se in scored], len(planets_by_star)


def spawn_guardians(game):
    """New-game hook: place guardians on the richest unowned systems,
    record them in the DB, and create their ECS ships. Populates
    ``game.space_monsters``."""
    cm = game.component_mgr
    game.space_monsters = []
    candidates, num_systems = _candidate_stars(cm)
    if not candidates:
        return
    n = min(_guardian_count(num_systems), len(candidates))
    if n <= 0:
        return
    ensure_monster_empire(game)
    with get_connection() as conn:
        for i in range(n):
            star_entity = candidates[i]
            star_ref = cm.get_component(star_entity, StarRef)
            if star_ref is None:
                continue
            name = MONSTER_NAMES[i % len(MONSTER_NAMES)]
            row_id = insert_space_monster(conn, star_ref.db_id, name,
                                          GUARDIAN_SHIPS_PER)
            entities = _create_guardian_ships(game, star_entity, row_id)
            game.space_monsters.append({
                "id": row_id, "star_entity": star_entity,
                "star_db_id": star_ref.db_id, "name": name,
                "entities": entities,
            })
        conn.commit()


def load_guardians(game):
    """Load-game hook: recreate ECS ships for every still-alive guardian
    recorded in the DB. Populates ``game.space_monsters``."""
    cm = game.component_mgr
    game.space_monsters = []
    rows = get_space_monsters(alive_only=True)
    if not rows:
        return
    star_by_db = {ref.db_id: ent for ent, ref in cm.get_all(StarRef)}
    ensure_monster_empire(game)
    for row in rows:
        star_entity = star_by_db.get(row["star_id"])
        if star_entity is None:
            continue  # star no longer exists (shouldn't happen) — skip
        # Restore only the surviving hulls (partial losses persist).
        count = row["ships"] if row["ships"] is not None else GUARDIAN_SHIPS_PER
        if count <= 0:
            continue
        entities = _create_guardian_ships(game, star_entity, row["id"], count)
        game.space_monsters.append({
            "id": row["id"], "star_entity": star_entity,
            "star_db_id": row["star_id"], "name": row["monster_type"],
            "entities": entities,
        })


def monster_at_star(cm, star_entity: int) -> bool:
    """True if a living guardian ship sits at this star (blocks
    colonisation of the system)."""
    for ship_entity, at in cm.get_all(ShipAt):
        if at.star_entity != star_entity:
            continue
        owner = cm.get_component(ship_entity, ShipOwner)
        if owner is not None and is_monster(owner.empire_id):
            return True
    return False


def _victor_at_star(cm, star_entity: int):
    """The (non-monster) empire with the most warships at this star after
    a guardian dies — treated as the one that cleared it. None on mutual
    destruction (no surviving fleet)."""
    counts: dict[int, int] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        if at.star_entity != star_entity:
            continue
        owner = cm.get_component(ship_entity, ShipOwner)
        ship = cm.get_component(ship_entity, Ship)
        if owner is None or ship is None or is_pseudo_empire(owner.empire_id):
            continue
        counts[owner.empire_id] = counts.get(owner.empire_id, 0) + 1
    if not counts:
        return None
    # Most ships wins; deterministic tiebreak by lowest empire id.
    return max(counts, key=lambda e: (counts[e], -e))


def _grant_kill_reward(game, guardian):
    cm = game.component_mgr
    victor_id = _victor_at_star(cm, guardian["star_entity"])
    if victor_id is None:
        return
    emp = next((e for _x, e in cm.get_all(Empire) if e.id == victor_id), None)
    if emp is None:
        return
    emp.bc += KILL_REWARD_BC
    emp.research_points += KILL_REWARD_RESEARCH
    with get_connection() as conn:
        update_empire_economy(conn, victor_id, emp.bc, emp.research_points)
        conn.commit()
    player = game.player_empire() if hasattr(game, "player_empire") else None
    if player is not None and victor_id == player.id:
        sn = cm.get_component(guardian["star_entity"], Name)
        star_name = sn.value if sn else "a system"
        turn_log(game, CAT_COMBAT,
                 f"Slew the {guardian['name']} at {star_name}! "
                 f"+{KILL_REWARD_BC} BC, +{KILL_REWARD_RESEARCH} RP")


def reconcile_kills(game):
    """Detect guardians whose ships were destroyed in combat — mark them
    dead in the DB and reward whoever cleared the system — and persist
    partial losses so a reload can't restore destroyed hulls.

    Called from BOTH the post-combat turn tick (catches AI auto-resolved
    kills) AND the tactical / auto-resolve battle finalisers (catches the
    player's kills, which resolve *after* advance_turn returns). Idempotent:
    a cleared guardian is dropped from ``game.space_monsters`` so it's
    never rewarded twice.
    """
    active = getattr(game, "space_monsters", None)
    if not active:
        return
    cm = game.component_mgr
    survivors = []
    killed = []
    count_changes = []  # (row_id, surviving_count)
    for g in active:
        living = [e for e in g["entities"]
                  if cm.get_component(e, Ship) is not None]
        if living:
            if len(living) != len(g["entities"]):
                count_changes.append((g["id"], len(living)))
            g["entities"] = living  # prune any losses
            survivors.append(g)
        else:
            killed.append(g)
    if killed or count_changes:
        with get_connection() as conn:
            for g in killed:
                mark_space_monster_dead(conn, g["id"])
            for row_id, cnt in count_changes:
                update_space_monster_ships(conn, row_id, cnt)
            conn.commit()
        for g in killed:
            _grant_kill_reward(game, g)
    game.space_monsters = survivors


def monster_tick(game, turn: int):
    """Turn callback (runs AFTER combat): reconcile AI-resolved kills."""
    reconcile_kills(game)

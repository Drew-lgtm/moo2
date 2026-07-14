"""Antaran raiders — the recurring end-game threat.

Master of Orion 2's Antarans periodically burst out of their pocket
dimension to raid a colony, then vanish. They're not a normal empire:
they hold no territory, don't research or trade, and are hostile to
*everyone*. Surviving their raids (and eventually striking back through
a Dimensional Portal) is a late-game pillar.

This module models the raids:

- An **Antaran pseudo-empire** exists only to give the raiders a name
  and colour in combat reports / on the map. It owns no colonies, so
  the economy, AI, endgame and council loops that key off owned planets
  ignore it automatically; the few loops that iterate *every* empire
  (AI planning, the diplomacy / espionage rival lists) skip it via
  ``is_antaran``.
- **Raider ships are ECS-only** (negative ids, never written to the
  ``ships`` table). They live for a short window then retreat. Combat
  treats them as hostile to all (see ``combat._hostile``), so the
  player fights them in the tactical scene with the fleets and
  planetary defences they've built — the payoff for that investment.

State: ``game.antaran_raid`` holds the active raid (or None). Raids
don't survive a save/load (they're a transient event), which is fine —
a fresh one arrives on schedule.
"""
from __future__ import annotations

from ecs.components import (
    Empire, Owner, Population, Orbiting, Position, Name, StarRef,
    Ship, ShipOwner, ShipAt, ShipInTransit,
)
from ecs.turn_log import log as turn_log, CAT_COMBAT


ANTARAN_EMPIRE_ID = 9001
ANTARAN_RACE = "Antaran"
ANTARAN_COLOR = "purple"

# Schedule. Raids begin mid-game and recur; fleet size scales with the
# turn so the threat keeps pace with the player's growing navy.
RAID_FIRST_TURN = 40
RAID_INTERVAL = 25
RAID_DURATION = 3          # turns raiders linger before retreating
RAID_BASE_SHIPS = 2
RAID_SHIPS_PER_40_TURNS = 1
RAID_MAX_SHIPS = 8

# Raider hull + the fearsome loadout frozen onto each (independent of
# any empire's tech — Antaran gear is always top-tier).
RAID_HULL = "battleship"
RAID_LOADOUT = {
    "armor_tech": "xentronium_armor",
    "shield_tech": "class_vii_shield",
    "weapon_tech": "death_ray",
    "weapon_count": 4,
    "weapon_mount": "heavy",
    "specials": [],
}

# ECS-only ship ids for raiders count down from here so they never
# collide with real (positive, DB-assigned) ship ids.
_ANTARAN_SHIP_ID_BASE = -9000


def is_antaran(empire_id) -> bool:
    return empire_id == ANTARAN_EMPIRE_ID


def ensure_antaran_empire(game):
    """Create the Antaran pseudo-empire ECS entity if it doesn't exist
    yet (it's not persisted — recreated on demand). Returns its entity
    id."""
    cm = game.component_mgr
    for eid, emp in cm.get_all(Empire):
        if emp.id == ANTARAN_EMPIRE_ID:
            return eid
    e = game.entity_mgr.create_entity()
    cm.add_component(e, Empire(
        id=ANTARAN_EMPIRE_ID, name="Antarans", race_type=ANTARAN_RACE,
        color=ANTARAN_COLOR, tech_level=99, home_star_id=None,
        is_player=False,
    ))
    return e


def _raid_ship_count(turn: int) -> int:
    n = RAID_BASE_SHIPS + (turn // 40) * RAID_SHIPS_PER_40_TURNS
    return min(RAID_MAX_SHIPS, n)


def _strongest_colony_star(cm):
    """Highest-population colony in the galaxy (the Antarans hit the
    juiciest target). Returns (star_entity, owner_id, planet_entity) or
    (None, None, None). Ties broken by lowest planet entity id for
    determinism."""
    best = None  # (pop, -planet_entity, star, owner, planet)
    for planet_entity, owner in cm.get_all(Owner):
        pop = cm.get_component(planet_entity, Population)
        orbit = cm.get_component(planet_entity, Orbiting)
        if pop is None or orbit is None:
            continue
        key = (pop.current, -planet_entity)
        if best is None or key > best[0]:
            best = (key, orbit.star_entity, owner.empire_id, planet_entity)
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def _spawn_raid(game, turn: int):
    cm = game.component_mgr
    star, target_owner, target_planet = _strongest_colony_star(cm)
    if star is None:
        return None
    ensure_antaran_empire(game)
    n = _raid_ship_count(turn)
    entities = []
    for i in range(n):
        e = game.entity_mgr.create_entity()
        cm.add_component(e, Ship(
            id=_ANTARAN_SHIP_ID_BASE - i, ship_class=RAID_HULL,
            armor_tech=RAID_LOADOUT["armor_tech"],
            shield_tech=RAID_LOADOUT["shield_tech"],
            weapon_tech=RAID_LOADOUT["weapon_tech"],
            weapon_count=RAID_LOADOUT["weapon_count"],
            weapon_mount=RAID_LOADOUT["weapon_mount"],
            specials=list(RAID_LOADOUT["specials"]),
        ))
        cm.add_component(e, ShipOwner(empire_id=ANTARAN_EMPIRE_ID))
        cm.add_component(e, ShipAt(star_entity=star))
        entities.append(e)

    star_name_comp = cm.get_component(star, Name)
    star_name = star_name_comp.value if star_name_comp else "a colony"
    # Warn the player if it's their world (or nearby); it's always news.
    player = game.player_empire()
    if player is not None:
        if target_owner == player.id:
            turn_log(game, CAT_COMBAT,
                     f"ANTARAN RAID on {star_name}! {n} warships incoming.")
        else:
            turn_log(game, CAT_COMBAT,
                     f"Antarans raid {star_name} ({n} ships).")
    return {"entities": entities, "star": star, "planet": target_planet,
            "leave_turn": turn + RAID_DURATION}


def _despawn_raid(game):
    """Remove any surviving raiders (retreat to Antares)."""
    cm = game.component_mgr
    raid = getattr(game, "antaran_raid", None)
    if not raid:
        return
    for e in raid["entities"]:
        # May already be destroyed in combat; guard each removal.
        if cm.get_component(e, Ship) is not None:
            for comp in (Ship, ShipOwner, ShipAt, ShipInTransit):
                cm.remove_component(e, comp)
            game.entity_mgr.destroy_entity(e)
    game.antaran_raid = None


def _living_raiders(game) -> int:
    cm = game.component_mgr
    raid = getattr(game, "antaran_raid", None)
    if not raid:
        return 0
    return sum(1 for e in raid["entities"]
               if cm.get_component(e, Ship) is not None)


def _antaran_bombard(game, raid):
    """Surviving raiders shell the target colony — so an undefended
    world still suffers even when no fleet or planetary defence
    contests the system. Reuses the standard bombardment (declare_war
    False — Antarans aren't in the diplomacy system)."""
    cm = game.component_mgr
    planet_entity = raid.get("planet")
    if planet_entity is None:
        return
    from ecs.bombard import can_bombard, bombard_planet
    if not can_bombard(cm, planet_entity, ANTARAN_EMPIRE_ID):
        return
    result = bombard_planet(game, planet_entity, ANTARAN_EMPIRE_ID,
                            declare_war=False)
    if not result.get("success"):
        return
    player = game.player_empire()
    owner = cm.get_component(planet_entity, Owner)
    # Owner may be gone if the colony was just destroyed — check pre-check.
    if player is not None:
        star = cm.get_component(raid["star"], Name)
        star_name = star.value if star else "a colony"
        if result.get("colony_destroyed"):
            turn_log(game, CAT_COMBAT, f"Antarans obliterated {star_name}!")
        elif result.get("pop_lost"):
            turn_log(game, CAT_COMBAT,
                     f"Antarans bombard {star_name}: -{result['pop_lost']}M pop")


def antaran_tick(game, turn: int):
    """Turn callback: retire a finished/destroyed raid, bombard the
    target with surviving raiders, then spawn a new raid on schedule.

    Bombardment happens the turn AFTER arrival (a fresh raid is created
    at the end of this tick and shells the colony on subsequent ticks),
    so a player fleet that wipes the raiders on the arrival turn's combat
    prevents any bombardment."""
    raid = getattr(game, "antaran_raid", None)
    if raid is not None:
        if turn >= raid["leave_turn"] or _living_raiders(game) == 0:
            _despawn_raid(game)
            raid = None
        else:
            _antaran_bombard(game, raid)

    if raid is None and turn >= RAID_FIRST_TURN \
            and (turn - RAID_FIRST_TURN) % RAID_INTERVAL == 0:
        game.antaran_raid = _spawn_raid(game, turn)

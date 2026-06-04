"""Random galactic events.

Each turn this module:

1. **Resolves active plagues** — if any colony has ``plague_turns > 0``,
   one million pop dies, growth is suppressed for the turn, and the
   counter ticks down. The duration is shorter if the empire has
   Microbiotics tech.

2. **Rolls for a new event** — with probability ``EVENT_BASE_CHANCE``
   per turn, one event fires from the weighted catalog:

   - **Derelict Ship** — a free random tech the empire doesn't have.
   - **Plague Outbreak** — strikes a random colony; runs 4-6 turns.
   - **Pirate Raid** — a random BC drain on the empire's treasury.

Events are logged to ``game.events_log`` so scenes can surface them,
and player-relevant lines are also routed through the existing
Espionage report log so the player sees them in the Intelligence panel
without a dedicated UI.
"""
from __future__ import annotations

import random

from ecs.components import Empire, Owner, Population, Planet, TechState
from ecs.techs import TECHS, is_available
from ecs.db import (
    get_connection, insert_empire_tech, update_empire_economy,
    update_planet_population, update_planet_workers, update_planet_plague,
    update_empire_tech, delete_planet_building,
)
from ecs.components import BuildState
from ecs.projects import PROJECTS


# Per-turn chance ANY event fires. Tuned conservative so events feel
# like an occasional spike, not a constant nuisance.
EVENT_BASE_CHANCE = 0.12

# Weighted catalog. Higher weight = more likely when an event fires.
# Roughly balanced 8 positive : 10 negative weight — slight adversity
# bias keeps the game tense without feeling punitive.
EVENT_WEIGHTS = {
    # Positive
    "derelict":         2,    # free random tech
    "trader":           2,    # +BC
    "pop_boom":         2,    # +pop on a colony
    "tech_breakthrough": 2,   # +RP onto current research target
    # Negative
    "plague":           3,    # multi-turn pop loss
    "pirate_raid":      3,    # BC drain
    "solar_flare":      2,    # 1 building destroyed
    "comet_strike":     2,    # 1 pop + 1 building lost
}

# Plague tuning.
PLAGUE_MIN_TURNS = 4
PLAGUE_MAX_TURNS = 6
PLAGUE_MICROBIOTICS_REDUCTION = 2  # turns shaved off when Microbiotics is researched

# Pirate raid tuning — a percentage hit on the empire's treasury,
# floored / capped so an early-game empire isn't wiped out and a
# late-game one feels it.
PIRATE_MIN_BC = 40
PIRATE_MAX_BC_FRACTION = 0.15      # at most this share of current BC

# Wandering trader / population boom / tech breakthrough tuning.
TRADER_MIN_BC = 80
TRADER_MAX_BC = 200
POP_BOOM_MIN = 1
POP_BOOM_MAX = 2
TECH_BREAKTHROUGH_MIN = 50
TECH_BREAKTHROUGH_MAX = 150


def _log(game, line: str):
    """Push an event to the game's rolling log AND the espionage report
    log (which the Espionage scene already surfaces)."""
    existing = getattr(game, "events_log", []) or []
    game.events_log = (existing + [line])[-40:]
    esp = getattr(game, "espionage", None)
    if esp is not None:
        esp._log(line)


def _player(component_mgr):
    for _eid, emp in component_mgr.get_all(Empire):
        if emp.is_player:
            return emp
    return None


def _player_unlocked(component_mgr, empire_id: int) -> set[str]:
    for _eid, ts in component_mgr.get_all(TechState):
        if ts.empire_id == empire_id:
            return set(ts.unlocked)
    return set()


def _player_locked(component_mgr, empire_id: int) -> set[str]:
    for _eid, ts in component_mgr.get_all(TechState):
        if ts.empire_id == empire_id:
            return set(ts.locked_out)
    return set()


# ---- Plague: ongoing resolution and new outbreaks ---------------------

def _resolve_active_plagues(game, turn: int, rng):
    """Every plagued colony loses 1M pop and its counter ticks down.
    When the counter hits 0 the outbreak ends. Microbiotics shortens
    things by 2 turns per resolution pass."""
    cm = game.component_mgr
    plague_writes: list[tuple[int, int]] = []   # (planet_id, plague_turns)
    pop_writes: list[tuple] = []
    worker_writes: list[tuple] = []
    cured: list[str] = []

    for entity_id, owner in cm.get_all(Owner):
        planet = cm.get_component(entity_id, Planet)
        if planet is None or planet.plague_turns <= 0:
            continue
        # 1M pop dies this turn.
        pop = cm.get_component(entity_id, Population)
        if pop is not None and pop.current > 0:
            pop.current -= 1
            for role in ("workers", "scientists", "farmers"):
                if getattr(pop, role) > 0:
                    setattr(pop, role, getattr(pop, role) - 1)
                    break
            pop.growth_progress = 0.0
            pop_writes.append((planet.id, pop.current, pop.max, pop.growth_progress))
            worker_writes.append((planet.id, pop.farmers, pop.workers, pop.scientists))
        # Wind down — faster if the owner has Microbiotics.
        unlocked = _player_unlocked(cm, owner.empire_id)
        wear = 1 + (PLAGUE_MICROBIOTICS_REDUCTION if "microbiotics" in unlocked else 0)
        planet.plague_turns = max(0, planet.plague_turns - wear)
        plague_writes.append((planet.id, planet.plague_turns))
        if planet.plague_turns == 0:
            owner_emp = next((e for _e, e in cm.get_all(Empire)
                              if e.id == owner.empire_id), None)
            if owner_emp is not None and owner_emp.is_player:
                cured.append(f"T{turn}: Plague on a {owner_emp.name} colony has burned out.")

    if not (plague_writes or pop_writes or worker_writes or cured):
        return
    with get_connection() as conn:
        for planet_id, plague_turns in plague_writes:
            update_planet_plague(conn, planet_id, plague_turns)
        for planet_id, current, mx, growth in pop_writes:
            update_planet_population(conn, planet_id, current, mx, growth)
        for planet_id, f, w, s in worker_writes:
            update_planet_workers(conn, planet_id, f, w, s)
        conn.commit()
    for msg in cured:
        _log(game, msg)


def _trigger_plague(game, turn: int, rng):
    """Pick a random player colony and start an outbreak there. If the
    player has no colonies, no-op."""
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    targets = []
    for entity_id, owner in cm.get_all(Owner):
        if owner.empire_id != player.id:
            continue
        planet = cm.get_component(entity_id, Planet)
        pop = cm.get_component(entity_id, Population)
        if planet is None or pop is None or pop.current < 2 or planet.plague_turns > 0:
            continue
        targets.append((entity_id, planet))
    if not targets:
        return
    entity_id, planet = rng.choice(targets)
    duration = rng.randint(PLAGUE_MIN_TURNS, PLAGUE_MAX_TURNS)
    planet.plague_turns = duration
    with get_connection() as conn:
        update_planet_plague(conn, planet.id, duration)
        conn.commit()
    _log(game, f"T{turn}: A virulent plague has broken out on planet #{planet.id} "
               f"— {duration} turns of population loss expected.")


# ---- Derelict Ship: free random unlearned tech -----------------------

def _trigger_derelict(game, turn: int, rng):
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    unlocked = _player_unlocked(cm, player.id)
    locked_out = _player_locked(cm, player.id)
    # Eligible techs: not unlocked, not locked-out, prereqs satisfied.
    candidates = [
        tech_id for tech_id, _spec in TECHS.items()
        if tech_id not in unlocked
        and tech_id not in locked_out
        and is_available(tech_id, unlocked, locked_out)
    ]
    if not candidates:
        return
    chosen = rng.choice(candidates)
    # Apply on the TechState + DB.
    ts = next((t for _e, t in cm.get_all(TechState) if t.empire_id == player.id), None)
    if ts is None:
        return
    ts.unlocked.append(chosen)
    # If the empire was already researching this, clear the target.
    if ts.current_target == chosen:
        ts.current_target = None
        ts.progress = 0
    with get_connection() as conn:
        insert_empire_tech(conn, player.id, chosen)
        conn.commit()
    name = TECHS.get(chosen, {}).get("name", chosen)
    _log(game, f"T{turn}: A derelict alien ship yielded blueprints — {name} acquired.")


# ---- Pirate Raid: BC drain -------------------------------------------

def _trigger_pirate_raid(game, turn: int, rng):
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    if player.bc <= 0:
        return
    drain = max(PIRATE_MIN_BC, int(player.bc * PIRATE_MAX_BC_FRACTION))
    drain = min(drain, player.bc)
    player.bc -= drain
    with get_connection() as conn:
        update_empire_economy(conn, player.id, player.bc, player.research_points)
        conn.commit()
    _log(game, f"T{turn}: Pirate raiders looted {drain} BC from your trade routes.")


# ---- Wandering Trader: free BC ---------------------------------------

def _trigger_trader(game, turn: int, rng):
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    bonus = rng.randint(TRADER_MIN_BC, TRADER_MAX_BC)
    player.bc += bonus
    with get_connection() as conn:
        update_empire_economy(conn, player.id, player.bc, player.research_points)
        conn.commit()
    _log(game, f"T{turn}: A wandering trader paid you {bonus} BC for safe passage "
               f"through your space.")


# ---- Population Boom: instant pop bump on a random colony ------------

def _trigger_pop_boom(game, turn: int, rng):
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    targets = []
    for entity_id, owner in cm.get_all(Owner):
        if owner.empire_id != player.id:
            continue
        planet = cm.get_component(entity_id, Planet)
        pop = cm.get_component(entity_id, Population)
        if planet is None or pop is None:
            continue
        # Only colonies with room to grow benefit from a boom.
        if pop.current >= pop.max:
            continue
        targets.append((entity_id, planet, pop))
    if not targets:
        return
    entity_id, planet, pop = rng.choice(targets)
    grew = min(rng.randint(POP_BOOM_MIN, POP_BOOM_MAX), pop.max - pop.current)
    if grew <= 0:
        return
    pop.current += grew
    pop.workers += grew  # default new pop into the workforce
    pop.growth_progress = 0.0
    with get_connection() as conn:
        update_planet_population(conn, planet.id, pop.current, pop.max,
                                  pop.growth_progress)
        update_planet_workers(conn, planet.id, pop.farmers, pop.workers,
                               pop.scientists)
        conn.commit()
    _log(game, f"T{turn}: A baby boom on planet #{planet.id} — +{grew}M new "
               f"colonists report for work.")


# ---- Tech Breakthrough: instant research progress --------------------

def _trigger_tech_breakthrough(game, turn: int, rng):
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    ts = next((t for _e, t in cm.get_all(TechState) if t.empire_id == player.id), None)
    if ts is None or ts.current_target is None:
        return
    proj = TECHS.get(ts.current_target)
    if proj is None:
        return
    bonus = rng.randint(TECH_BREAKTHROUGH_MIN, TECH_BREAKTHROUGH_MAX)
    # Don't overshoot the project cost; tech completion is handled
    # cleanly by ``production_tick`` next turn.
    bonus = min(bonus, proj["cost"] - ts.progress)
    if bonus <= 0:
        return
    ts.progress += bonus
    with get_connection() as conn:
        update_empire_tech(conn, player.id, ts.current_target, ts.progress)
        conn.commit()
    _log(game, f"T{turn}: Lab breakthrough — research on {proj['name']} surged "
               f"by {bonus} RP.")


# ---- Solar Flare: destroy one random non-defense building ------------

def _pick_destructible_building(bs: BuildState) -> str | None:
    """Random completed non-defence building, or None. Defences and
    farming/economy structures are eligible; planet-defence stays
    intact because the cause is environmental, not insurgent."""
    if bs is None or not bs.completed:
        return None
    options = []
    for pid in bs.completed:
        # Only skip ground-combat defences for solar/comet events?
        # No — those structures aren't shielded against natural events.
        # Include them so any building can be lost. Filter only ship
        # projects (shouldn't be in completed anyway).
        proj = PROJECTS.get(pid, {})
        if proj.get("type") == "ship":
            continue
        options.append(pid)
    if not options:
        return None
    return random.choice(options)


def _trigger_solar_flare(game, turn: int, rng):
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    targets = []
    for entity_id, owner in cm.get_all(Owner):
        if owner.empire_id != player.id:
            continue
        bs = cm.get_component(entity_id, BuildState)
        if bs is None or not bs.completed:
            continue
        targets.append((entity_id, bs))
    if not targets:
        return
    entity_id, bs = rng.choice(targets)
    target = _pick_destructible_building(bs)
    if target is None:
        return
    bs.completed.remove(target)
    planet = cm.get_component(entity_id, Planet)
    pname = PROJECTS.get(target, {}).get("name", target)
    with get_connection() as conn:
        delete_planet_building(conn, planet.id, target)
        conn.commit()
    _log(game, f"T{turn}: Solar flare seared planet #{planet.id} — {pname} "
               f"infrastructure destroyed.")


# ---- Comet Strike: 1M pop loss + 1 building destroyed ----------------

def _trigger_comet_strike(game, turn: int, rng):
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    targets = []
    for entity_id, owner in cm.get_all(Owner):
        if owner.empire_id != player.id:
            continue
        planet = cm.get_component(entity_id, Planet)
        pop = cm.get_component(entity_id, Population)
        if planet is None or pop is None or pop.current <= 0:
            continue
        targets.append((entity_id, planet, pop))
    if not targets:
        return
    entity_id, planet, pop = rng.choice(targets)
    bs = cm.get_component(entity_id, BuildState)
    building_target = _pick_destructible_building(bs)

    # 1M pop dies in the impact.
    pop.current -= 1
    for role in ("workers", "scientists", "farmers"):
        if getattr(pop, role) > 0:
            setattr(pop, role, getattr(pop, role) - 1)
            break
    pop.growth_progress = 0.0

    pname = None
    if building_target is not None:
        bs.completed.remove(building_target)
        pname = PROJECTS.get(building_target, {}).get("name", building_target)

    with get_connection() as conn:
        update_planet_population(conn, planet.id, pop.current, pop.max,
                                  pop.growth_progress)
        update_planet_workers(conn, planet.id, pop.farmers, pop.workers,
                               pop.scientists)
        if building_target is not None:
            delete_planet_building(conn, planet.id, building_target)
        conn.commit()
    extra = f", flattening {pname}" if pname else ""
    _log(game, f"T{turn}: Comet impact on planet #{planet.id} — 1M dead{extra}.")


# ---- Tick orchestration -----------------------------------------------

EVENT_HANDLERS = {
    "derelict":         _trigger_derelict,
    "trader":           _trigger_trader,
    "pop_boom":         _trigger_pop_boom,
    "tech_breakthrough": _trigger_tech_breakthrough,
    "plague":           _trigger_plague,
    "pirate_raid":      _trigger_pirate_raid,
    "solar_flare":      _trigger_solar_flare,
    "comet_strike":     _trigger_comet_strike,
}


def events_tick(game, new_turn: int):
    """Resolve active plagues, then roll for a new event."""
    rng = random
    _resolve_active_plagues(game, new_turn, rng)
    if rng.random() > EVENT_BASE_CHANCE:
        return
    # Weighted choice.
    total = sum(EVENT_WEIGHTS.values())
    pick = rng.random() * total
    accum = 0
    for name, weight in EVENT_WEIGHTS.items():
        accum += weight
        if pick <= accum:
            handler = EVENT_HANDLERS.get(name)
            if handler is not None:
                handler(game, new_turn, rng)
            break

"""Star-system combat.

When two or more empires have parked ships at the same star at the end
of a turn, combat resolves. The model is intentionally simple for now:

- Each side's "attack power" = sum of attack across its ships.
- Each side absorbs damage equal to the sum of every OTHER side's
  attack — so 3-way standoffs are brutal but rare.
- Damage destroys cheapest (lowest hull) ships first; ships are
  all-or-nothing (no partial damage carried).

A combat log entry is appended to ``game.last_combats`` so future UI
can surface what happened. For now players will see fleet badges
change.
"""
from __future__ import annotations

from ecs.components import (
    Ship, ShipOwner, ShipAt, ShipInTransit, TechState, Owner, Orbiting, Position,
    BuildState,
)
from ecs.ships import SHIPS
from ecs.races import trait_count, traits_for_empire
from ecs.techs import empire_attack_bonus, empire_hull_bonus
from ecs.invasion import _planet_defense_rating
from ecs.sensors import sensor_points, empire_sensor_range_px, is_detected
from ecs.db import get_connection, delete_ship
from ecs.ship_design import compute_loadout


def _empire_bonuses(component_mgr, empire_id: int) -> tuple[int, int]:
    """Sum tech-driven (Physics field) + trait-driven (ship_attack /
    ship_hull) bonuses for one empire. MAX semantics on the tech side
    so weapon tiers replace each other (Laser → Phasor → Plasma)."""
    traits = traits_for_empire(component_mgr, empire_id)
    trait_atk = trait_count(traits, "ship_attack")
    trait_hull = 2 * trait_count(traits, "ship_hull")  # trait wording: "+2 Ship Hull"

    tech_atk = tech_hull = 0
    for _eid, tech in component_mgr.get_all(TechState):
        if tech.empire_id == empire_id:
            tech_atk = empire_attack_bonus(tech.unlocked)
            tech_hull = empire_hull_bonus(tech.unlocked)
            break
    return trait_atk + tech_atk, trait_hull + tech_hull


def _attack_of(component_mgr, ship_entity: int, attack_bonus: int = 0,
               leader_map: dict | None = None,
               loadout_atk: int = 0) -> int:
    ship = component_mgr.get_component(ship_entity, Ship)
    if ship is None:
        return 0
    extra = leader_map.get(ship.id, (0, 0))[0] if leader_map else 0
    return SHIPS.get(ship.ship_class, {}).get("attack", 0) + attack_bonus + extra + loadout_atk


def _hull_of(component_mgr, ship_entity: int, hull_bonus: int = 0,
             leader_map: dict | None = None,
             loadout_hull: int = 0) -> int:
    """Effective hull = base + race/trait bonus + ship leader + loadout
    (armor + shield-defense + special hull/defense). Shields are folded
    into hull for the loss-computation pass since damage doesn't carry
    between turns."""
    ship = component_mgr.get_component(ship_entity, Ship)
    if ship is None:
        return 0
    extra = leader_map.get(ship.id, (0, 0))[1] if leader_map else 0
    return SHIPS.get(ship.ship_class, {}).get("hull", 0) + hull_bonus + extra + loadout_hull


def _compute_losses(component_mgr, ships: list[int], damage: int) -> list[int]:
    """Backwards-compatible: ignores tech/trait hull bonuses."""
    return _compute_losses_with_bonus(component_mgr, ships, damage, 0)


def _compute_losses_with_bonus(component_mgr, ships: list[int], damage: int,
                                hull_bonus: int, leader_map: dict | None = None,
                                loadout_hull_by_class: dict | None = None) -> list[int]:
    """Return ship entities destroyed. Cheapest hull dies first; no
    partial-damage carry between turns. ``hull_bonus`` is added to every
    ship's hull (race trait), ``leader_map`` adds per-ship Battle
    Tactician hull, and ``loadout_hull_by_class`` adds armor+shield
    bonus for the empire's auto-fitted equipment."""
    if damage <= 0 or not ships:
        return []

    def hull_of(ship_entity):
        ship = component_mgr.get_component(ship_entity, Ship)
        loadout_h = 0
        if ship is not None and loadout_hull_by_class is not None:
            loadout_h = loadout_hull_by_class.get(ship.ship_class, 0)
        return _hull_of(component_mgr, ship_entity, hull_bonus, leader_map, loadout_h)

    sorted_ships = sorted(ships, key=hull_of)
    losses: list[int] = []
    remaining = damage
    for ship_entity in sorted_ships:
        hull = hull_of(ship_entity)
        if hull <= 0:
            continue
        if remaining >= hull:
            losses.append(ship_entity)
            remaining -= hull
        else:
            break
    return losses


def _destroy_ship(game, ship_entity: int):
    cm = game.component_mgr
    for comp_type in (Ship, ShipOwner, ShipAt, ShipInTransit):
        cm.remove_component(ship_entity, comp_type)
    game.entity_mgr.destroy_entity(ship_entity)


def combat_tick(game, new_turn: int):
    """Resolve combat at every star where two or more *at-war* empires
    have ships. Empires at peace (or under a non-aggression pact) can
    share a star without fighting."""
    cm = game.component_mgr
    diplo = getattr(game, "diplomacy", None)

    # Ship-leader combat bonuses: ship.id -> (attack, hull). Battle
    # Tacticians / Weapons Masters assigned to a ship buff that hull.
    leaders = getattr(game, "leaders", None)
    leader_map: dict[int, tuple[int, int]] = {}
    if leaders is not None:
        from ecs.leaders import ship_effect
        for l in leaders.leaders.values():
            if l.category == "ship" and l.assigned_ship_id is not None:
                leader_map[l.assigned_ship_id] = ship_effect(l)

    def _hostile(a: int, b: int) -> bool:
        # No diplomacy object (e.g. old save) → fall back to the old
        # "everyone fights everyone" behaviour so nothing silently
        # becomes invincible.
        if diplo is None:
            return True
        return diplo.at_war(a, b)

    # star_entity -> {empire_id: [ship_entity]}
    by_star: dict[int, dict[int, list[int]]] = {}
    for ship_entity, at in cm.get_all(ShipAt):
        owner = cm.get_component(ship_entity, ShipOwner)
        if owner is None:
            continue
        by_star.setdefault(at.star_entity, {}).setdefault(owner.empire_id, []).append(ship_entity)

    # star_entity -> {empire_id: total planetary defense rating}. A
    # fortified colony (Missile Base → Star Fortress) fires on hostile
    # fleets in its system even with no defending ships present, and
    # those structures can't be destroyed by space combat — only taken
    # by ground invasion.
    by_star_defense: dict[int, dict[int, int]] = {}
    for planet_entity, owner in cm.get_all(Owner):
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is None:
            continue
        rating = _planet_defense_rating(cm.get_component(planet_entity, BuildState))
        if rating:
            d = by_star_defense.setdefault(orbit.star_entity, {})
            d[owner.empire_id] = d.get(owner.empire_id, 0) + rating

    log: list[dict] = []
    destroyed_ids: list[int] = []
    destroyed_entities: list[int] = []

    # Cache empire combat bonuses once per tick — tech state doesn't
    # change mid-resolution.
    bonus_by_empire: dict[int, tuple[int, int]] = {}

    def _bonuses(eid: int) -> tuple[int, int]:
        if eid not in bonus_by_empire:
            bonus_by_empire[eid] = _empire_bonuses(cm, eid)
        return bonus_by_empire[eid]

    # Per-empire auto-loadout stats by ship_class. Built lazily because
    # we don't want to walk SHIPS for empires not in this battle.
    loadout_atk_cache: dict[int, dict[str, int]] = {}
    loadout_hull_cache: dict[int, dict[str, int]] = {}

    def _empire_unlocked(eid):
        for _e, t in cm.get_all(TechState):
            if t.empire_id == eid:
                return set(t.unlocked)
        return set()

    def _loadout_for(eid: int, ship_class: str) -> tuple[int, int]:
        """(attack, hull+defense) the empire's auto-design grants a ship
        of this class. Cached per (empire, class)."""
        if eid not in loadout_atk_cache:
            loadout_atk_cache[eid] = {}
            loadout_hull_cache[eid] = {}
        if ship_class not in loadout_atk_cache[eid]:
            lo = compute_loadout(ship_class, _empire_unlocked(eid))
            s = lo["stats"]
            loadout_atk_cache[eid][ship_class] = s["attack"]
            # Fold shield defense into effective hull (no partial damage
            # carry, so shields just soak damage like extra hull here).
            loadout_hull_cache[eid][ship_class] = s["hull"] + s["defense"]
        return (loadout_atk_cache[eid][ship_class],
                loadout_hull_cache[eid][ship_class])

    def _ship_loadout_atk(eid: int, ship_entity: int) -> int:
        ship = cm.get_component(ship_entity, Ship)
        return _loadout_for(eid, ship.ship_class)[0] if ship else 0

    # Every star with ships and/or planetary defenses is a possible
    # battlefield.
    for star_entity in set(by_star) | set(by_star_defense):
        ships_here = by_star.get(star_entity, {})
        def_here = by_star_defense.get(star_entity, {})
        participants = set(ships_here) | set(def_here)
        if len(participants) < 2:
            continue
        # Skip stars where no two present empires are actually at war.
        plist = list(participants)
        if not any(_hostile(plist[i], plist[j])
                   for i in range(len(plist)) for j in range(i + 1, len(plist))):
            continue

        # Attack = fleet firepower + stationary planetary defenses.
        side_attack = {
            eid: sum(_attack_of(cm, e, _bonuses(eid)[0], leader_map,
                                _ship_loadout_atk(eid, e))
                     for e in ships_here.get(eid, []))
                 + def_here.get(eid, 0)
            for eid in participants
        }
        side_losses: dict[int, list[int]] = {}
        for eid in participants:
            # Only take damage from empires we're at war with. Planetary
            # defenses absorb nothing — only ships can be destroyed.
            damage = sum(
                side_attack[other] for other in participants
                if other != eid and _hostile(eid, other)
            )
            # Make sure the empire's loadout map is populated for every
            # class present so _compute_losses_with_bonus can look it up.
            for e in ships_here.get(eid, []):
                _loadout_for(eid, cm.get_component(e, Ship).ship_class)
            side_losses[eid] = _compute_losses_with_bonus(
                cm, ships_here.get(eid, []), damage, _bonuses(eid)[1], leader_map,
                loadout_hull_cache.get(eid, {}),
            )

        # Record the engagement before mutating — rich enough for the
        # combat-report screen: per side, ships by class, attack power,
        # defenses, losses, survivors.
        sides = []
        for eid in participants:
            ships = ships_here.get(eid, [])
            by_class: dict[str, int] = {}
            for e in ships:
                sc = cm.get_component(e, Ship)
                if sc is not None:
                    by_class[sc.ship_class] = by_class.get(sc.ship_class, 0) + 1
            lost = len(side_losses[eid])
            sides.append({
                "empire_id": eid,
                "attack": side_attack[eid],
                "defense": def_here.get(eid, 0),
                "ships_before": by_class,
                "total_before": len(ships),
                "lost": lost,
                "remaining": len(ships) - lost,
            })
        log_entry = {
            "turn": new_turn,
            "star_entity": star_entity,
            "sides": sides,
            # Kept for backwards compatibility with any existing readers.
            "losses_by_empire": {
                eid: len(losses) for eid, losses in side_losses.items() if losses
            },
            "attack_by_empire": dict(side_attack),
        }
        log.append(log_entry)

        for eid, losses in side_losses.items():
            for ship_entity in losses:
                ship = cm.get_component(ship_entity, Ship)
                if ship is None:
                    continue
                destroyed_ids.append(ship.id)
                destroyed_entities.append(ship_entity)

    if destroyed_entities:
        with get_connection() as conn:
            for ship_id in destroyed_ids:
                delete_ship(conn, ship_id)
            conn.commit()
        for ship_entity in destroyed_entities:
            _destroy_ship(game, ship_entity)

    # Append to a rolling log on Game for review.
    if log:
        existing = getattr(game, "last_combats", [])
        # Keep at most the 20 most recent engagements.
        game.last_combats = (existing + log)[-20:]
        # Surface battles the player fought in *and* nearby clashes the
        # player's sensors picked up (AI-vs-AI within detection range).
        # The GalaxyScene pops up a report for these after the turn.
        player = game.player_empire()
        if player is not None:
            points = sensor_points(game, player.id)
            sensor_r = empire_sensor_range_px(cm, player.id)
            reports = []
            for r in log:
                involved = any(s["empire_id"] == player.id for s in r["sides"])
                if involved:
                    r["observed"] = False
                    reports.append(r)
                    continue
                # Not involved — only report if a sensor source sees the star.
                spos = cm.get_component(r["star_entity"], Position)
                if spos is not None and is_detected(spos.x, spos.y, points, sensor_r):
                    r["observed"] = True
                    reports.append(r)
            if reports:
                game.pending_combat_reports = reports

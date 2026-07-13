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

import random

from ecs.components import (
    Ship, ShipOwner, ShipAt, ShipInTransit, TechState, Owner, Orbiting, Position,
    BuildState, Name, Empire,
)
from ecs.turn_log import log as turn_log, CAT_COMBAT
from ecs.tactical import TacticalBattle, TacticalShip, GRID_COLS, GRID_ROWS
from ecs.ships import SHIPS
from ecs.races import trait_count, traits_for_empire
from ecs.techs import (
    empire_attack_bonus, empire_hull_bonus,
    empire_ship_shield_bonus, empire_planetary_shield_bonus,
)
from ecs.invasion import _planet_defense_rating
from ecs.sensors import sensor_points, empire_sensor_range_px, is_detected
from ecs.db import get_connection, delete_ship
from ecs.ship_design import stats_from_ship
from ecs import battle
from ecs.battle import Combatant


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


def _empire_unlocked_techs(component_mgr, empire_id: int) -> set:
    for _eid, tech in component_mgr.get_all(TechState):
        if tech.empire_id == empire_id:
            return set(tech.unlocked)
    return set()


def _empire_ship_shield_bonus(component_mgr, empire_id: int) -> int:
    """Flat shield-capacity bonus every combat ship of this empire gets
    from power techs (Energy Absorber). 0 if none unlocked."""
    return empire_ship_shield_bonus(_empire_unlocked_techs(component_mgr, empire_id))


def _destroy_ship(game, ship_entity: int):
    cm = game.component_mgr
    for comp_type in (Ship, ShipOwner, ShipAt, ShipInTransit):
        cm.remove_component(ship_entity, comp_type)
    game.entity_mgr.destroy_entity(ship_entity)


# Multi-round combat: ships exchange fire over up to this many rounds.
# A battle ends sooner if only one side has surviving combatants.
MAX_COMBAT_ROUNDS = 5


def _build_combatants(component_mgr, ships_here, bonuses_fn, leader_map,
                      ship_atk_fn, ship_stats_full_fn):
    """Snapshot every ship into a canonical ``battle.Combatant`` for the
    engagement. ``key`` is the ECS ship entity id so losses map back.

    Also returns the per-empire intact attack pool (the first-round
    attack figure shown in the combat report). Note: armor-tech hull is
    already inside ``stats.hull``; the special evasion stat becomes the
    combatant's flat ``defense`` (per-hit reduction), matching the
    tactical path and the canonical model in ``ecs/battle.py``."""
    combatants_by_eid: dict[int, list[Combatant]] = {}
    intact_attack: dict[int, int] = {}
    for eid, ships in ships_here.items():
        atk_bonus, hull_bonus = bonuses_fn(eid)
        # Energy Absorber (power tech): flat shield-capacity bonus on
        # every one of this empire's ships in the battle.
        shield_bonus = _empire_ship_shield_bonus(component_mgr, eid)
        side_attack = 0
        roster: list[Combatant] = []
        for e in ships:
            ship_atk = _attack_of(component_mgr, e, atk_bonus, leader_map,
                                  ship_atk_fn(eid, e))
            full = ship_stats_full_fn(e)
            leader_hull = leader_map.get(
                component_mgr.get_component(e, Ship).id, (0, 0)
            )[1] if leader_map else 0
            base_hull = SHIPS.get(
                component_mgr.get_component(e, Ship).ship_class, {}
            ).get("hull", 0)
            hull_max = base_hull + hull_bonus + leader_hull + full.get("hull", 0)
            shield_cap = full.get("shield_capacity", 0) + shield_bonus
            roster.append(Combatant(
                key=e,
                empire_id=eid,
                attack=ship_atk,
                hull=hull_max,
                hull_max=hull_max,
                shield=shield_cap,
                shield_max=shield_cap,
                shield_regen=full.get("shield_regen", 0),
                defense=full.get("defense", 0),
            ))
            side_attack += ship_atk
        combatants_by_eid[eid] = roster
        intact_attack[eid] = side_attack
    return combatants_by_eid, intact_attack


def _build_tactical_battle(cm, star_entity: int, new_turn: int,
                           player_id: int, ships_here: dict[int, list[int]],
                           ship_stats_full,
                           def_here: dict[int, int] | None = None) -> TacticalBattle:
    """Snapshot the ECS state at ``star_entity`` into a TacticalBattle.

    Placement: player ships on the left columns (0-2), enemies on the
    right columns (GRID_COLS-3..GRID_COLS-1). Each empire fills its
    columns top-down. If an empire has more ships than column-rows,
    extras stack into the next inward column.

    Stations: any empire in ``def_here`` with a positive defense
    rating gets a stationary Star Base / Battlestation / Star Fortress
    placed against its back wall — derived from the highest-tier
    orbital-defense building completed on the planet (so the chain
    upgrade is faithful).
    """
    from ecs.tactical import SHIP_AP, DEFAULT_AP
    from ecs.ships import SHIPS as _SHIPS

    star_name_comp = cm.get_component(star_entity, Name)
    star_name = star_name_comp.value if star_name_comp else "deep space"

    battle = TacticalBattle(
        star_entity=star_entity, star_name=star_name, turn=new_turn,
        player_id=player_id,
    )

    # Stable ordering: player first, then everyone else.
    empire_order = ([player_id] +
                    [eid for eid in ships_here if eid != player_id])
    for slot_idx, eid in enumerate(empire_order):
        ships = ships_here.get(eid, [])
        # Energy Absorber shield bonus, same as the strategic path.
        shield_bonus = _empire_ship_shield_bonus(cm, eid)
        if slot_idx == 0:
            cols = [0, 1, 2]
            back_col = 0  # station rides the back wall for the player
        else:
            base = GRID_COLS - 1 - (slot_idx - 1) * 3
            cols = [max(0, base), max(0, base - 1), max(0, base - 2)]
            back_col = base
        for i, ship_entity in enumerate(ships):
            ship = cm.get_component(ship_entity, Ship)
            if ship is None:
                continue
            stats = ship_stats_full(ship_entity)
            # Total hull = ship_class base + equipment hull bonus.
            base_hull = _SHIPS.get(ship.ship_class, {}).get("hull", 0)
            hull = max(1, int(base_hull + stats.get("hull", 0)))
            attack = max(0, int(stats.get("attack", 0)))
            shield_max = max(0, int(stats.get("shield_capacity", 0))) + shield_bonus
            shield_regen = max(0, int(stats.get("shield_regen", 0)))
            # 'defense' in stats_from_ship is an evasion-style flat —
            # we surface it as the armor damage reduction here.
            armor = max(0, int(stats.get("defense", 0)))
            speed = SHIP_AP.get(ship.ship_class, DEFAULT_AP)
            col = cols[i % len(cols)]
            row = i % GRID_ROWS
            battle.ships.append(TacticalShip(
                entity_id=ship_entity,
                empire_id=eid,
                ship_class=ship.ship_class,
                name=f"{ship.ship_class.title()} #{ship.id}",
                col=col, row=row,
                hull=hull, max_hull=hull,
                attack=attack,
                speed=speed, moves_left=speed,
                shield_max=shield_max, shield_current=shield_max,
                shield_regen=shield_regen,
                armor=armor,
            ))

        # Station from planetary defense rating, if any. Derived stats
        # are tuned so a Star Fortress is significantly more painful
        # than a battleship without being unkillable for a fleet.
        if def_here and def_here.get(eid, 0) > 0:
            station = _make_station_for(cm, star_entity, eid, def_here[eid], back_col)
            if station is not None:
                # Place at the back row so it doesn't sit on top of a
                # fleet ship — search the back column for a free row.
                for row in range(GRID_ROWS):
                    if battle.ship_at(station.col, row) is None:
                        station.row = row
                        break
                battle.ships.append(station)
    return battle


def _make_station_for(cm, star_entity: int, empire_id: int,
                      defense_rating: int, back_col: int):
    """Build a station TacticalShip whose strength tracks the highest
    orbital-defense building present on any planet at this star owned
    by ``empire_id``. Returns None if no qualifying planet found.
    """
    from ecs.tactical import TacticalShip as _TS
    # Find the strongest defense building present.
    highest_tier = None
    for planet_entity, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is None or orbit.star_entity != star_entity:
            continue
        bs = cm.get_component(planet_entity, BuildState)
        if bs is None:
            continue
        for tier in ("star_fortress", "battlestation", "star_base"):
            if tier in bs.completed:
                if (highest_tier is None
                        or _STATION_RANK[tier] > _STATION_RANK[highest_tier]):
                    highest_tier = tier
                break
    if highest_tier is None:
        return None
    stats = _STATION_STATS[highest_tier]
    return _TS(
        entity_id=-1,  # stations aren't backed by ECS ship entities
        empire_id=empire_id,
        ship_class=highest_tier,
        name=stats["name"],
        col=back_col, row=0,  # row filled in by caller
        hull=stats["hull"], max_hull=stats["hull"],
        attack=stats["attack"],
        speed=0, moves_left=0,
        shield_max=stats["shield"], shield_current=stats["shield"],
        shield_regen=stats["regen"],
        armor=stats["armor"],
        is_station=True,
    )


_STATION_RANK = {"star_base": 1, "battlestation": 2, "star_fortress": 3}
_STATION_STATS = {
    "star_base":     {"name": "Star Base",     "hull": 60,  "attack": 8,
                       "shield": 30, "regen": 5,  "armor": 4},
    "battlestation": {"name": "Battlestation", "hull": 90,  "attack": 14,
                       "shield": 50, "regen": 8,  "armor": 6},
    "star_fortress": {"name": "Star Fortress", "hull": 130, "attack": 24,
                       "shield": 80, "regen": 12, "armor": 8},
}


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
    # Planetary Barrier Shield (force-field tech): a flat defensive
    # contribution at every star where the empire holds a colony, even
    # with no defence buildings. Cached per empire.
    _barrier_cache: dict[int, int] = {}

    def _barrier(eid: int) -> int:
        if eid not in _barrier_cache:
            _barrier_cache[eid] = empire_planetary_shield_bonus(
                _empire_unlocked_techs(cm, eid))
        return _barrier_cache[eid]

    _colony_stars: set[tuple[int, int]] = set()  # (star_entity, empire_id)
    for planet_entity, owner in cm.get_all(Owner):
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is None:
            continue
        _colony_stars.add((orbit.star_entity, owner.empire_id))
        rating = _planet_defense_rating(cm.get_component(planet_entity, BuildState))
        if rating:
            d = by_star_defense.setdefault(orbit.star_entity, {})
            d[owner.empire_id] = d.get(owner.empire_id, 0) + rating
    # Barrier shield adds once per (star, empire) that holds a colony.
    for star_entity, empire_id in _colony_stars:
        bonus = _barrier(empire_id)
        if bonus:
            d = by_star_defense.setdefault(star_entity, {})
            d[empire_id] = d.get(empire_id, 0) + bonus

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

    # Per-ship loadout stats — read from each ship's frozen equipment
    # (armor + shield + weapon × count + specials, all snapshotted at
    # build time). An old hull keeps its old gear when a newer tech
    # later lands; only newly-built ships pack the upgrade.
    ship_stats_cache: dict[int, dict] = {}

    def _ship_stats_full(ship_entity: int) -> dict:
        if ship_entity in ship_stats_cache:
            return ship_stats_cache[ship_entity]
        ship = cm.get_component(ship_entity, Ship)
        if ship is None:
            stats = {"attack": 0, "hull": 0, "defense": 0,
                     "shield_capacity": 0, "shield_regen": 0}
        else:
            stats = stats_from_ship(ship)
        ship_stats_cache[ship_entity] = stats
        return stats

    def _ship_loadout_atk(eid: int, ship_entity: int) -> int:
        return _ship_stats_full(ship_entity).get("attack", 0)

    # Player empire id (cached). When the player is in an engagement,
    # the strategic auto-resolver hands off to the tactical hex scene
    # instead — we queue a TacticalBattle here, skip auto-resolve for
    # that star, and let the player play the battle out after the
    # tick.
    player = None
    for _e, emp in cm.get_all(Empire):
        if emp.is_player:
            player = emp
            break
    player_id = player.id if player else None
    tactical_queue: list[TacticalBattle] = []

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

        # Tactical handoff: if the player has ships at this star and at
        # least one opposing empire is hostile, build a TacticalBattle
        # and skip auto-resolve. AI-vs-AI battles keep the fast path.
        if (player_id is not None
                and player_id in ships_here
                and any(_hostile(player_id, other)
                        for other in participants if other != player_id)):
            tactical_queue.append(_build_tactical_battle(
                cm, star_entity, new_turn, player_id,
                ships_here, _ship_stats_full,
                def_here=def_here,
            ))
            continue

        # Round-based combat with shields:
        #   - each ship has hull HP + a regenerating shield HP pool;
        #   - up to MAX_ROUNDS rounds, each round both sides fire
        #     simultaneously;
        #   - incoming damage drains the targeted ship's shield first,
        #     then its hull. Surviving ships' shields regenerate at the
        #     end of every round;
        #   - planetary defenses fire each round but can't be destroyed
        #     in space.
        combatants_by_eid, attack_by_eid_round1 = _build_combatants(
            cm, ships_here, _bonuses, leader_map,
            _ship_loadout_atk, _ship_stats_full,
        )
        first_round_attack = {
            eid: attack_by_eid_round1.get(eid, 0) + def_here.get(eid, 0)
            for eid in participants
        }
        battle.resolve_auto(combatants_by_eid, def_here, _hostile,
                            random.Random(new_turn * 1009 + star_entity),
                            max_rounds=MAX_COMBAT_ROUNDS)
        side_losses: dict[int, list[int]] = {
            eid: [c.key for c in combatants_by_eid.get(eid, []) if c.destroyed]
            for eid in participants
        }
        side_attack = first_round_attack

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
                # Short one-liners for the player's turn log.
                for r in reports:
                    sn = cm.get_component(r["star_entity"], Name)
                    star_name = sn.value if sn else "?"
                    if r.get("observed"):
                        turn_log(game, CAT_COMBAT,
                                 f"Observed clash at {star_name}")
                    else:
                        my_side = next(
                            (s for s in r["sides"]
                             if s["empire_id"] == player.id),
                            None,
                        )
                        if my_side:
                            turn_log(
                                game, CAT_COMBAT,
                                f"Battle at {star_name}: lost "
                                f"{my_side['lost']}, {my_side['remaining']} left",
                            )

    # Hand off any player-involved engagements to the combat-options
    # decision scene. The player picks Attack / Auto / Retreat per
    # engagement; only the ones they Attack reach the tactical scene.
    if tactical_queue:
        existing = getattr(game, "pending_engagements", None) or []
        game.pending_engagements = list(existing) + tactical_queue

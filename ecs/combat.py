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

from ecs.components import Ship, ShipOwner, ShipAt, ShipInTransit, TechState
from ecs.ships import SHIPS
from ecs.races import trait_count, traits_for_empire
from ecs.techs import empire_attack_bonus, empire_hull_bonus
from ecs.db import get_connection, delete_ship


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


def _attack_of(component_mgr, ship_entity: int, attack_bonus: int = 0) -> int:
    ship = component_mgr.get_component(ship_entity, Ship)
    if ship is None:
        return 0
    return SHIPS.get(ship.ship_class, {}).get("attack", 0) + attack_bonus


def _hull_of(component_mgr, ship_entity: int, hull_bonus: int = 0) -> int:
    ship = component_mgr.get_component(ship_entity, Ship)
    if ship is None:
        return 0
    return SHIPS.get(ship.ship_class, {}).get("hull", 0) + hull_bonus


def _compute_losses(component_mgr, ships: list[int], damage: int) -> list[int]:
    """Backwards-compatible: ignores tech/trait hull bonuses."""
    return _compute_losses_with_bonus(component_mgr, ships, damage, 0)


def _compute_losses_with_bonus(component_mgr, ships: list[int], damage: int,
                                hull_bonus: int) -> list[int]:
    """Return ship entities destroyed. Cheapest hull dies first; no
    partial-damage carry between turns. ``hull_bonus`` is added to every
    ship's hull (from Tachyon Scanner / Plasma Cannon / ship_hull race
    trait) so tougher empires soak more damage before losing ships."""
    if damage <= 0 or not ships:
        return []
    sorted_ships = sorted(
        ships, key=lambda e: _hull_of(component_mgr, e, hull_bonus),
    )
    losses: list[int] = []
    remaining = damage
    for ship_entity in sorted_ships:
        hull = _hull_of(component_mgr, ship_entity, hull_bonus)
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

    for star_entity, by_owner in by_star.items():
        if len(by_owner) < 2:
            continue
        # Skip stars where no two present empires are actually at war.
        present = list(by_owner)
        if not any(_hostile(present[i], present[j])
                   for i in range(len(present)) for j in range(i + 1, len(present))):
            continue

        side_attack = {
            empire_id: sum(_attack_of(cm, e, _bonuses(empire_id)[0]) for e in ships)
            for empire_id, ships in by_owner.items()
        }
        side_losses: dict[int, list[int]] = {}
        for empire_id, ships in by_owner.items():
            # Only take damage from empires we're at war with.
            damage = sum(
                side_attack[other] for other in by_owner
                if other != empire_id and _hostile(empire_id, other)
            )
            side_losses[empire_id] = _compute_losses_with_bonus(
                cm, ships, damage, _bonuses(empire_id)[1],
            )

        # Record the engagement before mutating — rich enough for the
        # combat-report screen: per side, ships by class, attack power,
        # losses, survivors.
        sides = []
        for empire_id, ships in by_owner.items():
            by_class: dict[str, int] = {}
            for e in ships:
                sc = cm.get_component(e, Ship)
                if sc is not None:
                    by_class[sc.ship_class] = by_class.get(sc.ship_class, 0) + 1
            lost = len(side_losses[empire_id])
            sides.append({
                "empire_id": empire_id,
                "attack": side_attack[empire_id],
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

        for empire_id, losses in side_losses.items():
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
        # Surface battles the player fought in — the GalaxyScene pops up
        # a report screen for these after the turn resolves.
        player = game.player_empire()
        if player is not None:
            player_battles = [
                r for r in log
                if any(s["empire_id"] == player.id for s in r["sides"])
            ]
            if player_battles:
                game.pending_combat_reports = player_battles

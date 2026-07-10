"""Canonical combat damage model — the single source of truth.

Before this module the game had THREE divergent resolvers:
  * ``combat._resolve_battle`` (strategic auto) folded armor into hull,
    ignored per-hit reduction, no random multiplier;
  * ``scenes.tactical._auto_resolve`` used a bare hull pool, ignored
    shields AND armor;
  * ``scenes.combat_decision._auto_resolve`` was a copy of the above.
The interactive tactical per-shot path (``TacticalBattle.attack``) used
yet a fourth shield→armor→hull ordering.

Everything now routes through the primitives here so a given fleet
produces the same outcome distribution regardless of whether the player
watches it (tactical), auto-resolves it from the Combat Options screen,
or it's an AI-vs-AI clash resolved strategically.

THE CANONICAL MODEL
-------------------
Each combatant has three defensive quantities:

  * ``hull``   — structure HP. Base hull + armor-tech hull + hull
    specials. Death at 0.
  * ``shield`` — a regenerating absorptive pool in front of the hull.
    Refills by ``shield_regen`` at the end of each round, up to
    ``shield_max``.
  * ``defense``— flat per-hit damage reduction (evasion, approximated).
    Applied once per hit; a hit ALWAYS lands at least 1 damage.

One hit resolves as::

    after_def = max(1, raw_damage - target.defense)
    to_shield = min(target.shield, after_def)
    to_hull   = after_def - to_shield

``raw_damage`` for a beam = ``attacker.attack × rng(0.7..1.3) × range_mult``.
Range multiplier is 1.0 for the strategic/auto path (no positioning) and
comes from the hex distance in the tactical path.

Determinism: every function that rolls takes an explicit
``random.Random`` so tests pin exact numbers with a seeded RNG.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


# Damage roll spread. A shot lands between 70% and 130% of nominal.
DAMAGE_MIN_MULT = 0.7
DAMAGE_MAX_MULT = 1.3

# Rounds an auto-resolved battle runs before it's called (stalemate cap).
MAX_AUTO_ROUNDS = 5


@dataclass
class Combatant:
    """The canonical mutable combat unit. Both the strategic snapshot
    (``combat._build_combatants``) and the tactical snapshot build these
    so the resolver math is identical.

    ``key`` is an opaque handle the caller uses to map results back to
    its own objects (an ECS entity id strategically, a TacticalShip
    reference tactically).
    """
    key: object
    empire_id: int
    attack: int
    hull: int
    hull_max: int
    shield: int = 0
    shield_max: int = 0
    shield_regen: int = 0
    defense: int = 0
    destroyed: bool = False


def roll_damage(attack: int, rng: random.Random, range_mult: float = 1.0) -> int:
    """Nominal beam damage for one shot, with the standard random spread
    and an optional range multiplier. Always ≥ 1 when ``attack`` and
    ``range_mult`` are positive."""
    if attack <= 0 or range_mult <= 0:
        return 0
    dmg = attack * rng.uniform(DAMAGE_MIN_MULT, DAMAGE_MAX_MULT) * range_mult
    return max(1, int(round(dmg)))


def apply_hit(target: Combatant, raw_damage: int) -> dict:
    """Resolve ``raw_damage`` against one combatant's defense → shield →
    hull. Mutates the target. Returns a breakdown dict::

        {"damage": int, "to_shield": int, "to_hull": int, "destroyed": bool}

    ``damage`` is post-defense (what actually got through the evasion
    layer). A hit always lands ≥ 1 if ``raw_damage`` > 0.
    """
    if raw_damage <= 0 or target.destroyed:
        return {"damage": 0, "to_shield": 0, "to_hull": 0,
                "destroyed": target.destroyed}
    after_def = max(1, raw_damage - target.defense)
    to_shield = min(target.shield, after_def)
    target.shield -= to_shield
    # Hull absorbs the remainder, but only up to what it has — overkill
    # is NOT recorded here. This keeps ``damage`` equal to what actually
    # landed, so the pool resolver spills the excess onto the next ship
    # instead of wasting it (and so combat-log lines read honestly).
    remainder = after_def - to_shield
    to_hull = min(remainder, target.hull)
    target.hull -= to_hull
    destroyed = False
    if target.hull <= 0:
        target.hull = 0
        target.destroyed = True
        destroyed = True
    return {"damage": to_shield + to_hull, "to_shield": to_shield,
            "to_hull": to_hull, "destroyed": destroyed}


def _weakest_target(roster: list[Combatant]) -> Combatant | None:
    """Focus-fire helper: the living combatant with the least total
    remaining HP (shield + hull). Deterministic — ties broken by list
    order."""
    best = None
    best_total = None
    for c in roster:
        if c.destroyed:
            continue
        total = c.shield + c.hull
        if total <= 0:
            continue
        if best is None or total < best_total:
            best, best_total = c, total
    return best


def apply_damage_pool(roster: list[Combatant], pool: int,
                      rng: random.Random) -> None:
    """Spend a whole side's summed attack ``pool`` on the opposing
    ``roster``, focus-firing the weakest ship first and spilling the
    remainder onto the next. Each ship applies its own defense as the
    pool bites into it, so a high-evasion escort genuinely soaks more of
    the barrage than a soft target would.

    This is the auto-resolve / strategic path; ``rng`` is threaded for
    signature parity with the per-shot path (the spread is already baked
    into ``pool`` by the caller) and to leave room for future
    crit / miss rolls without another signature change.
    """
    remaining = pool
    while remaining > 0:
        target = _weakest_target(roster)
        if target is None:
            return
        result = apply_hit(target, remaining)
        # Drain the pool by what this ship actually absorbed (shield +
        # hull), so overkill spills onto the next target. ``max(1, …)``
        # guards against a zero-absorb infinite loop (can't happen while
        # a live target exists, but cheap insurance).
        remaining -= max(1, result["damage"])


def regen_shields(roster: list[Combatant]) -> None:
    """End-of-round shield regeneration on all survivors."""
    for c in roster:
        if c.destroyed:
            continue
        if c.shield_max > 0:
            c.shield = min(c.shield_max, c.shield + c.shield_regen)


def resolve_auto(combatants_by_eid: dict[int, list[Combatant]],
                 defenses: dict[int, int],
                 hostile_fn,
                 rng: random.Random,
                 max_rounds: int = MAX_AUTO_ROUNDS) -> None:
    """Run a multi-round auto battle in place.

    - ``combatants_by_eid``: empire id → its live Combatant roster.
    - ``defenses``: empire id → flat planetary-defense attack that fires
      each round but can't be destroyed (stations in space combat).
    - ``hostile_fn(a, b)``: True if empires a and b are at war.
    - ``rng``: seeded for determinism.

    Each round every living side pools its ships' attack (plus its
    planetary defense), rolls the spread once per side, and spends the
    pool on each hostile opponent. Shields regen at round end. Stops
    when fewer than two hostile sides remain or ``max_rounds`` elapses.
    """
    for _round in range(max_rounds):
        living = [eid for eid in combatants_by_eid
                  if any(not c.destroyed for c in combatants_by_eid[eid])
                  or defenses.get(eid, 0) > 0]
        # Include defense-only sides.
        for eid in defenses:
            if defenses[eid] > 0 and eid not in living:
                living.append(eid)
        if len(living) < 2:
            return
        if not any(hostile_fn(a, b)
                   for i, a in enumerate(living)
                   for b in living[i + 1:]):
            return

        # Roll each side's pool once this round (spread applied to the
        # summed attack, then planetary defense added flat).
        side_pool: dict[int, int] = {}
        for eid in living:
            base = sum(c.attack for c in combatants_by_eid.get(eid, [])
                       if not c.destroyed)
            rolled = roll_damage(base, rng) if base > 0 else 0
            side_pool[eid] = rolled + defenses.get(eid, 0)

        for eid in living:
            incoming = sum(side_pool[other] for other in living
                           if other != eid and hostile_fn(eid, other))
            apply_damage_pool(combatants_by_eid.get(eid, []), incoming, rng)

        for roster in combatants_by_eid.values():
            regen_shields(roster)


def winner_of(combatants_by_eid: dict[int, list[Combatant]],
              defenses: dict[int, int] | None = None) -> int | None:
    """Empire id of the sole side with surviving ships (or a live
    planetary defense), or None if 0 / 2+ sides remain."""
    defenses = defenses or {}
    alive = [eid for eid in set(combatants_by_eid) | set(defenses)
             if any(not c.destroyed for c in combatants_by_eid.get(eid, []))
             or defenses.get(eid, 0) > 0]
    return alive[0] if len(alive) == 1 else None

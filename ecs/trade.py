"""Trade route computation for visualisation.

The economy treats freighter capacity as an empire-wide pool (see
``pop_growth_tick`` in ``economy.py``) — food balances net out across
all of an empire's colonies without bookkeeping which specific surplus
fed which specific deficit. That's fine for resolution but unhelpful
for the player, who wants to *see* where their food is moving.

This module reconstructs plausible point-to-point routes for display
only. Greedy match: the biggest surpluses are paired with the biggest
deficits in descending order, capped by the empire's freighter
capacity. The amounts are visualisation hints, not gameplay state —
no economy mutation happens here.
"""
from __future__ import annotations

from ecs.components import Empire, Owner, Orbiting, Planet, Population, BuildState
from ecs.economy import planet_output, empire_tech_bonus, FARMER_FOOD
from ecs.races import trait_count, traits_for_empire
from ecs.ships import empire_freighter_capacity


def trade_routes(game, empire_id: int) -> list[tuple[int, int, int]]:
    """Return ``(source_planet_entity, dest_planet_entity, amount)`` for
    each implied food transport this turn. Same-star pairs are omitted
    (a freighter has nowhere to fly to). Returns ``[]`` if the empire
    has no deficit colonies or no spare capacity."""
    cm = game.component_mgr
    traits = traits_for_empire(cm, empire_id)
    tech_bonus = empire_tech_bonus(cm, empire_id)
    per_pop_need = 0.5 if "tolerant" in traits else 1.0

    # Snapshot every owned planet's (production, need, star_entity).
    surplus: list[tuple[int, int, int]] = []  # (planet_eid, amount, star_eid)
    deficit: list[tuple[int, int, int]] = []  # (planet_eid, amount, star_eid)
    for planet_entity, owner in cm.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        planet = cm.get_component(planet_entity, Planet)
        pop = cm.get_component(planet_entity, Population)
        if planet is None or pop is None:
            continue
        build_state = cm.get_component(planet_entity, BuildState)
        orbit = cm.get_component(planet_entity, Orbiting)
        if orbit is None:
            continue
        f, _i, _r, _b = planet_output(planet, pop, build_state, traits, tech_bonus)
        need = int(pop.current * per_pop_need + 0.999)  # ceil
        diff = f - need
        if diff > 0:
            surplus.append((planet_entity, diff, orbit.star_entity))
        elif diff < 0:
            deficit.append((planet_entity, -diff, orbit.star_entity))

    if not surplus or not deficit:
        return []

    capacity = empire_freighter_capacity(cm, empire_id)
    if capacity <= 0:
        return []

    surplus.sort(key=lambda r: -r[1])
    deficit.sort(key=lambda r: -r[1])

    routes: list[tuple[int, int, int]] = []
    remaining = capacity
    si = di = 0
    s_eid, s_amt, s_star = surplus[si]
    d_eid, d_amt, d_star = deficit[di]
    while remaining > 0 and si < len(surplus) and di < len(deficit):
        flow = min(s_amt, d_amt, remaining)
        if flow <= 0:
            # Advance whichever side is exhausted to avoid an infinite loop
            # if a zero ever slips through.
            if s_amt <= 0:
                si += 1
                if si < len(surplus):
                    s_eid, s_amt, s_star = surplus[si]
            else:
                di += 1
                if di < len(deficit):
                    d_eid, d_amt, d_star = deficit[di]
            continue
        # Visualise only when source and destination orbit different
        # stars — a same-star transfer would be a degenerate line.
        if s_star != d_star:
            routes.append((s_eid, d_eid, flow))
        s_amt -= flow
        d_amt -= flow
        remaining -= flow
        if s_amt <= 0:
            si += 1
            if si < len(surplus):
                s_eid, s_amt, s_star = surplus[si]
        if d_amt <= 0:
            di += 1
            if di < len(deficit):
                d_eid, d_amt, d_star = deficit[di]
    return routes

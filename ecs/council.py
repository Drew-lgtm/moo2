"""Galactic Council — MOO2-style diplomatic victory.

Every ``COUNCIL_INTERVAL`` turns the council convenes. The two
highest-population empires are the candidates; every empire (including
the candidates) casts population-weighted votes for whichever candidate
it likes more (by diplomacy attitude), or abstains if it dislikes both.

If a candidate's votes reach ``VICTORY_FRACTION`` of the *total*
population in the galaxy, they're elected Galactic Emperor:

- Player elected  → diplomatic victory.
- An AI elected   → the player may **Accept** (defeat) or **Defy**, in
  which case the player goes to war with the new emperor and everyone
  who backed them, and the game continues.

No candidate reaching the threshold → no emperor this session.
"""
from __future__ import annotations

from ecs.components import Empire, Owner, Population


COUNCIL_INTERVAL = 25      # turns between council sessions
VICTORY_FRACTION = 2 / 3   # share of total votes needed to win


def is_council_turn(turn: int) -> bool:
    return turn > 0 and turn % COUNCIL_INTERVAL == 0


def _empire_population(component_mgr, empire_id: int) -> int:
    total = 0
    for eid, owner in component_mgr.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        pop = component_mgr.get_component(eid, Population)
        if pop is not None:
            total += pop.current
    return total


def tally_votes(game) -> dict:
    """Run a council session. Returns a result dict:

    {
        "candidates": [id, id],          # up to two front-runners
        "votes": {empire_id: weight},    # votes each candidate received
        "ballots": {voter_id: cand_id},  # who each empire voted for (or None)
        "total": int,                    # total population (vote pool)
        "winner": empire_id | None,
        "supporters": [empire_id, ...],  # who voted for the winner
    }
    """
    cm = game.component_mgr
    diplo = getattr(game, "diplomacy", None)

    empires = [emp for _eid, emp in cm.get_all(Empire)]
    pops = {emp.id: _empire_population(cm, emp.id) for emp in empires}
    # Only empires that still hold population participate.
    living = [emp for emp in empires if pops[emp.id] > 0]
    total = sum(pops[emp.id] for emp in living)

    result = {
        "candidates": [], "votes": {}, "ballots": {},
        "total": total, "winner": None, "supporters": [],
    }
    if len(living) < 2 or total <= 0:
        return result

    # Two highest-population empires are the candidates.
    living.sort(key=lambda e: pops[e.id], reverse=True)
    candidates = [living[0].id, living[1].id]
    result["candidates"] = candidates
    result["votes"] = {c: 0 for c in candidates}

    def _attitude(voter_id, cand_id) -> int:
        if voter_id == cand_id:
            return 1000  # always back yourself
        if diplo is None:
            return 0
        return diplo.attitude(voter_id, cand_id)

    for voter in living:
        # Vote for the preferred candidate; abstain if hostile to both.
        best, best_att = None, None
        for cand in candidates:
            att = _attitude(voter.id, cand)
            if best is None or att > best_att:
                best, best_att = cand, att
        # Abstain if the voter is hostile to its "preferred" candidate
        # and isn't a candidate itself.
        if voter.id not in candidates and best_att is not None and best_att <= -30:
            result["ballots"][voter.id] = None
            continue
        result["ballots"][voter.id] = best
        result["votes"][best] += pops[voter.id]

    # Determine winner.
    for cand in candidates:
        if result["votes"][cand] >= VICTORY_FRACTION * total:
            result["winner"] = cand
            result["supporters"] = [
                v for v, c in result["ballots"].items() if c == cand
            ]
            break

    return result


def defy_emperor(game, result: dict):
    """The player rejects the elected AI emperor. The player goes to war
    with the emperor and everyone who voted for them."""
    diplo = getattr(game, "diplomacy", None)
    player = game.player_empire()
    if diplo is None or player is None or result.get("winner") is None:
        return
    turn = getattr(game.galaxy, "turn", 0)
    all_ids = [emp.id for _e, emp in game.component_mgr.get_all(Empire)]
    targets = set(result["supporters"]) | {result["winner"]}
    for tid in targets:
        if tid != player.id:
            diplo.declare_war(player.id, tid, turn, all_ids)
    diplo.save()

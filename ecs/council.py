"""Galactic Council — MOO2-style diplomatic victory.

Every ``COUNCIL_INTERVAL`` turns the council convenes. Two changes from
the naive model:

1. **Dominance auto-win.** If a single empire already controls
   ``VICTORY_FRACTION`` (two thirds) of the galaxy's population, there is
   no point holding a vote — it would self-elect anyway. That empire is
   declared Emperor outright and the ballot is skipped.

2. **Open ballot.** Every *living* empire is a candidate, and the player
   actively casts their (population-weighted) vote for whichever empire
   they like — or abstains. AI empires vote by diplomatic attitude.

If a candidate's votes reach ``VICTORY_FRACTION`` of the *total*
population, they're elected Galactic Emperor:

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
AI_ABSTAIN_ATTITUDE = -30  # an AI abstains if it dislikes its best option this much


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


def _ai_vote(voter_id: int, candidates: list[int], diplo) -> int | None:
    """Which candidate an AI backs. Always self if able; otherwise the
    best-liked candidate, abstaining if hostile even to that one."""
    best, best_att = None, None
    for cand in candidates:
        if cand == voter_id:
            return voter_id  # always back yourself
        att = diplo.attitude(voter_id, cand) if diplo is not None else 0
        if best is None or att > best_att:
            best, best_att = cand, att
    if best_att is not None and best_att <= AI_ABSTAIN_ATTITUDE:
        return None
    return best


def convene(game) -> dict:
    """Open a council session. Returns a session dict the council scene
    drives. The player's ballot is filled in later via ``finalize``.

    {
        "candidates": [id, ...],          # every living empire
        "pops": {id: population},
        "total": int,                     # total population (vote pool)
        "ai_ballots": {voter_id: cand_id|None},
        "player_id": id | None,
        "auto_winner": id | None,         # dominance (>=2/3 pop) → skip vote
        # filled by finalize():
        "votes": {cand_id: weight},
        "ballots": {voter_id: cand_id|None},
        "winner": id | None,
        "supporters": [id, ...],
        "finalized": bool,
    }
    """
    cm = game.component_mgr
    diplo = getattr(game, "diplomacy", None)

    empires = [emp for _eid, emp in cm.get_all(Empire)]
    pops = {emp.id: _empire_population(cm, emp.id) for emp in empires}
    living = [emp for emp in empires if pops[emp.id] > 0]
    total = sum(pops[emp.id] for emp in living)

    player = game.player_empire()
    player_id = player.id if player else None

    session = {
        "candidates": [], "pops": pops, "total": total,
        "ai_ballots": {}, "player_id": player_id, "auto_winner": None,
        "votes": {}, "ballots": {}, "winner": None, "supporters": [],
        "finalized": False,
    }
    if len(living) < 2 or total <= 0:
        return session

    # Candidates = every living empire, biggest first (display order).
    living.sort(key=lambda e: pops[e.id], reverse=True)
    candidates = [e.id for e in living]
    session["candidates"] = candidates

    # Dominance check: one empire already holds two thirds of the galaxy.
    for e in living:
        if pops[e.id] >= VICTORY_FRACTION * total:
            session["auto_winner"] = e.id
            break

    # Precompute AI ballots; the player's is added in finalize().
    for voter in living:
        if voter.id == player_id:
            continue
        session["ai_ballots"][voter.id] = _ai_vote(voter.id, candidates, diplo)

    return session


def finalize(session: dict, player_choice: int | None) -> dict:
    """Tally the session with the player's ballot (a candidate id, or
    None to abstain) and determine the winner. Idempotent-ish: safe to
    call once after the player votes."""
    ballots = dict(session.get("ai_ballots", {}))
    pid = session.get("player_id")
    if pid is not None:
        ballots[pid] = player_choice

    pops = session.get("pops", {})
    votes = {c: 0 for c in session.get("candidates", [])}
    for voter, cand in ballots.items():
        if cand in votes:
            votes[cand] += pops.get(voter, 0)

    total = max(1, session.get("total", 0))
    winner = session.get("auto_winner")
    if winner is None:
        for cand, weight in votes.items():
            if weight >= VICTORY_FRACTION * total:
                winner = cand
                break

    session["ballots"] = ballots
    session["votes"] = votes
    session["winner"] = winner
    session["supporters"] = (
        [v for v, c in ballots.items() if c == winner] if winner is not None else []
    )
    session["finalized"] = True
    return session


# Backward-compatible alias: older callers used tally_votes() to both run
# and resolve the council. It now just opens the session (the scene
# finalizes after the player votes, or immediately on a dominance win).
def tally_votes(game) -> dict:
    return convene(game)


def defy_emperor(game, result: dict):
    """The player rejects the elected AI emperor. The player goes to war
    with the emperor and everyone who voted for them."""
    diplo = getattr(game, "diplomacy", None)
    player = game.player_empire()
    if diplo is None or player is None or result.get("winner") is None:
        return
    turn = getattr(game.galaxy, "turn", 0)
    all_ids = [emp.id for _e, emp in game.component_mgr.get_all(Empire)]
    targets = set(result.get("supporters", [])) | {result["winner"]}
    for tid in targets:
        if tid != player.id:
            diplo.declare_war(player.id, tid, turn, all_ids)
    diplo.save()

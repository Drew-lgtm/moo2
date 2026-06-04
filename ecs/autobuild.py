"""Per-colony autobuild — automate the boring queueing.

A player can toggle ``BuildState.autobuild`` on for any of their
colonies (Colony screen → ``Auto`` button). The flag holds a
personality name (``"balanced"`` / ``"economic"`` / ``"scientific"`` /
``"militaristic"``) whose ``build_priority`` list drives the queue.

Each turn — before ``production_tick`` — ``autobuild_tick`` walks every
player colony with ``autobuild`` set and an empty queue, and starts the
first eligible building in that personality's priority list. Ships are
intentionally NOT auto-queued (build them deliberately) and locked-out
or tech-gated projects are skipped.

The player can still queue / interrupt manually at any time; autobuild
only steps in when there's literally nothing being built.
"""
from __future__ import annotations

from ecs.components import Owner, BuildState, Empire, TechState, Planet
from ecs.projects import PROJECTS, project_is_available
from ecs.personalities import get as get_personality, PERSONALITIES
from ecs.db import get_connection, update_planet_build


# Personalities the player can pick for a colony's autobuild. Same
# catalog as the AI uses.
AVAILABLE_PROFILES = list(PERSONALITIES.keys())  # ["balanced","economic",...]


def cycle_profile(current: str) -> str:
    """Cycle order shown by the Colony screen Auto button:
    "" (Off) -> balanced -> economic -> scientific -> militaristic -> ""."""
    order = [""] + AVAILABLE_PROFILES
    try:
        idx = order.index(current)
    except ValueError:
        idx = 0
    return order[(idx + 1) % len(order)]


def profile_label(profile: str) -> str:
    if not profile:
        return "Off"
    return PERSONALITIES.get(profile, {}).get("name", profile.title())


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


def autobuild_tick(game, new_turn: int):
    """Queue the next priority project on any player-owned, autobuild-
    enabled colony whose queue + current_project are empty. Runs before
    ``production_tick`` so the new project starts accumulating industry
    *this* turn rather than next."""
    cm = game.component_mgr
    player = _player(cm)
    if player is None:
        return
    unlocked = _player_unlocked(cm, player.id)
    pending: list[tuple[int, str, int]] = []  # (planet_id, project_id, progress)

    for entity_id, owner in cm.get_all(Owner):
        if owner.empire_id != player.id:
            continue
        bs = cm.get_component(entity_id, BuildState)
        if bs is None or not bs.autobuild:
            continue
        if bs.current_project or bs.queue:
            continue  # player or autobuild already queued something
        planet = cm.get_component(entity_id, Planet)
        if planet is None:
            continue

        priority = get_personality(bs.autobuild).get("build_priority", [])
        completed = set(bs.completed)
        for project_id in priority:
            proj = PROJECTS.get(project_id)
            if proj is None:
                continue
            # Autobuild handles only buildings — ships are an explicit
            # player decision (avoids accidental fleet hoarding).
            if proj.get("type") == "ship":
                continue
            if project_id in completed:
                continue
            if not project_is_available(project_id, unlocked):
                continue
            bs.current_project = project_id
            pending.append((planet.id, project_id, bs.progress))
            break

    if not pending:
        return
    with get_connection() as conn:
        for planet_id, project_id, progress in pending:
            update_planet_build(conn, planet_id, project_id, progress)
        conn.commit()

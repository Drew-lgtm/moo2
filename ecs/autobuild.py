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
from ecs.personalities import PERSONALITIES
from ecs.races import traits_for_empire
from ecs.db import get_connection, update_planet_build


# Autobuild profiles — decoupled from AI personalities so we can add
# player-only options (like "Farming") without polluting the AI's
# behaviour catalog. The four AI-mirror profiles just borrow the
# personality's ``build_priority`` so they stay in lock-step with how
# the AI plays its own colonies.
AUTOBUILD_PROFILES: dict[str, dict] = {
    "balanced":     {"label": "Balanced",
                     "build_priority": PERSONALITIES["balanced"]["build_priority"]},
    "economic":     {"label": "Economic",
                     "build_priority": PERSONALITIES["economic"]["build_priority"]},
    "scientific":   {"label": "Scientific",
                     "build_priority": PERSONALITIES["scientific"]["build_priority"]},
    "militaristic": {"label": "Militaristic",
                     "build_priority": PERSONALITIES["militaristic"]["build_priority"]},
    # Player-only profile: stack every food / growth / max-pop building
    # the empire can build, then back-fill with basic economy /
    # research so a maxed-out farm world still pulls its weight.
    "farming":      {"label": "Farming", "build_priority": [
        "granary",              # +growth (no tech)
        "hydroponics",          # +2 max pop (Agriculture)
        "subterranean_farms",   # +3 flat food (Soil Enrichment) — fungi vats
        "soil_enrichment_b",    # +1 max pop + growth (Soil Enrichment)
        "cloning_center",       # +1 max pop + big growth (Cloning)
        "atmospheric_renewer",  # +2 max pop + growth (Advanced Construction)
        "terraforming",         # +3 max pop (Terraforming)
        "weather_control_center", # +5 food + growth (Weather Controller)
        "orbital_mirror",       # +4 food + growth (Orbital Mirror Array)
        # Back-fill once the farming chain is exhausted so the world
        # still contributes industry / BC / research / defence.
        "factory", "marketplace", "research_lab", "capital",
        "pleasure_dome_b",      # +2 max pop + BC + growth (Pleasure Dome)
        "missile_base", "ground_batteries", "star_base",
    ]},
}

# Cycle order shown by the Colony screen Auto button. "" = Off.
PROFILE_CYCLE = ["", "balanced", "economic", "scientific", "militaristic", "farming"]


def cycle_profile(current: str) -> str:
    """Step the Auto button through the profile cycle."""
    try:
        idx = PROFILE_CYCLE.index(current)
    except ValueError:
        idx = 0
    return PROFILE_CYCLE[(idx + 1) % len(PROFILE_CYCLE)]


def profile_label(profile: str) -> str:
    if not profile:
        return "Off"
    return AUTOBUILD_PROFILES.get(profile, {}).get("label", profile.title())


def profile_priority(profile: str) -> list[str]:
    """Project ids the autobuild tick walks for this profile."""
    return AUTOBUILD_PROFILES.get(profile, {}).get("build_priority", [])


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
    traits = traits_for_empire(cm, player.id)
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

        priority = profile_priority(bs.autobuild)
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
            if not project_is_available(project_id, unlocked, traits):
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

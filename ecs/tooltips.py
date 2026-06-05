"""Tooltip text builders.

Each public helper returns ``list[str]`` ready to hand to
``Tooltip.show``. The first line is treated as a title; subsequent
lines are body text. Lines prefixed with ``"hint:"`` render dimmed.

Scenes call these from their ``tooltip_at(pos)`` implementations — see
``ecs/tooltip.py`` for the dispatch.
"""
from __future__ import annotations

from ecs.techs import TECHS, FIELD_NAMES
from ecs.ships import SHIPS
from ecs.projects import PROJECTS


# ----- techs ----------------------------------------------------------

_BUTTON_HINTS = {
    "colonies":  "List of your colonies — population, output, build queue.",
    "planets":   "Every known planet, owned or otherwise.",
    "research":  "Open the tech tree to pick a research target.",
    "diplomacy": "Treaties, attitude, gifts & demands with rivals.",
    "leaders":   "Hire and assign heroes to colonies or warships.",
    "races":     "Race rosters and traits.",
    "espionage": "Train spies, assign offensive missions, view reports.",
    "info":      "Empire summary and turn projection.",
    "turn":      "End your turn and resolve everyone else's.",
}


def tech_tooltip(tech_id: str, unlocked: set[str] | None = None,
                 locked_out: set[str] | None = None) -> list[str]:
    """Tech card: name, field, tier, cost, prereqs, effect summary,
    research status. ``unlocked`` / ``locked_out`` (if provided) drive
    the status line at the bottom."""
    tech = TECHS.get(tech_id)
    if tech is None:
        return [tech_id, "hint:(unknown tech)"]

    field = FIELD_NAMES.get(tech.get("field", ""), tech.get("field", "?"))
    tier = tech.get("tier", "?")
    cost = tech.get("cost", "?")
    lines: list[str] = [
        tech.get("name", tech_id),
        f"{field} · Tier {tier} · {cost} RP",
    ]
    desc = tech.get("description") or ""
    if desc:
        lines.append(desc)

    # Effect summary — pull the structured fields people care about.
    effects: list[str] = []
    for key, label in (
        ("speed_bonus",          "+{} ship speed"),
        ("fuel_range",           "+{} fuel range (parsecs)"),
        ("sensor_range",         "+{} sensor range"),
        ("industry_per_worker",  "+{} production / worker"),
        ("food_per_farmer",      "+{} food / farmer"),
        ("research_per_scientist", "+{} research / scientist"),
        ("spy_offense",          "+{} spy skill"),
        ("spy_defense",          "+{} security"),
    ):
        v = tech.get(key)
        if v:
            effects.append(label.format(v))
    if tech.get("stealth"):
        effects.append("stealth: caught spies rarely identified")
    if tech.get("mind_scan"):
        effects.append("mind scan: caught enemy spies always unmasked")
    eq = tech.get("equipment")
    if eq:
        slot = eq.get("slot", "")
        bits = [f"size {eq.get('size', 0)}"]
        for k, label in (("attack", "+{} attack/slot"),
                          ("hull",   "+{} hull"),
                          ("defense", "+{} defense"),
                          ("capacity", "shield cap {}"),
                          ("regen",   "regen +{}/round")):
            v = eq.get(k)
            if v:
                bits.append(label.format(v))
        if eq.get("space_bonus_pct"):
            bits.append(f"+{eq['space_bonus_pct']}% ship space")
        if eq.get("cloak"):
            bits.append("cloak")
        effects.append(f"{slot.capitalize()}: " + ", ".join(bits))
    for e in effects:
        lines.append(e)
    if tech.get("effect_stub"):
        lines.append("hint:effect not yet implemented")

    prereqs = tech.get("prereqs") or []
    if prereqs:
        names = ", ".join(TECHS.get(p, {}).get("name", p) for p in prereqs)
        lines.append(f"hint:needs {names}")

    if unlocked is not None and tech_id in unlocked:
        lines.append("hint:UNLOCKED")
    elif locked_out is not None and tech_id in locked_out:
        lines.append("hint:LOCKED OUT — picked a different tier alternative")

    # Tier-mates (the picks-one alternatives at this tier).
    group = tech.get("tier_group")
    if group:
        mates = [t for t, s in TECHS.items()
                 if s.get("tier_group") == group and t != tech_id]
        if mates:
            mate_names = ", ".join(TECHS[t]["name"] for t in mates)
            lines.append(f"hint:tier alternatives: {mate_names}")
    return lines


# ----- buttons --------------------------------------------------------

def button_tooltip(name: str) -> list[str]:
    label = name.replace("_", " ").title()
    hint = _BUTTON_HINTS.get(name, "")
    return [label, hint] if hint else [label]


# ----- planets --------------------------------------------------------

def planet_tooltip(planet, population=None, build_state=None,
                   owner_name: str | None = None) -> list[str]:
    """Planet card: type · size · richness · gravity, special features,
    population, build status, ownership."""
    bits = [planet.planet_type, planet.size]
    bits.append(f"richness {getattr(planet, 'richness', 'Abundant')}")
    bits.append(f"gravity {getattr(planet, 'gravity', 'Normal')}")
    lines = ["Planet", " · ".join(bits)]

    if population is not None and getattr(population, "current", 0) > 0:
        lines.append(
            f"Pop {population.current}M / {population.max}M"
            f"  (F{population.farmers}/W{population.workers}/S{population.scientists})"
        )
    if build_state is not None:
        if build_state.current_project:
            lines.append(
                f"Building: {build_state.current_project} "
                f"({build_state.progress}/?)"
            )
        if build_state.queue:
            lines.append(f"Queue: {len(build_state.queue)} more")

    specials = getattr(planet, "special", None) or []
    if specials:
        lines.append("hint:features: " + ", ".join(specials))
    if not planet.colonizable:
        lines.append("hint:not colonizable")
    if owner_name:
        lines.append(f"hint:held by {owner_name}")
    return lines


# ----- stars ----------------------------------------------------------

def star_tooltip(name: str, planet_count: int, owner_names: list[str],
                 visible: bool, distance_pc: float | None = None) -> list[str]:
    """Star tooltip — counts of planets and who's there."""
    lines = [name or "Star"]
    if not visible:
        lines.append("hint:unexplored — right-click a closer star for detail")
        return lines
    lines.append(f"{planet_count} planet(s)")
    if owner_names:
        lines.append("held by: " + ", ".join(owner_names))
    if distance_pc is not None:
        lines.append(f"hint:{distance_pc:.1f} pc from your selected fleet")
    return lines


# ----- ships ----------------------------------------------------------

# ----- treaties / diplomacy actions -----------------------------------

_TREATY_DESCRIPTIONS = {
    "non_aggression": "A pledge of non-attack. Breaking it scars your "
                      "reputation with everyone.",
    "trade":          "Both sides earn +% BC per turn from each other's economy.",
    "research":       "Both sides earn +% research per turn from each "
                      "other's labs.",
    "open_borders":   "Ships may traverse each other's space and refuel at "
                      "allied colonies.",
    "alliance":       "Mutual defence + shared visibility. Heavy commitment.",
    "defensive_pact": "If one side is attacked, the other joins the war.",
}

_DIPLO_ACTION_HINTS = {
    "propose":      "Offer a treaty. The AI weighs attitude and strength.",
    "cancel":       "Cancels the treaty with a 5-turn notice — others can "
                    "still see the diplomatic shift.",
    "declare_war":  "Immediate war. Skips any treaty timer; breaking a "
                    "peace counts as betrayal.",
    "make_peace":   "Sue for peace. Attitude floor at -10 after acceptance.",
    "gift":         "Hand over 50 BC to lift attitude.",
    "demand":       "Threaten for 50 BC of tribute. Refused if you're "
                    "weaker.",
    "trade_tech":   "Offer one of your unlocked techs for one of theirs.",
    "trade_chart":  "Swap exploration maps for instant mutual visibility.",
}


def treaty_tooltip(treaty: str) -> list[str]:
    """Two-line tooltip for a treaty button — full name + what it does."""
    from ecs.diplomacy import TREATY_NAMES
    name = TREATY_NAMES.get(treaty, treaty.replace("_", " ").title())
    desc = _TREATY_DESCRIPTIONS.get(treaty, "")
    return [name, desc] if desc else [name]


def diplo_action_tooltip(action: str, treaty_arg: str | None = None) -> list[str]:
    """Tooltip for a diplomacy button (propose / declare_war / make_peace
    / gift / demand / trade_tech / trade_chart / cancel)."""
    label = action.replace("_", " ").title()
    hint = _DIPLO_ACTION_HINTS.get(action, "")
    lines = [label]
    if hint:
        lines.append(hint)
    if treaty_arg and action in ("propose", "cancel"):
        from ecs.diplomacy import TREATY_NAMES
        lines.append(f"hint: target: {TREATY_NAMES.get(treaty_arg, treaty_arg)}")
    return lines


def empire_row_tooltip(emp, attitude: int | None = None,
                        treaties: list[str] | None = None,
                        at_war: bool = False) -> list[str]:
    """Tooltip for an empire row (diplomacy / espionage / leaders)."""
    lines = [emp.name, f"hint: {emp.race_type}"]
    if at_war:
        lines.append("AT WAR")
    if attitude is not None:
        lines.append(f"Attitude: {attitude:+d}")
    if treaties:
        from ecs.diplomacy import TREATY_NAMES
        names = ", ".join(TREATY_NAMES.get(t, t) for t in treaties)
        lines.append(f"hint: Treaties: {names}")
    return lines


# ----- leaders --------------------------------------------------------

def leader_tooltip(leader, assignment_label: str | None = None) -> list[str]:
    """Tooltip for a leader card — skill, effect, salary, post."""
    lines = [
        f"{leader.name}",
        f"{('Colony' if leader.category == 'colony' else 'Ship')} · "
        f"{leader.skill_name} Lv.{leader.level}",
        f"Effect: {leader.effect_text()}",
    ]
    if leader.owner_empire_id is not None:
        lines.append(f"Salary {leader.salary} BC/turn")
    else:
        lines.append(f"Hire: {leader.hire_cost} BC (then {leader.salary}/turn)")
    if assignment_label:
        lines.append(f"hint: Post: {assignment_label}")
    return lines


# ----- spies ----------------------------------------------------------

_SPY_MISSION_HINTS = {
    "steal":       "Copy a random tech the target knows and you don't. "
                   "Caught spies who get identified poison relations.",
    "sabotage":    "Destroy a random target building, or drain BC if "
                   "nothing to wreck.",
    "assassinate": "Kill one of the target's hired leaders. Higher catch "
                   "risk — wet work is loud.",
    "incite":      "Spark guerrilla unrest on a target colony: resets "
                   "assimilation, ground forces wear down.",
    "frame":       "Sabotage with a fall guy: a random THIRD empire "
                   "takes the diplomatic blame. Needs 3+ rivals alive.",
    "defense":     "Counter-intel at home. Boosts security against incoming spies.",
}


def spy_mission_tooltip(mission: str) -> list[str]:
    from ecs.espionage import MISSION_NAMES
    label = MISSION_NAMES.get(mission, mission.capitalize())
    hint = _SPY_MISSION_HINTS.get(mission, "")
    return [label, hint] if hint else [label]


def spy_row_tooltip(emp, my_spies_here: dict) -> list[str]:
    """Tooltip for an enemy row in the Espionage screen — empire +
    current assignments against them."""
    lines = [f"Spy ops vs {emp.name}", f"hint: {emp.race_type}"]
    for mission in ("steal", "sabotage"):
        n = my_spies_here.get(mission, 0)
        if n:
            lines.append(f"{mission.capitalize()}: {n} assigned")
    if not any(my_spies_here.values()):
        lines.append("hint: no operatives assigned")
    return lines


# ----- projects (buildings + ships) ----------------------------------

def project_tooltip(project_id: str, unlocked_techs=None,
                    installed: bool = False) -> list[str]:
    """One-stop tooltip for any project — building or ship. Shows
    category, production cost, effects, required tech, description.
    Ship projects also surface the live auto-loadout when
    ``unlocked_techs`` is provided. ``installed=True`` marks a building
    that's already completed on a planet (no cost line — it's built)."""
    proj = PROJECTS.get(project_id)
    if proj is None:
        return [project_id]
    lines: list[str] = [proj.get("name", project_id)]
    cat = proj.get("category", "")
    cost = proj.get("cost", "?")
    if proj.get("type") == "ship":
        lines.append(f"Ship · {cost} production")
        ship_class = proj.get("ship_class")
        if ship_class and unlocked_techs is not None:
            from ecs.ship_design import loadout_summary
            lines.append(loadout_summary(ship_class, unlocked_techs))
    else:
        if installed:
            lines.append(f"{cat.title()} · built")
        else:
            lines.append(f"{cat.title()} · {cost} production")
        effects = proj.get("effects", {})
        if effects:
            bits = [f"+{v} {k.replace('_', ' ')}" for k, v in effects.items()]
            lines.append("Effects: " + ", ".join(bits))
    req = proj.get("required_tech")
    if req:
        tech_name = TECHS.get(req, {}).get("name", req)
        # For already-built buildings the requirement is past — phrase
        # as info rather than a gate.
        if installed:
            lines.append(f"hint:from {tech_name}")
        else:
            lines.append(f"hint:needs {tech_name}")
    desc = proj.get("description")
    if desc:
        lines.append(f"hint:{desc}")
    return lines


def ship_tooltip(ship, owner_name: str | None = None) -> list[str]:
    """Ship card — class + frozen loadout from build time. Uses the
    same field semantics ``ecs.ship_design.stored_loadout_summary``
    relies on."""
    spec = SHIPS.get(ship.ship_class, {})
    name = spec.get("name", ship.ship_class.title())
    lines = [name]
    lines.append(
        f"hull {spec.get('hull','?')}  speed {spec.get('speed','?')}  "
        f"space {spec.get('space','?')}"
    )
    parts: list[str] = []
    if ship.armor_tech:
        parts.append(TECHS.get(ship.armor_tech, {}).get("name", ship.armor_tech))
    if ship.shield_tech:
        parts.append(TECHS.get(ship.shield_tech, {}).get("name", ship.shield_tech))
    if ship.weapon_tech and ship.weapon_count:
        wname = TECHS.get(ship.weapon_tech, {}).get("name", ship.weapon_tech)
        parts.append(f"{ship.weapon_count}× {wname}")
    for sp_id in (ship.specials or []):
        parts.append(TECHS.get(sp_id, {}).get("name", sp_id))
    lines.append("Loadout: " + (" · ".join(parts) if parts else "(none)"))
    if owner_name:
        lines.append(f"hint:flag of {owner_name}")
    return lines

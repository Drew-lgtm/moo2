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

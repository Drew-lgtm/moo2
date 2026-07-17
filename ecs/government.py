"""Government types and colony morale (MOO2-style).

An empire runs under one **government**, an empire-wide policy chosen from
those its research has unlocked. Each government trades off differently:

- **Dictatorship** (default) — neutral baseline; order through control.
- **Democracy** (needs *Governance*) — a science/commerce powerhouse
  (+research, +BC empire-wide) with slightly happier home worlds, but
  conquered worlds chafe badly under its freedoms.
- **Imperium** (needs *Galactic Unification*) — rigid central order lifts
  morale on every colony and keeps conquered worlds in line.

**Morale** is a per-colony 0–100 level. It starts at a neutral 50, shifts
with the government (and, for recently-conquered worlds, a restiveness
penalty), and scales the colony's industry / research / BC output between
0.75× (miserable) and 1.25× (thriving) — food is unaffected (people eat
regardless). Government income %s stack on top, empire-wide.

State: ``Empire.government`` holds the key (default 'dictatorship').
"""
from __future__ import annotations


DEFAULT_GOVERNMENT = "dictatorship"

# Each government: display name, the tech that unlocks it (None = always
# available), empire-wide research/BC percentage bonuses, a flat colony
# morale modifier, and an extra morale modifier applied to still-
# assimilating (recently conquered) colonies.
GOVERNMENTS: dict[str, dict] = {
    "dictatorship": {
        "name": "Dictatorship", "unlock": None,
        "research_pct": 0, "bc_pct": 0,
        "morale": 0, "conquered_morale": 0,
        "description": "Order through central control. No bonuses, no penalties.",
    },
    "democracy": {
        "name": "Democracy", "unlock": "governance",
        "research_pct": 20, "bc_pct": 10,
        "morale": 5, "conquered_morale": -25,
        "description": "+20% research, +10% BC, content home worlds — but "
                       "conquered worlds resent their new freedoms.",
    },
    "imperium": {
        "name": "Imperium", "unlock": "galactic_unification",
        "research_pct": 0, "bc_pct": 0,
        "morale": 20, "conquered_morale": 10,
        "description": "Rigid central order: higher morale on every colony "
                       "and a firm grip on conquered worlds.",
    },
}

# Morale tuning.
MORALE_BASE = 50            # a neutral, native colony under Dictatorship
MORALE_CONQUERED_PENALTY = -20   # base restiveness while still assimilating
# Output scaling: multiplier = MORALE_MULT_FLOOR + MORALE_MULT_SPAN * morale/100.
# morale 50 -> 1.0, 100 -> 1.25, 0 -> 0.75.
MORALE_MULT_FLOOR = 0.75
MORALE_MULT_SPAN = 0.5

# AI government preference, best-first: adopt the most advanced unlocked.
_AI_PREFERENCE = ["imperium", "democracy", "dictatorship"]


def government_of(empire) -> str:
    """The empire's current government key (defaults to dictatorship for
    older saves / empires with the field unset)."""
    g = getattr(empire, "government", None)
    return g if g in GOVERNMENTS else DEFAULT_GOVERNMENT


def available_governments(unlocked_techs) -> list[str]:
    """Government keys this empire may adopt, given its unlocked techs.
    Dictatorship is always available; the rest need their unlock tech."""
    unlocked = set(unlocked_techs or ())
    out = []
    for key, g in GOVERNMENTS.items():
        unlock = g["unlock"]
        if unlock is None or unlock in unlocked:
            out.append(key)
    return out


def government_pct(gov_key: str) -> tuple[int, int]:
    """(research_pct, bc_pct) empire-wide bonuses for a government."""
    g = GOVERNMENTS.get(gov_key, GOVERNMENTS[DEFAULT_GOVERNMENT])
    return g["research_pct"], g["bc_pct"]


def colony_morale(gov_key: str, planet) -> int:
    """A colony's morale (0–100) under the given government. Recently
    conquered worlds (still assimilating) are less content."""
    g = GOVERNMENTS.get(gov_key, GOVERNMENTS[DEFAULT_GOVERNMENT])
    morale = MORALE_BASE + g["morale"]
    if getattr(planet, "assimilation_progress", 100) < 100:
        morale += MORALE_CONQUERED_PENALTY + g["conquered_morale"]
    return max(0, min(100, morale))


def morale_output_mult(morale: int) -> float:
    """Output multiplier for a colony at this morale (0.75×–1.25×)."""
    return MORALE_MULT_FLOOR + MORALE_MULT_SPAN * (morale / 100.0)


def ai_preferred_government(unlocked_techs) -> str:
    """The government an AI adopts: the most advanced one it has unlocked."""
    available = set(available_governments(unlocked_techs))
    for key in _AI_PREFERENCE:
        if key in available:
            return key
    return DEFAULT_GOVERNMENT

"""Inter-empire diplomacy: attitude, treaties, war, reputation.

State is pairwise and symmetric — keyed by ``(min(a,b), max(a,b))``.
Each pair tracks:

- ``attitude``: -100 (hostile) .. +100 (allied). Drives AI decisions
  and decays toward 0 each turn.
- ``at_war``: bool. Combat (combat.py) and invasion (invasion.py) only
  resolve between empires that are at war.
- ``treaties``: a set of active agreement keys (see TREATIES).

Two safety nets the player asked for:

1. **Betrayal reputation** — declaring war or invading while a peace /
   non-aggression treaty is in force flags the aggressor as a
   treaty-breaker: every *other* empire's attitude toward them drops,
   and those empires auto-cancel their own Trade / Research treaties
   with the betrayer.

2. **Cancellation notice** — cancelling a treaty doesn't end it
   immediately; it stays in force for ``CANCEL_NOTICE_TURNS`` more
   turns. ``tick`` removes treaties whose notice has elapsed.

The live object hangs off ``game.diplomacy`` and persists through the
``diplomacy`` / ``diplomacy_pending`` tables.
"""
from __future__ import annotations

from ecs.db import get_connection


# ---- treaty catalog ----------------------------------------------------

NON_AGGRESSION = "non_aggression"
TRADE = "trade"
RESEARCH = "research"
ALLIANCE = "alliance"
DEFENSIVE_PACT = "defensive_pact"
OPEN_BORDERS = "open_borders"

TREATIES = [NON_AGGRESSION, TRADE, RESEARCH, ALLIANCE, DEFENSIVE_PACT, OPEN_BORDERS]

TREATY_NAMES = {
    NON_AGGRESSION: "Non-Aggression Pact",
    TRADE:          "Trade Treaty",
    RESEARCH:       "Research Treaty",
    ALLIANCE:       "Alliance",
    DEFENSIVE_PACT: "Defensive Pact",
    OPEN_BORDERS:   "Open Borders",
}

# Treaties that imply a peace obligation — breaking the peace while one
# of these is active triggers the betrayal penalty.
PEACE_TREATIES = {NON_AGGRESSION, ALLIANCE, DEFENSIVE_PACT}

# Per-turn economic bonuses (percent) applied to BOTH signatories.
TRADE_BONUS_PCT = 15
RESEARCH_BONUS_PCT = 15


# ---- attitude ----------------------------------------------------------

ATTITUDE_MIN = -100
ATTITUDE_MAX = 100

# Level thresholds (low end inclusive). Used for display + AI gating.
ATTITUDE_LEVELS = [
    (-100, "Hostile"),
    (-49, "Wary"),
    (-14, "Neutral"),
    (15, "Cordial"),
    (50, "Friendly"),
]


def attitude_level(value: int) -> str:
    label = "Neutral"
    for threshold, name in ATTITUDE_LEVELS:
        if value >= threshold:
            label = name
    return label


# ---- tuning knobs ------------------------------------------------------

CANCEL_NOTICE_TURNS = 5

# Attitude shifts.
ATTITUDE_DECAY = 1            # drift toward 0 each turn
DECLARE_WAR_HIT = -40         # toward the empire you declared war on
BETRAYAL_SELF_HIT = -30       # extra hit for breaking a peace treaty
BETRAYAL_REPUTATION_HIT = -20 # every other empire's view of the betrayer
INVADE_HIT = -25             # attitude hit on the invaded empire
GIFT_ATTITUDE_PER_50BC = 5    # +attitude per 50 BC gifted
SHARED_WAR_BONUS = 10         # toward an ally you're co-warring with


class Diplomacy:
    def __init__(self):
        # (a,b) sorted -> {"attitude": int, "at_war": bool, "treaties": set[str]}
        self.pairs: dict[tuple[int, int], dict] = {}
        # (a,b,treaty) -> turn the treaty actually ends
        self.pending_cancel: dict[tuple[int, int, str], int] = {}
        # rolling log of notable events for UI surfacing
        self.log: list[str] = []

    # -- key helpers ----------------------------------------------------

    @staticmethod
    def _key(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a <= b else (b, a)

    def _pair(self, a: int, b: int) -> dict:
        k = self._key(a, b)
        if k not in self.pairs:
            self.pairs[k] = {"attitude": 0, "at_war": False, "treaties": set()}
        return self.pairs[k]

    # -- queries --------------------------------------------------------

    def attitude(self, a: int, b: int) -> int:
        return self._pair(a, b)["attitude"]

    def at_war(self, a: int, b: int) -> bool:
        if a == b:
            return False
        return self._pair(a, b)["at_war"]

    def has_treaty(self, a: int, b: int, treaty: str) -> bool:
        return treaty in self._pair(a, b)["treaties"]

    def treaties(self, a: int, b: int) -> set:
        return set(self._pair(a, b)["treaties"])

    def has_peace_treaty(self, a: int, b: int) -> bool:
        return bool(self._pair(a, b)["treaties"] & PEACE_TREATIES)

    def peace_cancellation_pending(self, a: int, b: int) -> bool:
        """True if a peace/NAP treaty between the pair is already inside
        its cancellation notice window (winding down to expiry)."""
        key = self._key(a, b)
        return any(
            (ka, kb) == key and treaty in PEACE_TREATIES
            for (ka, kb, treaty) in self.pending_cancel
        )

    def peace_expiry_turn(self, a: int, b: int) -> int | None:
        """Earliest turn a peace treaty between the pair finishes its
        cancellation notice, or None if none is pending."""
        key = self._key(a, b)
        ends = [
            end for (ka, kb, treaty), end in self.pending_cancel.items()
            if (ka, kb) == key and treaty in PEACE_TREATIES
        ]
        return min(ends) if ends else None

    # -- mutations ------------------------------------------------------

    def adjust_attitude(self, a: int, b: int, delta: int):
        p = self._pair(a, b)
        p["attitude"] = max(ATTITUDE_MIN, min(ATTITUDE_MAX, p["attitude"] + delta))

    def set_attitude(self, a: int, b: int, value: int):
        self._pair(a, b)["attitude"] = max(ATTITUDE_MIN, min(ATTITUDE_MAX, value))

    def add_treaty(self, a: int, b: int, treaty: str):
        """Sign a treaty. Alliance implies a non-aggression pact. Signing
        any treaty cancels an in-force war and clears a pending
        cancellation of that treaty."""
        p = self._pair(a, b)
        p["at_war"] = False
        p["treaties"].add(treaty)
        if treaty == ALLIANCE:
            p["treaties"].add(NON_AGGRESSION)
        self.pending_cancel.pop((*self._key(a, b), treaty), None)
        self.adjust_attitude(a, b, 8)

    def remove_treaty_now(self, a: int, b: int, treaty: str):
        """Immediately drop a treaty (used internally by the betrayal
        penalty and once a cancellation notice elapses)."""
        self._pair(a, b)["treaties"].discard(treaty)
        self.pending_cancel.pop((*self._key(a, b), treaty), None)

    def cancel_treaty(self, a: int, b: int, treaty: str, turn: int):
        """Schedule a treaty to end after CANCEL_NOTICE_TURNS. It stays
        in force until then. Re-cancelling just keeps the earlier date."""
        if not self.has_treaty(a, b, treaty):
            return
        key = (*self._key(a, b), treaty)
        if key not in self.pending_cancel:
            self.pending_cancel[key] = turn + CANCEL_NOTICE_TURNS
            self.log.append(
                f"T{turn}: {TREATY_NAMES.get(treaty, treaty)} between "
                f"{a} and {b} will end on turn {self.pending_cancel[key]}."
            )

    def declare_war(self, aggressor: int, target: int, turn: int,
                    all_empire_ids: list[int] | None = None):
        """Open hostilities. If a peace treaty was in force, apply the
        betrayal penalty: reputation damage with every other empire +
        auto-cancellation of their Trade/Research treaties with the
        aggressor."""
        broke_peace = self.has_peace_treaty(aggressor, target)
        p = self._pair(aggressor, target)
        p["at_war"] = True
        # All peace/cooperation treaties between the two are void at once.
        p["treaties"].clear()
        self.adjust_attitude(aggressor, target, DECLARE_WAR_HIT)

        if broke_peace:
            self.adjust_attitude(aggressor, target, BETRAYAL_SELF_HIT)
            self.log.append(f"T{turn}: Empire {aggressor} BROKE a peace treaty with {target}!")
            self._apply_betrayal_reputation(aggressor, turn, all_empire_ids or [])
        else:
            self.log.append(f"T{turn}: Empire {aggressor} declared war on {target}.")

    def _apply_betrayal_reputation(self, betrayer: int, turn: int, all_empire_ids: list[int]):
        """Every other empire likes the betrayer less and severs its
        Trade / Research treaties with them (no notice — trust is gone)."""
        for other in all_empire_ids:
            if other == betrayer:
                continue
            self.adjust_attitude(betrayer, other, BETRAYAL_REPUTATION_HIT)
            for treaty in (TRADE, RESEARCH):
                if self.has_treaty(betrayer, other, treaty):
                    self.remove_treaty_now(betrayer, other, treaty)
                    self.log.append(
                        f"T{turn}: Empire {other} cancelled its "
                        f"{TREATY_NAMES[treaty]} with the treaty-breaker {betrayer}."
                    )

    def make_peace(self, a: int, b: int, turn: int):
        p = self._pair(a, b)
        if p["at_war"]:
            p["at_war"] = False
            # Reset attitude toward neutral so the war doesn't instantly
            # re-trigger — "we've settled our differences." Floors at -10
            # so a freshly-ended war doesn't immediately clear the
            # declare-war threshold (-30) next turn.
            self.set_attitude(a, b, max(self.attitude(a, b), -10))
            self.log.append(f"T{turn}: Empire {a} and {b} signed a peace treaty.")

    def note_invasion(self, aggressor: int, target: int, turn: int,
                      all_empire_ids: list[int] | None = None):
        """Invading enemy territory is an act of war. If not already at
        war (e.g. a sneak attack through a NAP), this declares it and
        triggers the betrayal logic."""
        self.adjust_attitude(aggressor, target, INVADE_HIT)
        if not self.at_war(aggressor, target):
            self.declare_war(aggressor, target, turn, all_empire_ids)

    # -- per-turn tick --------------------------------------------------

    def tick(self, turn: int, all_empire_ids: list[int]):
        """Process elapsed cancellation notices, then decay attitudes
        slightly toward neutral. Allies co-warring drift friendlier."""
        # Finalise cancellations whose notice has elapsed.
        expired = [k for k, end in self.pending_cancel.items() if turn >= end]
        for key in expired:
            a, b, treaty = key
            self._pair(a, b)["treaties"].discard(treaty)
            self.pending_cancel.pop(key, None)
            self.log.append(f"T{turn}: {TREATY_NAMES.get(treaty, treaty)} between {a} and {b} has ended.")

        # Attitude decay toward 0 (war keeps it pinned low — don't decay
        # up out of hostility while fighting).
        for (a, b), p in self.pairs.items():
            att = p["attitude"]
            if p["at_war"]:
                continue
            if att > 0:
                p["attitude"] = max(0, att - ATTITUDE_DECAY)
            elif att < 0:
                p["attitude"] = min(0, att + ATTITUDE_DECAY)

        # Keep the log bounded.
        if len(self.log) > 50:
            self.log = self.log[-50:]

    # -- persistence ----------------------------------------------------

    def save(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM diplomacy")
            conn.execute("DELETE FROM diplomacy_pending")
            for (a, b), p in self.pairs.items():
                conn.execute(
                    "INSERT INTO diplomacy (empire_a, empire_b, attitude, at_war, treaties) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (a, b, p["attitude"], 1 if p["at_war"] else 0, ",".join(sorted(p["treaties"]))),
                )
            for (a, b, treaty), end in self.pending_cancel.items():
                conn.execute(
                    "INSERT INTO diplomacy_pending (empire_a, empire_b, treaty, ends_turn) "
                    "VALUES (?, ?, ?, ?)",
                    (a, b, treaty, end),
                )
            conn.commit()

    def load(self):
        self.pairs.clear()
        self.pending_cancel.clear()
        with get_connection() as conn:
            for row in conn.execute("SELECT * FROM diplomacy"):
                treaties = {t for t in (row["treaties"] or "").split(",") if t}
                self.pairs[(row["empire_a"], row["empire_b"])] = {
                    "attitude": row["attitude"] or 0,
                    "at_war": bool(row["at_war"]),
                    "treaties": treaties,
                }
            for row in conn.execute("SELECT * FROM diplomacy_pending"):
                self.pending_cancel[(row["empire_a"], row["empire_b"], row["treaty"])] = row["ends_turn"]


# Minimum attitude an AI requires before it will accept each treaty
# when another empire proposes one. Alliance is the highest bar.
TREATY_ACCEPT_THRESHOLD = {
    NON_AGGRESSION: -20,
    OPEN_BORDERS:   0,
    TRADE:          5,
    RESEARCH:       15,
    DEFENSIVE_PACT: 30,
    ALLIANCE:       45,
}


def would_accept_treaty(diplomacy: "Diplomacy", target: int, proposer: int, treaty: str) -> bool:
    """Whether ``target`` (an AI) accepts ``treaty`` proposed by
    ``proposer``. At war you must make peace first; otherwise it's a
    pure attitude check against TREATY_ACCEPT_THRESHOLD."""
    if diplomacy.at_war(target, proposer):
        return False
    if diplomacy.has_treaty(target, proposer, treaty):
        return False
    threshold = TREATY_ACCEPT_THRESHOLD.get(treaty, 0)
    return diplomacy.attitude(target, proposer) >= threshold


def would_accept_peace(diplomacy: "Diplomacy", target: int, proposer: int) -> bool:
    """An AI accepts peace if it isn't winning badly — modelled simply
    as attitude not being rock-bottom hostile."""
    return diplomacy.attitude(target, proposer) > -70


def would_accept_tech_trade(diplomacy: "Diplomacy", target: int, proposer: int,
                            give_cost: int, get_cost: int) -> bool:
    """Whether ``target`` accepts a tech swap: it hands over a tech
    worth ``get_cost`` (to the proposer) in return for one worth
    ``give_cost``. Friendlier targets accept worse-for-them deals; at
    war they never trade tech."""
    if diplomacy.at_war(target, proposer):
        return False
    att = diplomacy.attitude(target, proposer)
    # Effective value of what we receive, inflated by goodwill.
    return give_cost * (1 + att / 200) >= get_cost * 0.9


def all_empire_ids(component_mgr) -> list[int]:
    from ecs.components import Empire
    return [emp.id for _eid, emp in component_mgr.get_all(Empire)]


def empire_strength(component_mgr, empire_id: int) -> int:
    """Crude power rating = owned planets + total pop. Used for gang-up
    logic and tribute decisions."""
    from ecs.components import Owner, Population
    planets = 0
    pop = 0
    for eid, owner in component_mgr.get_all(Owner):
        if owner.empire_id != empire_id:
            continue
        planets += 1
        p = component_mgr.get_component(eid, Population)
        if p is not None:
            pop += p.current
    return planets * 3 + pop


def diplomacy_tick(game, new_turn: int):
    """Turn callback: age treaty cancellations + decay attitudes, then
    persist. No-op if diplomacy isn't initialised yet."""
    diplo = getattr(game, "diplomacy", None)
    if diplo is None:
        return
    diplo.tick(new_turn, all_empire_ids(game.component_mgr))
    diplo.save()


def empire_trade_bonus_pct(diplomacy: Diplomacy, empire_id: int, all_empire_ids: list[int]) -> int:
    """Total trade-treaty BC bonus percent for ``empire_id`` (stacks per
    active Trade Treaty partner)."""
    if diplomacy is None:
        return 0
    pct = 0
    for other in all_empire_ids:
        if other != empire_id and diplomacy.has_treaty(empire_id, other, TRADE):
            pct += TRADE_BONUS_PCT
    return pct


def empire_research_bonus_pct(diplomacy: Diplomacy, empire_id: int, all_empire_ids: list[int]) -> int:
    if diplomacy is None:
        return 0
    pct = 0
    for other in all_empire_ids:
        if other != empire_id and diplomacy.has_treaty(empire_id, other, RESEARCH):
            pct += RESEARCH_BONUS_PCT
    return pct

"""Player-perspective turn log.

A tiny rolling record of things that *visibly* happened to the player
empire each turn: buildings finished, techs researched, random events,
combat the player was in or observed, colonies founded / lost, and the
diplomatic moves involving the player's empire. Strictly player-side —
AI-vs-AI internals stay out so the log reads like a personal newsfeed.

The TurnLog is attached to the Game instance (``game.turn_log``) and is
in-memory only — it does not survive save / load. The galaxy view
shows the last turn's entries as a compact strip; longer history is
available by scrolling category logs already plumbed elsewhere
(``game.events_log``, ``game.diplomacy.log``, etc).
"""
from __future__ import annotations


# Short, fixed category labels so the UI can colour / filter by tag.
CAT_BUILDING = "Build"
CAT_TECH     = "Tech"
CAT_EVENT    = "Event"
CAT_DIPLO    = "Diplo"
CAT_COMBAT   = "Combat"
CAT_COLONY   = "Colony"


# Hard cap on retained entries. Older entries fall off the front. Sized
# to comfortably hold ~20 turns of activity.
MAX_ENTRIES = 250


class TurnLog:
    """List of ``(turn, category, text)`` tuples, newest at the end."""

    __slots__ = ("entries",)

    def __init__(self):
        self.entries: list[tuple[int, str, str]] = []

    def add(self, turn: int, category: str, text: str) -> None:
        self.entries.append((int(turn), category, text))
        if len(self.entries) > MAX_ENTRIES:
            # Drop the oldest excess in one slice rather than per-append.
            self.entries = self.entries[-MAX_ENTRIES:]

    def for_turn(self, turn: int) -> list[tuple[str, str]]:
        return [(c, t) for (tn, c, t) in self.entries if tn == turn]

    def last_turn(self) -> int | None:
        return self.entries[-1][0] if self.entries else None

    def recent(self, n: int = 20) -> list[tuple[int, str, str]]:
        return self.entries[-n:]


def log(game, category: str, text: str) -> None:
    """Push an entry to ``game.turn_log`` at the current galaxy turn.

    No-ops silently if the log isn't initialised (e.g. very early
    startup) so callers don't need to guard.
    """
    tl = getattr(game, "turn_log", None)
    if tl is None:
        return
    turn = getattr(getattr(game, "galaxy", None), "turn", 0)
    tl.add(turn, category, text)

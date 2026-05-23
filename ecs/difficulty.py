"""Difficulty level constants and the AI output multiplier table.

Kept in its own module so both the AI loop (ecs.ai) and the economy
(ecs.economy) can import without creating a cycle.
"""
from __future__ import annotations


DIFFICULTIES = ["easy", "normal", "hard", "impossible"]
DEFAULT_DIFFICULTY = "normal"


AI_OUTPUT_MULT = {
    "easy":       0.5,
    "normal":     1.0,
    "hard":       1.75,
    "impossible": 3.0,
}


def ai_output_multiplier(difficulty: str) -> float:
    return AI_OUTPUT_MULT.get(difficulty, 1.0)

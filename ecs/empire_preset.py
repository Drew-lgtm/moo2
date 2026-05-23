from dataclasses import dataclass


@dataclass
class EmpirePreset:
    """Player-chosen empire identity, used to seed the human empire at
    generation time. AI empires fill the remaining slots with random
    color/race picks that avoid this preset's choices."""
    name: str
    color: str
    race: str

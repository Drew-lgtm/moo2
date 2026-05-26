from dataclasses import dataclass, field


@dataclass
class EmpirePreset:
    """Player-chosen empire identity, used to seed the human empire at
    generation time. AI empires fill the remaining slots with random
    color/race picks that avoid this preset's choices.

    ``custom_traits`` is populated when ``race == "Custom"`` (see
    ``ecs.races.CUSTOM_RACE_NAME``) — a list of trait keys the player
    point-bought during empire setup.
    """
    name: str
    color: str
    race: str
    custom_traits: list[str] = field(default_factory=list)

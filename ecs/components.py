from dataclasses import dataclass, field

@dataclass
class Position:
    x: int
    y: int

@dataclass
class StarVisual:
    image_name: str
    size: int
    star_class: str

@dataclass
class Name:
    value: str

@dataclass
class Owner:
    empire_id: int

@dataclass
class Planet:
    id: int
    planet_type: str
    size: str
    colonizable: bool


@dataclass
class Population:
    """Per-planet population, attached to colonized planets only.

    current grows up to max each turn (pop_growth_tick). Per-turn output
    scales by current/max — see ecs.economy.planet_output.
    """
    current: int
    max: int


@dataclass
class BuildState:
    """Per-planet construction state.

    Attached to colonized planets. While current_project is set, the
    planet's BC accumulates as progress instead of flowing to the empire.
    Completed projects' flat effects (bc, research) apply to the planet's
    output every subsequent turn.
    """
    current_project: str | None = None
    progress: int = 0
    completed: list[str] = field(default_factory=list)

@dataclass
class Orbiting:
    star_entity: int

@dataclass
class Empire:
    id: int
    name: str
    race_type: str
    color: str
    tech_level: int
    home_star_id: int
    bc: int = 0
    research_points: int = 0
    is_player: bool = False
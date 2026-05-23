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

    Total pop = farmers + workers + scientists, all of which sum to
    current. current grows toward max each turn following a logistic
    curve (pop_growth_tick); growth_progress carries the fractional
    pop between ticks. New pop units default to workers; starvation
    removes workers first.
    """
    current: int
    max: int
    growth_progress: float = 0.0
    farmers: int = 0
    workers: int = 0
    scientists: int = 0


@dataclass
class BuildState:
    """Per-planet construction state.

    `current_project` is the active build. `queue` holds items behind it,
    in order. When a project completes, the next queued item becomes
    current and any progress overflow carries over.
    """
    current_project: str | None = None
    progress: int = 0
    completed: list[str] = field(default_factory=list)
    queue: list[str] = field(default_factory=list)

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
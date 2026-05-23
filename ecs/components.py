from dataclasses import dataclass

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
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
    planet_type: str
    size: str
    colonizable: bool

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
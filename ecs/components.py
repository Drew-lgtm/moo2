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
    def __init__(self, star_entity):
        self.star_entity = star_entity

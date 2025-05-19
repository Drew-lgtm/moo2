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
    type: str      # Planet environment
    size: str
    colonizable: bool
@dataclass
class Orbiting:
    star_id: int

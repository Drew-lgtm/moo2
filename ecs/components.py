from dataclasses import dataclass

@dataclass
class Position:
    x: int
    y: int

@dataclass
class Name:
    value: str

@dataclass
class Owner:
    empire_id: int

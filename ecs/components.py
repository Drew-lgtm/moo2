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
class StarRef:
    """Attached to a star entity; carries the matching ``stars.id`` row.

    Lets game logic that has an Orbiting.star_entity look up the star's
    DB id (e.g. for `ships.current_star_id`).
    """
    db_id: int

@dataclass
class Name:
    value: str

@dataclass
class Owner:
    empire_id: int

@dataclass
class Planet:
    """A planet orbiting a star.

    MOO2-style descriptors beyond bare type/size:

    - ``richness`` mineral abundance (Ultra Poor / Poor / Abundant /
      Rich / Ultra Rich) multiplies industry output.
    - ``gravity`` (Low / Normal / Heavy) penalises all per-pop output
      for races not adapted to it. We don't model adaptation traits
      yet so Low/Heavy are flat penalties.
    - ``special`` is a list of feature keys (artifacts, gem_deposits,
      gold_veins, ...). Effects in ``ecs.economy.planet_output``.
    """
    id: int
    planet_type: str
    size: str
    colonizable: bool
    richness: str = "Abundant"
    gravity: str = "Normal"
    special: list[str] = field(default_factory=list)


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

    `autobuild` is empty when manual, or the name of a personality
    whose ``build_priority`` queues the next building on this colony
    when nothing else is being built. Set via the Colony screen; AI
    empires use their own ``_ai_queue_building`` path and don't read
    this flag.
    """
    current_project: str | None = None
    progress: int = 0
    completed: list[str] = field(default_factory=list)
    queue: list[str] = field(default_factory=list)
    autobuild: str = ""

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
    personality: str = "balanced"
    # Comma-separated trait keys for custom races. Empty for preset races
    # (their traits live in ecs.races.RACES[race_type]).
    custom_traits: str = ""


@dataclass
class TechState:
    """Per-empire tech research state.

    Attached to the same entity as the Empire component. `current_target`
    is the tech id whose progress accumulates from per-turn research.
    Completed techs land in `unlocked`.

    `locked_out` holds techs the empire passed on at a tier choice
    (MOO2-style — picking one alternative excludes the others). Locked
    techs can still be acquired by stealing from a rival who picked
    differently.
    """
    empire_id: int
    current_target: str | None = None
    progress: int = 0
    unlocked: list[str] = field(default_factory=list)
    locked_out: list[str] = field(default_factory=list)


@dataclass
class Ship:
    """One ship of a given class. Persisted in the ``ships`` table.

    The loadout fields (armor / shield / weapon / weapon_count /
    specials) are **frozen at construction** — the empire's best
    research at build time. Researching a better tech afterwards does
    NOT retrofit existing hulls; only newly-built ships get the upgrade.
    """
    id: int
    ship_class: str
    armor_tech: str | None = None
    shield_tech: str | None = None
    weapon_tech: str | None = None
    weapon_count: int = 0
    specials: list[str] = field(default_factory=list)


@dataclass
class ShipOwner:
    empire_id: int


@dataclass
class ShipAt:
    """Ship is currently parked at a star (the orbiting star entity)."""
    star_entity: int


@dataclass
class ShipInTransit:
    """Ship is moving between stars; ``turns_remaining`` decrements each
    turn until arrival, at which point ShipAt(dest_star_entity) replaces
    this component. ``total_turns`` is the original duration so we can
    animate progress = 1 - turns_remaining / total_turns.
    """
    from_star_entity: int
    to_star_entity: int
    turns_remaining: int
    total_turns: int = 0
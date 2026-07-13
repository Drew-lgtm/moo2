"""Tests for manual ship designs + weapon mounts."""
import pytest

from ecs.ship_design import (
    MOUNTS, mount_attack_mult, mount_space_mult,
    design_space_used, hull_space_budget, stats_from_ship,
)
from ecs.components import Ship


# ---- mounts ------------------------------------------------------------

def test_mount_multipliers():
    assert mount_attack_mult("normal") == 1.0
    assert mount_attack_mult("heavy") == 2.0
    assert mount_attack_mult("point_defense") == 0.5
    # unknown mount falls back to normal
    assert mount_attack_mult("bogus") == 1.0


def test_heavy_mount_doubles_attack_and_space():
    # laser_cannons: attack 1, size 1.
    normal = design_space_used(weapon_tech="laser_cannons", weapon_count=2,
                               weapon_mount="normal")
    heavy = design_space_used(weapon_tech="laser_cannons", weapon_count=2,
                              weapon_mount="heavy")
    assert heavy == normal * 2  # 2 vs 4


def test_stats_from_ship_applies_mount():
    def ship(mount):
        return Ship(id=1, ship_class="cruiser", weapon_tech="phasors",
                    weapon_count=3, weapon_mount=mount, specials=[])
    # phasors attack 2 × 3 = 6 baseline; heavy → 12; PD → 3.
    assert stats_from_ship(ship("normal"))["attack"] == 6
    assert stats_from_ship(ship("heavy"))["attack"] == 12
    assert stats_from_ship(ship("point_defense"))["attack"] == 3


# ---- space budget ------------------------------------------------------

def test_hull_budget_base():
    # frigate space is 6 in the catalog.
    assert hull_space_budget("frigate") == 6


def test_molecular_compression_expands_budget():
    base = hull_space_budget("cruiser")
    boosted = hull_space_budget("cruiser", unlocked={"molecular_compression"})
    assert boosted == base + int(round(base * 0.20))


# ---- ShipDesign dataclass ---------------------------------------------

def test_design_stats_and_fit():
    from ecs.designs import ShipDesign
    d = ShipDesign(id=1, empire_id=1, name="Gunboat", ship_class="frigate",
                   weapon_tech="laser_cannons", weapon_count=3,
                   armor_tech="heavy_armor")
    st = d.stats()
    assert st["attack"] == 3          # laser 1 × 3, normal mount
    assert st["hull"] >= 2            # frigate base + heavy_armor 2
    assert d.fits()                   # 3(weapons)+1(armor)=4 <= 6


def test_design_overbudget_does_not_fit():
    from ecs.designs import ShipDesign
    # 10 heavy-mount lasers on a frigate (budget 6) → 20 space, no fit.
    d = ShipDesign(id=1, empire_id=1, name="Overloaded", ship_class="frigate",
                   weapon_tech="laser_cannons", weapon_count=10,
                   weapon_mount="heavy")
    assert not d.fits()


# ---- manager CRUD (in-memory) -----------------------------------------

def test_manager_create_and_filter():
    from ecs.designs import ShipDesignManager
    m = ShipDesignManager()
    a = m.create(1, "A", "frigate", weapon_tech="laser_cannons", weapon_count=2)
    m.create(1, "B", "cruiser")
    m.create(2, "C", "frigate")  # different empire
    assert len(m.for_empire(1)) == 2
    assert len(m.for_empire_class(1, "frigate")) == 1
    m.delete(a.id)
    assert len(m.for_empire(1)) == 1


# ---- save / load roundtrip (isolated temp DB) -------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def test_design_backed_build_spawns_frozen_loadout(temp_db):
    """End-to-end: a design:<id> build order that completes must spawn a
    ship carrying the design's exact loadout + mount, not the auto one."""
    from types import SimpleNamespace
    from ecs.entity_manager import EntityManager
    from ecs.component_manager import ComponentManager
    from ecs.components import (
        Empire, TechState, Owner, Planet, Population, BuildState,
        Orbiting, StarRef, Ship, ShipOwner,
    )
    from ecs.designs import ShipDesignManager, design_project_id
    from ecs.economy import production_tick

    from ecs.db import get_connection, insert_star, insert_empire
    # Seed the parent rows the ships FK requires (stars, empires).
    with get_connection() as conn:
        insert_star(conn, "Sol", 0, 0, "G", "star.png", 30)      # id 1
        insert_empire(conn, "P", "Humans", "blue", 1, 0)          # id 1
        conn.commit()

    em = EntityManager()
    cm = ComponentManager()

    # Empire 1 with no useful weapon tech unlocked — so if the spawn
    # used the AUTO path it would build an unarmed cruiser. The design
    # explicitly fits phasors on a heavy mount, proving it's honoured.
    emp_e = em.create_entity()
    cm.add_component(emp_e, Empire(id=1, name="P", race_type="Humans",
                                   color="blue", tech_level=0, home_star_id=1,
                                   bc=0, research_points=0, is_player=True))
    cm.add_component(emp_e, TechState(empire_id=1, unlocked=[]))

    star_e = em.create_entity()
    cm.add_component(star_e, StarRef(db_id=1))

    planet_e = em.create_entity()
    cm.add_component(planet_e, Planet(id=1, planet_type="Terran", size="Medium",
                                      colonizable=True))
    cm.add_component(planet_e, Owner(empire_id=1))
    cm.add_component(planet_e, Population(current=4, max=12, workers=4))
    cm.add_component(planet_e, Orbiting(star_entity=star_e))

    designs = ShipDesignManager()
    design = designs.create(1, "Heavy Phasor Cruiser", "cruiser",
                            weapon_tech="phasors", weapon_count=2,
                            weapon_mount="heavy", armor_tech="heavy_armor")

    # Build order already funded past the hull cost.
    cm.add_component(planet_e, BuildState(
        current_project=design_project_id(design.id), progress=1000))

    game = SimpleNamespace(component_mgr=cm, entity_mgr=em,
                           ship_designs=designs, leaders=None,
                           galaxy=SimpleNamespace(difficulty="normal"),
                           diplomacy=None, turn_log=None)

    production_tick(game, new_turn=2)

    ships = [(e, s) for e, s in cm.get_all(Ship)]
    assert len(ships) == 1, "exactly one ship should have spawned"
    _e, ship = ships[0]
    assert ship.ship_class == "cruiser"
    assert ship.weapon_tech == "phasors"
    assert ship.weapon_count == 2
    assert ship.weapon_mount == "heavy"
    assert ship.armor_tech == "heavy_armor"


def test_manager_save_load_roundtrip(temp_db):
    from ecs.designs import ShipDesignManager
    m = ShipDesignManager()
    m.create(1, "Laser Frigate", "frigate", weapon_tech="laser_cannons",
             weapon_count=3, weapon_mount="normal", armor_tech="heavy_armor",
             specials=["inertial_stabilizer"])
    m.create(1, "Heavy Cruiser", "cruiser", weapon_tech="phasors",
             weapon_count=2, weapon_mount="heavy")
    m.save()

    m2 = ShipDesignManager()
    m2.load()
    designs = sorted(m2.for_empire(1), key=lambda d: d.id)
    assert len(designs) == 2
    assert designs[0].name == "Laser Frigate"
    assert designs[0].weapon_mount == "normal"
    assert designs[0].specials == ["inertial_stabilizer"]
    assert designs[1].weapon_mount == "heavy"
    # ids preserved so build-order references survive load.
    assert {d.id for d in designs} == {1, 2}

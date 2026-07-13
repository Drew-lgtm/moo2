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

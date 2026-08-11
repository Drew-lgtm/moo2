"""Endgame scoring: the Military pillar values what a fleet actually IS
— hull + fitted equipment, scaled by crew veterancy — not just hull count."""
import pytest
from types import SimpleNamespace

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import (
    Empire, TechState, Owner, Planet, Population, BuildState, Orbiting,
    Ship, ShipOwner,
)
from ecs.endgame import score_breakdown, SCORE_OUTCOME_BONUS
from ecs.veterancy import RANK_THRESHOLDS


def _game(ships=()):
    em = EntityManager(); cm = ComponentManager()
    cm.add_component(em.create_entity(),
                     Empire(id=1, name="P", race_type="Humans", color="blue",
                            tech_level=0, home_star_id=1, bc=0,
                            research_points=0, is_player=True))
    for s in ships:
        e = em.create_entity()
        cm.add_component(e, s)
        cm.add_component(e, ShipOwner(empire_id=1))
    return SimpleNamespace(component_mgr=cm, entity_mgr=em,
                           galaxy=SimpleNamespace(turn=100))


def _military(game):
    return score_breakdown(game, 1)["pillars"]["Military"]


def test_equipped_ship_outscores_a_bare_hull():
    bare = Ship(id=1, ship_class="cruiser")
    kitted = Ship(id=2, ship_class="cruiser", weapon_tech="laser_cannons",
                  weapon_count=6, armor_tech="heavy_armor",
                  shield_tech="class_i_shield")
    assert _military(_game([kitted])) > _military(_game([bare]))


def test_veteran_crew_raises_fleet_worth():
    green = Ship(id=1, ship_class="battleship", experience=0)
    elite = Ship(id=2, ship_class="battleship",
                 experience=RANK_THRESHOLDS[4])       # Ultra-Elite
    assert _military(_game([elite])) > _military(_game([green]))


def test_missile_armament_counts_toward_worth():
    beam = Ship(id=1, ship_class="cruiser", weapon_tech="laser_cannons",
                weapon_count=4)
    missile = Ship(id=2, ship_class="cruiser", weapon_tech="merculite_missile",
                   weapon_count=4)
    # Both are real armament — the missile boat must not score as unarmed.
    assert _military(_game([missile])) > _military(_game([Ship(id=3, ship_class="cruiser")]))
    assert _military(_game([beam])) > 0


def test_no_fleet_scores_zero_military():
    assert _military(_game([])) == 0


def test_breakdown_shape_is_stable():
    """The game-over screen renders these exact pillar keys."""
    bd = score_breakdown(_game([Ship(id=1, ship_class="frigate")]), 1)
    assert set(bd["pillars"]) == {"Population", "Colonies", "Tech",
                                  "Buildings", "Economy", "Military"}
    assert set(bd["counts"]) == set(bd["pillars"])
    assert bd["raw"] == sum(bd["pillars"].values())


def test_antaran_victory_scores_highest():
    """Destroying Antares is the hardest path, so it must pay best."""
    assert SCORE_OUTCOME_BONUS["Antaran"] > SCORE_OUTCOME_BONUS["Conquest"]
    assert SCORE_OUTCOME_BONUS["Conquest"] > SCORE_OUTCOME_BONUS["Diplomatic"]
    assert SCORE_OUTCOME_BONUS["Diplomatic"] > SCORE_OUTCOME_BONUS["Defeat"]

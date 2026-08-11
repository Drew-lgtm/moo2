"""Tactical scene lifecycle — the battle object is cleared the moment a
fight finishes, so anything that runs after a win check must not touch it."""
import os
import random
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from ecs.tactical import TacticalShip, TacticalBattle


def _ship(eid, col, **kw):
    kw.setdefault("hull", 10)
    kw.setdefault("max_hull", 10)
    kw.setdefault("attack", 5)
    return TacticalShip(entity_id=eid, empire_id=eid, ship_class="cruiser",
                        name=f"S{eid}", col=col, row=0, **kw)


def _scene_with_finished_battle():
    """A tactical scene whose battle is already down to one side, so the
    next win check finalises (and clears self.battle)."""
    pygame.init()
    from ecs.scenes.tactical import TacticalScene
    scene = TacticalScene.__new__(TacticalScene)   # skip heavy __init__
    b = TacticalBattle(star_entity=1, star_name="X", turn=1, player_id=1)
    winner = _ship(1, 0)
    loser = _ship(2, 1)
    loser.destroyed = True                          # only empire 1 remains
    b.ships = [winner, loser]
    scene.battle = b
    scene.game = SimpleNamespace(
        component_mgr=None, entity_mgr=None, scenes=SimpleNamespace(
            replace=lambda *_a, **_k: None),
        pending_engagements=None, pending_combat_reports=None,
        space_monsters=[], diplomacy=None)
    scene._rng = random.Random(1)
    scene._log_lines = []
    scene._log = lambda msg: scene._log_lines.append(msg)
    scene.selected = None
    # Stub the heavy finaliser: mirror only the part that matters here —
    # a finished battle clears the reference.
    def _fake_finalise():
        scene.battle = None
    scene._finalise = _fake_finalise
    scene._player_empire_id = lambda: 1
    return scene


def test_end_turn_survives_battle_finishing_mid_call():
    """REGRESSION: _finalise() clears self.battle, and _end_turn used to
    dereference it immediately afterwards -> AttributeError crash."""
    scene = _scene_with_finished_battle()
    scene._end_turn()          # must not raise
    assert scene.battle is None


def test_draw_is_safe_after_the_battle_is_cleared():
    scene = _scene_with_finished_battle()
    scene._end_turn()
    surf = pygame.Surface((800, 600))
    scene.draw(surf)           # guarded no-op, must not raise

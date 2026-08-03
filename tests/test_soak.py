"""Multi-game soak test — hardening.

Boots several full games with different settings and runs each deep
enough to exercise the late-game systems (space-monster spawns/kills,
AI government adoption, ship veterancy accumulation, missile/PD combat,
Antaran raids), with a mid-run save/load, asserting cross-cutting
invariants hold. Catches integration crashes and state leaks that
single-feature unit tests miss.

Kept lean (small galaxies, raids pulled early) so it stays affordable in
the suite while still covering the composed turn loop end to end.
"""
from types import SimpleNamespace

import pytest

pygame = pytest.importorskip("pygame")


@pytest.fixture
def soak_env(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "soak.db")
    import ecs.antaran as antaran
    monkeypatch.setattr(antaran, "RAID_FIRST_TURN", 5)
    monkeypatch.setattr(antaran, "RAID_INTERVAL", 6)
    monkeypatch.setattr(antaran, "RAID_DURATION", 2)
    # Start from a clean display — an earlier test (e.g. the integration
    # test) may have left one open, and a second SCALED|FULLSCREEN
    # set_mode in the same process otherwise fails to create a renderer.
    pygame.display.quit()
    pygame.init()
    yield
    pygame.display.quit()


def _real_empire_ids(cm):
    from ecs.components import Empire
    from ecs.monsters import is_pseudo_empire
    return {e.id for _x, e in cm.get_all(Empire) if not is_pseudo_empire(e.id)}


def _check_invariants(game, expected_real_empires):
    from ecs.components import Empire, Ship, ShipOwner, Owner
    cm = game.component_mgr
    # Real empires never vanish spuriously (they can be eliminated, but the
    # Empire component persists); pseudo-empires are excluded.
    real = _real_empire_ids(cm)
    assert real == expected_real_empires, (real, expected_real_empires)
    # Every ShipOwner points at a ship that still exists (no orphans).
    for e, _o in cm.get_all(ShipOwner):
        assert cm.get_component(e, Ship) is not None
    # Every owned planet has a real (or pseudo, but not phantom) owner id.
    all_ids = {e.id for _x, e in cm.get_all(Empire)}
    for _pe, owner in cm.get_all(Owner):
        assert owner.empire_id in all_ids
    # Ship experience never negative.
    for _e, s in cm.get_all(Ship):
        assert (s.experience or 0) >= 0


@pytest.mark.parametrize("num_stars,num_empires,turns", [
    (14, 3, 18),   # more empires -> more combat/diplomacy churn
    (20, 2, 22),   # bigger map, deeper run -> multiple raids + monster life
])
def test_full_game_soak(soak_env, num_stars, num_empires, turns):
    from ecs.game import Game
    player = SimpleNamespace(name="Player", race="Humans", color="blue",
                             custom_traits=[])
    game = Game(num_stars=num_stars)
    game.start_new_game(player_empire=player, num_empires=num_empires)
    expected = _real_empire_ids(game.component_mgr)
    assert game.player_empire() is not None

    half = turns // 2
    for _ in range(half):
        game.advance_turn()
    _check_invariants(game, expected)

    # Mid-run save/load must round-trip cleanly and keep playing.
    game.load_game()
    assert _real_empire_ids(game.component_mgr) == expected
    _check_invariants(game, expected)

    for _ in range(turns - half):
        game.advance_turn()
    _check_invariants(game, expected)
    assert game.galaxy.turn == turns + 1

"""Full-stack smoke test: boot a real game and run the whole turn loop.

The per-feature tests build minimal hand-made worlds. This one boots the
actual Game (galaxy generation, AI, production, fleet movement, combat,
Antaran raids, events, diplomacy — every registered turn callback) over
a real generated galaxy for a stretch of turns, then reloads from the DB
and continues. It's the guard that the systems compose without crashing
and that a save round-trips — the kind of break a unit test misses.

Antaran raids are pulled early so that path is exercised in a short run.
Outcomes of combat/raids are stochastic, so the assertions cover only
invariants (no crash, turn advances, state round-trips), never who wins.
"""
from types import SimpleNamespace

import pytest

pygame = pytest.importorskip("pygame")


@pytest.fixture
def game_db(tmp_path, monkeypatch):
    """Isolate the on-disk galaxy DB and pull Antaran raids early (but not
    relentlessly) so the raid path runs within a short game."""
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "smoke.db")
    import ecs.antaran as antaran
    monkeypatch.setattr(antaran, "RAID_FIRST_TURN", 5)
    monkeypatch.setattr(antaran, "RAID_INTERVAL", 8)
    monkeypatch.setattr(antaran, "RAID_DURATION", 2)
    pygame.init()
    yield


def _boot():
    from ecs.game import Game
    player = SimpleNamespace(name="Player", race="Humans", color="blue",
                             custom_traits=[])
    game = Game(num_stars=12)
    game.start_new_game(player_empire=player, num_empires=2)
    return game


def _real_empires(cm):
    """Empires excluding the colony-less pseudo-empires (Antaran raiders,
    space monsters), which are ECS-only and never persisted."""
    from ecs.components import Empire
    from ecs.antaran import is_antaran
    from ecs.monsters import is_monster
    return [e for _x, e in cm.get_all(Empire)
            if not is_antaran(e.id) and not is_monster(e.id)]


def test_full_turn_loop_runs_and_reloads(game_db):
    from ecs.components import StarRef
    from ecs.antaran import is_antaran, ANTARAN_EMPIRE_ID

    game = _boot()
    assert game.galaxy.turn == 1
    assert len(game.turn_callbacks) >= 10
    # Boot produced a flagged player empire and two real empires.
    assert game.player_empire() is not None
    assert len(_real_empires(game.component_mgr)) == 2
    # System guardians (space monsters) were seeded on rich systems.
    assert len(game.space_monsters) >= 1

    raid_seen = False
    for _ in range(9):
        game.advance_turn()
        if getattr(game, "antaran_raid", None) is not None:
            raid_seen = True

    # The loop survived every system over many turns.
    assert game.galaxy.turn == 10
    # The Antaran raid path actually fired.
    assert raid_seen
    # Endgame flag is either unset or a well-formed result dict.
    if game.pending_endgame is not None:
        assert game.pending_endgame.get("result") in ("victory", "defeat")

    stars_before = len(list(game.component_mgr.get_all(StarRef)))
    guardians_before = len(game.space_monsters)

    # Reload from the DB (simulates quit + load) and keep playing.
    game.load_game()
    assert len(list(game.component_mgr.get_all(StarRef))) == stars_before
    assert game.galaxy.turn == 10
    # Guardians persist across save/load (killed ones stay dead).
    assert len(game.space_monsters) == guardians_before
    # Real empires round-trip; the transient Antaran pseudo-empire is
    # NEVER persisted, so a fresh load must not resurrect it.
    reloaded = _real_empires(game.component_mgr)
    assert len(reloaded) == 2
    assert not any(is_antaran(e.id)
                   for _x, e in game.component_mgr.get_all(
                       type(reloaded[0])))

    for _ in range(2):
        game.advance_turn()
    assert game.galaxy.turn == 12

"""In-game help overlay (F1): opens over any screen, scrolls, and returns
to wherever it was opened from."""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")


@pytest.fixture
def game(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "help.db")
    pygame.display.quit()
    pygame.init()
    from ecs.game import Game
    from ecs.scenes import GalaxyScene, InfoScene, HelpScene
    player = SimpleNamespace(name="P", race="Humans", color="blue",
                            custom_traits=[])
    g = Game(num_stars=10)
    g.scenes.register("galaxy", GalaxyScene(g))
    g.scenes.register("info", InfoScene(g))
    g.scenes.register("help", HelpScene(g))
    g.start_new_game(player_empire=player, num_empires=2)
    yield g
    pygame.display.quit()


def _f1():
    return pygame.event.Event(pygame.KEYDOWN,
                              {"key": pygame.K_F1, "mod": 0, "unicode": ""})


def _esc():
    return pygame.event.Event(pygame.KEYDOWN,
                              {"key": pygame.K_ESCAPE, "mod": 0, "unicode": ""})


def test_f1_opens_help_from_the_galaxy(game):
    game.scenes.replace("galaxy")
    assert game._handle_shortcut(_f1()) is True
    assert game.scenes.active_name == "help"


def test_help_returns_to_the_screen_it_was_opened_from(game):
    game.scenes.replace("info")
    game._handle_shortcut(_f1())
    game.scenes.active.handle_event(_esc())
    assert game.scenes.active_name == "info"


def test_f1_toggles_help_closed(game):
    game.scenes.replace("galaxy")
    game._handle_shortcut(_f1())
    game._handle_shortcut(_f1())
    assert game.scenes.active_name == "galaxy"


def test_help_opens_from_screens_without_other_shortcuts(game):
    """Help must work everywhere — it's most useful where you're stuck,
    which is often a screen the letter shortcuts don't serve."""
    game.scenes.replace("info")
    assert "saves" not in game._SHORTCUT_SCENES     # a non-shortcut screen
    game.scenes.register("saves", game.scenes._scenes["info"])
    game.scenes.replace("saves")
    assert game._handle_shortcut(_f1()) is True
    assert game.scenes.active_name == "help"


def test_help_renders_and_scrolls(game):
    game.scenes.replace("galaxy")
    game.open_help()
    scene = game.scenes.active
    surf = pygame.Surface((game.screen_width, game.screen_height))
    scene.draw(surf)
    assert scene._content_height > 0
    assert scene._max_scroll() > 0, "help should be scrollable"
    scene.scroll_offset = 200
    scene.draw(surf)                 # must not raise


def test_help_covers_the_opaque_systems(game):
    """The overlay exists to explain what the screens don't show."""
    from ecs.scenes.help import HELP_SECTIONS
    body = " ".join(h + " " + " ".join(ls) for h, ls in HELP_SECTIONS).lower()
    for topic in ("morale", "point-defense", "upkeep", "veteran",
                  "guardian", "blockade", "antares", "queue"):
        assert topic in body, f"help should mention {topic}"

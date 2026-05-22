"""Scene base class and a tiny manager that drives the active scene.

Each game state (main menu, galaxy view, system view, pause) is a Scene.
The Game owns a SceneManager; the main loop forwards events/update/draw
to the active scene and lets it request transitions by returning a name
from `next_scene` or calling `game.scenes.replace(name)` directly.
"""
from __future__ import annotations


class Scene:
    """Base class for game scenes.

    Subclasses override the methods they care about. `game` is the
    shared Game instance, set when the scene is registered.
    """

    def __init__(self, game):
        self.game = game

    def on_enter(self):
        pass

    def on_exit(self):
        pass

    def handle_event(self, event):
        pass

    def update(self, dt):
        pass

    def draw(self, screen):
        pass


class SceneManager:
    def __init__(self):
        self._scenes = {}
        self._active_name = None

    def register(self, name, scene):
        self._scenes[name] = scene

    @property
    def active(self):
        return self._scenes.get(self._active_name)

    @property
    def active_name(self):
        return self._active_name

    def replace(self, name):
        if name == self._active_name:
            return
        if self._active_name is not None:
            self._scenes[self._active_name].on_exit()
        self._active_name = name
        self._scenes[name].on_enter()

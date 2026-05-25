from ecs.scene import Scene
from ecs.system_view import SystemView


class SystemViewScene(Scene):
    """Wraps the SystemView widget. Entered when a star is clicked."""

    def __init__(self, game):
        super().__init__(game)
        self.view: SystemView | None = None

    def on_enter(self):
        star_id = getattr(self.game, "selected_star", None)
        if star_id is None:
            self.game.scenes.replace("galaxy")
            return
        self.view = SystemView(
            self.game.screen, self.game.component_mgr, star_id,
            logical_size=(self.game.screen_width, self.game.screen_height),
        )

    def on_exit(self):
        # Drop the SystemView widget but keep game.selected_star — we
        # might be bouncing through ColonyScene and back, and clearing
        # it here would make on_enter redirect to galaxy.
        self.view = None

    def handle_event(self, event):
        if self.view is None:
            return
        self.view.handle_event(event)
        # Planet click → open that planet's Colony scene. selected_planet
        # carries the entity id so ColonyScene.on_enter can pick it up.
        if self.view.pending_planet_click is not None:
            self.game.selected_planet = self.view.pending_planet_click
            self.view.pending_planet_click = None
            self.game.scenes.replace("colony")
            return
        if not self.view.is_open:
            self.game.scenes.replace("galaxy")

    def draw(self, screen):
        if self.view is not None:
            self.view.draw(self.game.font)

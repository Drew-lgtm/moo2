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
        self.view = SystemView(self.game.screen, self.game.component_mgr, star_id)

    def on_exit(self):
        self.view = None
        self.game.selected_star = None

    def handle_event(self, event):
        if self.view is None:
            return
        self.view.handle_event(event)
        if not self.view.is_open:
            self.game.scenes.replace("galaxy")

    def draw(self, screen):
        if self.view is not None:
            self.view.draw(self.game.font)

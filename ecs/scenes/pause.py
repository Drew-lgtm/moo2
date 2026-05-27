from ecs.scene import Scene
from ecs.menu import Menu


class PauseScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.menu = Menu(
            game.screen,
            ["Resume", "Save Game", "Load Game", "Quit to Menu"],
            title="Paused",
        )

    def handle_event(self, event):
        result = self.menu.handle_event(event)
        if result == "Resume":
            self.game.scenes.replace("galaxy")
        elif result == "Save Game":
            self.game.save_screen_mode = "save"
            self.game.save_screen_return = "pause"
            self.game.scenes.replace("saves")
        elif result == "Load Game":
            self.game.save_screen_mode = "load"
            self.game.save_screen_return = "pause"
            self.game.scenes.replace("saves")
        elif result == "Quit to Menu":
            self.game.scenes.replace("main_menu")

    def draw(self, screen):
        self.menu.draw()

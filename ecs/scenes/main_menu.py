from ecs.scene import Scene
from ecs.menu import Menu


class MainMenuScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.menu = Menu(game.screen, ["New Game", "Load Game", "Quit"], title="Main Menu")

    def handle_event(self, event):
        result = self.menu.handle_event(event)
        if result == "New Game":
            self.game.scenes.replace("empire_setup")
        elif result == "Load Game":
            self.game.load_game()
            self.game.scenes.replace("galaxy")
        elif result == "Quit":
            self.game.quit()

    def draw(self, screen):
        self.menu.draw()

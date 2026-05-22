import pygame

from ecs.scene import Scene
from ecs.menu import Menu
from ecs.save_manager import save_to_slot, load_from_slot


SLOT_KEYS = {
    pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
    pygame.K_4: 4, pygame.K_5: 5, pygame.K_6: 6,
    pygame.K_7: 7, pygame.K_8: 8, pygame.K_9: 9,
}


class PauseScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.menu = Menu(
            game.screen,
            ["Resume", "Save Game", "Load Game", "Quit to Menu"],
            title="Paused",
        )
        # When set to "save" or "load", the next 1-9 key press selects a slot.
        self.pending_slot_action: str | None = None

    def on_enter(self):
        self.pending_slot_action = None

    def handle_event(self, event):
        result = self.menu.handle_event(event)
        if result == "Resume":
            self.game.scenes.replace("galaxy")
            return
        if result == "Save Game":
            self.pending_slot_action = "save"
            return
        if result == "Load Game":
            self.pending_slot_action = "load"
            return
        if result == "Quit to Menu":
            self.game.scenes.replace("main_menu")
            return

        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_ESCAPE:
            if self.pending_slot_action:
                self.pending_slot_action = None
            else:
                self.game.scenes.replace("galaxy")
            return

        if event.key in SLOT_KEYS and self.pending_slot_action:
            slot = SLOT_KEYS[event.key]
            if self.pending_slot_action == "save":
                save_to_slot(slot)
            elif self.pending_slot_action == "load":
                if load_from_slot(slot):
                    self.game.load_game()
                    self.pending_slot_action = None
                    self.game.scenes.replace("galaxy")
                    return
            self.pending_slot_action = None

    def draw(self, screen):
        self.menu.draw()
        if self.pending_slot_action:
            hint = self.game.font.render(
                f"Press 1-9 to choose a {self.pending_slot_action} slot (Esc to cancel)",
                True, (255, 255, 0),
            )
            rect = hint.get_rect(center=(self.game.screen_width // 2, self.game.screen_height - 40))
            screen.blit(hint, rect)

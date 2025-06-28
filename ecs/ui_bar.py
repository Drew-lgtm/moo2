import pygame
from pathlib import Path
from assets.loader import load_image

UI_PATH = Path("assets/ui")

class UIButton:
    def __init__(self, name, x, y, callback, image_normal, image_pressed):
        self.name = name
        self.image_normal = image_normal
        self.image_pressed = image_pressed
        self.image = self.image_normal
        self.rect = self.image.get_rect(topleft=(x, y))
        self.callback = callback
        self.is_pressed = False

    def draw(self, screen):
        screen.blit(self.image, self.rect)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.is_pressed = True
                self.image = self.image_pressed
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_pressed and self.rect.collidepoint(event.pos):
                self.callback()
            self.is_pressed = False
            self.image = self.image_normal

class BottomUIBar:
    def __init__(self, screen_width, screen_height):
        button_names = ["colonies", "planets", "leaders", "races", "info", "turn"]
        num_buttons = len(button_names)
        self.buttons = []


# redo:  fix buttons scaling
        button_width = screen_width // num_buttons
        button_height = screen_height // 6
        y = screen_height - button_height

        for i, name in enumerate(button_names):
            x = i * button_width

            image_normal = pygame.transform.smoothscale(
                load_image(f"ui/{name}.png"), (button_width, button_height)
            )
            image_pressed = pygame.transform.smoothscale(
                load_image(f"ui/{name}_pressed.png"), (button_width, button_height)
            )

            button = UIButton(
                name=name,
                x=x,
                y=y,
                callback=lambda n=name: print(f"{n} clicked"),
                image_normal=image_normal,
                image_pressed=image_pressed
            )
            self.buttons.append(button)

    def draw(self, screen):
        for btn in self.buttons:
            btn.draw(screen)

    def handle_event(self, event):
        for btn in self.buttons:
            btn.handle_event(event)

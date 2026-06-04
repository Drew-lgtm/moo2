"""Bottom UI bar with text-labelled buttons.

The previous version blit large PNG images per button — the rendered
text on them was unreadable. This rewrite draws solid rectangles with
labels, with hover/press states. ``BAR_HEIGHT`` is the single source of
truth for how much vertical space the bar occupies, so the galaxy view,
panel scenes, and star generation can all reserve the right play-area
height.
"""
from __future__ import annotations

import pygame


class BottomUIBar:
    BAR_HEIGHT = 56

    BG_COLOR        = (18, 20, 32)
    SEPARATOR_COLOR = (90, 100, 140)
    BTN_FILL        = (40, 44, 64)
    BTN_FILL_HOVER  = (60, 66, 96)
    BTN_FILL_PRESS  = (90, 100, 140)
    BTN_BORDER      = (140, 150, 200)
    BTN_TEXT        = (240, 240, 240)

    BUTTON_NAMES = ["colonies", "planets", "research", "diplomacy", "leaders", "races", "espionage", "info", "turn"]
    LABELS = {
        "colonies": "Colonies",
        "planets":  "Planets",
        "research": "Research",
        "diplomacy": "Diplomacy",
        "leaders":  "Leaders",
        "races":    "Races",
        "espionage": "Espionage",
        "info":     "Info",
        "turn":     "Turn",
    }

    def __init__(self, screen_width, screen_height):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.bar_rect = pygame.Rect(
            0, screen_height - self.BAR_HEIGHT,
            screen_width, self.BAR_HEIGHT,
        )
        self.font = pygame.font.SysFont("Arial", 18, bold=True)

        button_width = screen_width // len(self.BUTTON_NAMES)
        self.buttons: list[UIButton] = []
        self._by_name: dict[str, UIButton] = {}
        for i, name in enumerate(self.BUTTON_NAMES):
            rect = pygame.Rect(
                i * button_width, screen_height - self.BAR_HEIGHT,
                button_width, self.BAR_HEIGHT,
            )
            label = self.LABELS.get(name, name.capitalize())
            button = UIButton(name, rect, label, self._noop_for(name), self.font)
            self.buttons.append(button)
            self._by_name[name] = button

    @staticmethod
    def _noop_for(name: str):
        return lambda n=name: print(f"{n} clicked (no handler bound)")

    def set_callback(self, name: str, fn):
        if name not in self._by_name:
            raise KeyError(f"unknown UI button: {name}")
        self._by_name[name].callback = fn if fn is not None else self._noop_for(name)

    def draw(self, screen):
        pygame.draw.rect(screen, self.BG_COLOR, self.bar_rect)
        # Top edge divider so the bar reads as separate from the map.
        pygame.draw.line(
            screen, self.SEPARATOR_COLOR,
            (self.bar_rect.left, self.bar_rect.top),
            (self.bar_rect.right, self.bar_rect.top), 2,
        )
        for btn in self.buttons:
            btn.draw(screen)

    def handle_event(self, event):
        for btn in self.buttons:
            btn.handle_event(event)

    def tooltip_at(self, pos):
        """Right-click on a bar button -> what it does. Returned as
        ``list[str]`` ready for ``Tooltip.show``; callers add it to
        their own ``tooltip_at`` result."""
        from ecs.tooltips import button_tooltip
        for btn in self.buttons:
            if btn.rect.collidepoint(pos):
                return button_tooltip(btn.name)
        return None


class UIButton:
    def __init__(self, name, rect, label, callback, font):
        self.name = name
        self.rect = rect
        self.label = label
        self.callback = callback
        self.font = font
        self.is_hovered = False
        self.is_pressed = False

    def draw(self, screen):
        if self.is_pressed:
            fill = BottomUIBar.BTN_FILL_PRESS
        elif self.is_hovered:
            fill = BottomUIBar.BTN_FILL_HOVER
        else:
            fill = BottomUIBar.BTN_FILL
        # Inset 1px so adjacent button borders don't double-up.
        inner = self.rect.inflate(-2, -2)
        pygame.draw.rect(screen, fill, inner)
        pygame.draw.rect(screen, BottomUIBar.BTN_BORDER, inner, 1)
        text = self.font.render(self.label, True, BottomUIBar.BTN_TEXT)
        screen.blit(text, text.get_rect(center=self.rect.center))

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.is_hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.is_pressed = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_pressed and self.rect.collidepoint(event.pos):
                self.callback()
            self.is_pressed = False

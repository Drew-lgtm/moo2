"""Central hover/inspect tooltip widget.

One instance lives on ``game.tooltip``. Scenes don't draw their own
tooltip box — they expose ``tooltip_at(pos) -> list[str] | None`` and
the main loop in ``Game.run`` calls it on right-click. The widget
auto-sizes to its content and clamps to the screen so it never falls
off-edge.

Per scene, the recipe is:

    def tooltip_at(self, pos):
        for rect, payload in self._tooltip_hits:
            if rect.collidepoint(pos):
                return payload  # list[str]
        return None

A left-click, scene change, or Esc hides the tooltip (handled in
``Game.run``). Right-click on empty space also hides.
"""
from __future__ import annotations

import pygame


BG_COLOR = (20, 24, 40, 235)
BORDER_COLOR = (180, 200, 240)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 190, 210)


class Tooltip:
    PAD_X = 10
    PAD_Y = 8
    LINE_GAP = 2

    def __init__(self):
        self.visible = False
        self.lines: list[str] = []
        self.anchor: tuple[int, int] = (0, 0)
        self._title_font: pygame.font.Font | None = None
        self._body_font: pygame.font.Font | None = None

    def show(self, lines, pos):
        """Display ``lines`` near ``pos``. The first line renders as the
        title (yellow); the rest as body text. Lines starting with
        ``"hint:"`` are dimmed."""
        self.lines = [str(l) for l in lines if l is not None]
        self.anchor = pos
        self.visible = bool(self.lines)

    def hide(self):
        self.visible = False

    def _fonts(self):
        if self._title_font is None:
            self._title_font = pygame.font.SysFont("Arial", 15, bold=True)
            self._body_font = pygame.font.SysFont("Arial", 13, bold=True)
        return self._title_font, self._body_font

    def draw(self, screen):
        if not self.visible or not self.lines:
            return
        title_font, body_font = self._fonts()

        surfs = []
        for i, raw in enumerate(self.lines):
            text = raw
            color = TEXT_COLOR
            if i == 0:
                font = title_font
                color = TITLE_COLOR
            else:
                font = body_font
                if text.startswith("hint:"):
                    text = text[len("hint:"):].strip()
                    color = HINT_COLOR
            surfs.append(font.render(text, True, color))

        w = max((s.get_width() for s in surfs), default=120) + self.PAD_X * 2
        h = sum(s.get_height() for s in surfs) + self.LINE_GAP * (len(surfs) - 1) + self.PAD_Y * 2

        x, y = self.anchor
        x += 14
        y += 14
        sw, sh = screen.get_size()
        if x + w > sw - 4:
            x = max(4, sw - w - 4)
        if y + h > sh - 4:
            y = max(4, sh - h - 4)

        rect = pygame.Rect(x, y, w, h)
        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill(BG_COLOR)
        screen.blit(bg, rect.topleft)
        pygame.draw.rect(screen, BORDER_COLOR, rect, 1)

        cy = y + self.PAD_Y
        for s in surfs:
            screen.blit(s, (x + self.PAD_X, cy))
            cy += s.get_height() + self.LINE_GAP

"""Combat report screen.

Pops up after a turn in which the player fought one or more battles
(``game.pending_combat_reports``). Pages through each engagement,
showing both sides — empire, colour, attack power, ships committed by
class, losses, survivors — and who held the field.

Esc / Continue dismisses the current report; after the last one the
player returns to the galaxy. Cleared on exit so it only shows once.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire, Name
from ecs.palette import empire_color
from ecs.ships import SHIPS


BG_COLOR = (8, 10, 22, 245)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
LOSS_COLOR = (240, 120, 120)
WIN_COLOR = (140, 230, 150)
BTN_BG = (50, 56, 84)
BTN_BORDER = (160, 170, 210)


class CombatReportScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 30, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 20, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 14, bold=True)
        self.reports: list = []
        self.index = 0
        self._buttons: list[tuple[str, pygame.Rect]] = []

    def on_enter(self):
        self.reports = list(getattr(self.game, "pending_combat_reports", None) or [])
        self.index = 0

    def on_exit(self):
        self.game.pending_combat_reports = None

    # ------------------------------------------------------------------ helpers

    def _empire(self, eid):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.id == eid:
                return emp
        return None

    def _star_name(self, star_entity) -> str:
        n = self.game.component_mgr.get_component(star_entity, Name)
        return n.value if n else "deep space"

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
            self._advance()
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for action, rect in self._buttons:
                if rect.collidepoint(event.pos):
                    self._advance()
                    return

    def _advance(self):
        self.index += 1
        if self.index >= len(self.reports):
            self.game.scenes.replace("galaxy")

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._buttons = []

        if not self.reports or self.index >= len(self.reports):
            self.game.scenes.replace("galaxy")
            return

        report = self.reports[self.index]
        cx = sw // 2

        title = f"Battle at {self._star_name(report['star_entity'])}"
        screen.blit(self.title_font.render(title, True, TITLE_COLOR),
                    self.title_font.render(title, True, TITLE_COLOR).get_rect(center=(cx, 56)))
        sub = f"Turn {report['turn']}   ·   Engagement {self.index + 1} of {len(self.reports)}"
        screen.blit(self.small_font.render(sub, True, HINT_COLOR),
                    self.small_font.render(sub, True, HINT_COLOR).get_rect(center=(cx, 88)))

        # Two side panels.
        sides = report["sides"]
        panel_w = 360
        gap = 40
        total_w = panel_w * min(2, len(sides)) + gap * (min(2, len(sides)) - 1)
        start_x = cx - total_w // 2
        y = 130
        for i, side in enumerate(sides[:2]):
            x = start_x + i * (panel_w + gap)
            self._draw_side(screen, side, x, y, panel_w)

        # Outcome banner — whoever kept the most ships held the field.
        outcome_y = y + 300
        self._draw_outcome(screen, report, cx, outcome_y)

        # Continue button.
        label = "Continue" if self.index == len(self.reports) - 1 else "Next Battle"
        rect = pygame.Rect(cx - 95, sh - 70, 190, 40)
        pygame.draw.rect(screen, BTN_BG, rect)
        pygame.draw.rect(screen, BTN_BORDER, rect, 1)
        surf = self.body_font.render(label, True, TEXT_COLOR)
        screen.blit(surf, surf.get_rect(center=rect.center))
        self._buttons.append(("advance", rect))

    def _draw_side(self, screen, side, x, y, w):
        emp = self._empire(side["empire_id"])
        name = emp.name if emp else f"Empire {side['empire_id']}"
        color = empire_color(emp.color) if emp else (200, 200, 200)
        is_player = emp is not None and emp.is_player

        h = 280
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(screen, (16, 18, 30), rect)
        pygame.draw.rect(screen, color, rect, 2)

        ix = x + 16
        iy = y + 14
        # Header: colour bar + name (+ "you").
        pygame.draw.rect(screen, color, pygame.Rect(ix, iy + 2, 8, 22))
        label = name + ("  (you)" if is_player else "")
        screen.blit(self.header_font.render(label, True, TEXT_COLOR), (ix + 16, iy))
        iy += 36

        screen.blit(self.body_font.render(f"Attack power: {side['attack']}", True, (210, 210, 230)), (ix, iy))
        iy += 28

        # Ships committed, by class.
        screen.blit(self.small_font.render("Fleet:", True, HINT_COLOR), (ix, iy))
        iy += 22
        if side["ships_before"]:
            for cls, n in sorted(side["ships_before"].items()):
                cls_name = SHIPS.get(cls, {}).get("name", cls.replace("_", " ").title())
                screen.blit(self.small_font.render(f"  {n} x {cls_name}", True, TEXT_COLOR), (ix, iy))
                iy += 20
        else:
            screen.blit(self.small_font.render("  (none)", True, HINT_COLOR), (ix, iy))
            iy += 20

        iy += 8
        lost = side["lost"]
        remaining = side["remaining"]
        screen.blit(self.body_font.render(f"Lost: {lost}", True, LOSS_COLOR if lost else HINT_COLOR), (ix, iy))
        iy += 26
        screen.blit(self.body_font.render(f"Survived: {remaining}", True,
                    WIN_COLOR if remaining else LOSS_COLOR), (ix, iy))

    def _draw_outcome(self, screen, report, cx, y):
        sides = report["sides"]
        # Winner = most ships remaining; ties / mutual wipeout = stalemate.
        sides_sorted = sorted(sides, key=lambda s: s["remaining"], reverse=True)
        top = sides_sorted[0]
        if top["remaining"] == 0:
            text, color = "Mutual annihilation — no ships survived.", LOSS_COLOR
        elif len(sides_sorted) > 1 and sides_sorted[1]["remaining"] == top["remaining"]:
            text, color = "Stalemate — both fleets hold the field.", HINT_COLOR
        else:
            emp = self._empire(top["empire_id"])
            name = emp.name if emp else f"Empire {top['empire_id']}"
            won = emp is not None and emp.is_player
            text = f"{name} held the field."
            color = WIN_COLOR if won else LOSS_COLOR
        surf = self.header_font.render(text, True, color)
        screen.blit(surf, surf.get_rect(center=(cx, y)))

"""Galactic Council screen.

Shown automatically when the council convenes (every COUNCIL_INTERVAL
turns). Displays the two candidates, the vote tally, and the outcome:

- Player elected  → Victory; button returns to the main menu.
- An AI elected   → Accept (defeat → main menu) or Defy (war with the
  emperor + supporters, resume the game).
- No winner       → Continue back to the galaxy.

Reads ``game.pending_council`` (set by Game.advance_turn) and clears it
on exit so it only shows once per session.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire
from ecs.palette import empire_color
from ecs.council import VICTORY_FRACTION, defy_emperor


BG_COLOR = (8, 10, 22, 245)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
WIN_COLOR = (140, 230, 150)
LOSE_COLOR = (240, 130, 130)
BTN_BG = (50, 56, 84)
BTN_BORDER = (160, 170, 210)


class CouncilScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 34, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 22, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 14, bold=True)
        self.result: dict | None = None
        self._buttons: list[tuple[str, pygame.Rect]] = []

    def on_enter(self):
        self.result = getattr(self.game, "pending_council", None)

    def on_exit(self):
        # Consume the pending council so it doesn't re-trigger.
        self.game.pending_council = None

    # ------------------------------------------------------------------ helpers

    def _empire(self, eid):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.id == eid:
                return emp
        return None

    def _name(self, eid):
        emp = self._empire(eid)
        return emp.name if emp else f"Empire {eid}"

    def _player_id(self):
        p = self.game.player_empire()
        return p.id if p else None

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for action, rect in self._buttons:
                if rect.collidepoint(event.pos):
                    self._do(action)
                    return
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # Esc = continue / accept depending on outcome.
            self.game.scenes.replace("galaxy")

    def _do(self, action: str):
        if action == "continue":
            self.game.scenes.replace("galaxy")
        elif action == "defy":
            defy_emperor(self.game, self.result or {})
            self.game.scenes.replace("galaxy")
        elif action in ("victory", "defeat"):
            # End the game — back to the main menu.
            self.game.scenes.replace("main_menu")

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._buttons = []

        cx = sw // 2
        screen.blit(self.title_font.render("Galactic Council", True, TITLE_COLOR),
                    self.title_font.render("Galactic Council", True, TITLE_COLOR).get_rect(center=(cx, 60)))

        result = self.result
        if not result or not result.get("candidates"):
            screen.blit(self.body_font.render(
                "Too few empires remain to convene a council.", True, HINT_COLOR),
                self.body_font.render("x", True, HINT_COLOR).get_rect(center=(cx, 160)))
            self._add_button(screen, "Continue", "continue", cx, 240)
            return

        # Candidate vote bars.
        total = max(1, result["total"])
        y = 130
        for cand in result["candidates"]:
            votes = result["votes"].get(cand, 0)
            pct = votes / total
            emp = self._empire(cand)
            color = empire_color(emp.color) if emp else (200, 200, 200)
            # Label.
            label = self.header_font.render(
                f"{self._name(cand)} — {votes} votes ({pct*100:.0f}%)", True, TEXT_COLOR)
            screen.blit(label, (cx - 300, y))
            y += 28
            # Bar.
            bar_bg = pygame.Rect(cx - 300, y, 600, 24)
            pygame.draw.rect(screen, (30, 34, 50), bar_bg)
            pygame.draw.rect(screen, color, pygame.Rect(cx - 300, y, int(600 * pct), 24))
            pygame.draw.rect(screen, BTN_BORDER, bar_bg, 1)
            y += 40

        # Threshold marker text.
        screen.blit(self.small_font.render(
            f"A candidate needs {int(VICTORY_FRACTION*100)}% of the total vote to be elected Emperor.",
            True, HINT_COLOR), (cx - 300, y))
        y += 40

        winner = result.get("winner")
        player_id = self._player_id()

        if winner is None:
            screen.blit(self.header_font.render(
                "No Emperor was elected this session.", True, TEXT_COLOR),
                (cx - 300, y))
            self._add_button(screen, "Continue", "continue", cx, y + 50)
        elif winner == player_id:
            screen.blit(self.header_font.render(
                "You have been elected Galactic Emperor!", True, WIN_COLOR),
                (cx - 300, y))
            screen.blit(self.body_font.render(
                "Diplomatic Victory.", True, WIN_COLOR), (cx - 300, y + 30))
            self._add_button(screen, "Glorious!", "victory", cx, y + 70)
        else:
            screen.blit(self.header_font.render(
                f"{self._name(winner)} has been elected Galactic Emperor.", True, LOSE_COLOR),
                (cx - 300, y))
            screen.blit(self.body_font.render(
                "Accept their rule, or defy the council and fight on?", True, TEXT_COLOR),
                (cx - 300, y + 30))
            self._add_button(screen, "Accept Defeat", "defeat", cx - 110, y + 80)
            self._add_button(screen, "Defy!", "defy", cx + 110, y + 80)

    def _add_button(self, screen, label, action, cx, cy, w=190, h=40):
        rect = pygame.Rect(cx - w // 2, cy, w, h)
        pygame.draw.rect(screen, BTN_BG, rect)
        pygame.draw.rect(screen, BTN_BORDER, rect, 1)
        surf = self.body_font.render(label, True, TEXT_COLOR)
        screen.blit(surf, surf.get_rect(center=rect.center))
        self._buttons.append((action, rect))

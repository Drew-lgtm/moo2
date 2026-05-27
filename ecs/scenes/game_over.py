"""Game-over screen: outcome banner + persistent Hall of Fame.

Reached when a victory/defeat condition fires (conquest, elimination,
or a Galactic Council decision). Records the winning empire to the
hall_of_fame table on entry, then shows the result from the player's
perspective and the all-time leaderboard (name, race, outcome, turn,
score). Any click / Esc returns to the main menu.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire
from ecs.endgame import record_result
from ecs.db import get_hall_of_fame


BG_COLOR = (8, 10, 22, 250)
TITLE_WIN = (140, 230, 150)
TITLE_LOSE = (240, 120, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
HEADER_COLOR = (255, 230, 120)
ROW_BG = (24, 28, 42)
ROW_BG_ALT = (30, 34, 50)


class GameOverScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 48, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 22, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 15, bold=True)
        self._recorded = False
        self._hof: list = []

    def on_enter(self):
        result = getattr(self.game, "pending_endgame", None) or {}
        # Record the winner once, then load the leaderboard.
        if not self._recorded and result:
            winner_id = result.get("winner_id")
            mode = result.get("mode", "Conquest")
            if winner_id is not None:
                record_result(self.game, winner_id, mode)
            self._recorded = True
        self._hof = list(get_hall_of_fame(12))

    def on_exit(self):
        self.game.pending_endgame = None
        self._recorded = False

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN or (
            event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
        ):
            self.game.scenes.replace("main_menu")

    # ------------------------------------------------------------------ draw

    def _empire(self, eid):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.id == eid:
                return emp
        return None

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        cx = sw // 2

        result = getattr(self.game, "pending_endgame", None) or {}
        won = result.get("result") == "victory"
        mode = result.get("mode", "")
        title = "VICTORY" if won else "DEFEAT"
        color = TITLE_WIN if won else TITLE_LOSE
        screen.blit(self.title_font.render(title, True, color),
                    self.title_font.render(title, True, color).get_rect(center=(cx, 70)))

        winner = self._empire(result.get("winner_id"))
        if won:
            sub = f"{mode} Victory — you rule the galaxy."
        elif winner is not None:
            sub = f"{mode} Victory for {winner.name} ({winner.race_type}). You have fallen."
        else:
            sub = "Your empire has been wiped out."
        screen.blit(self.header_font.render(sub, True, TEXT_COLOR),
                    self.header_font.render(sub, True, TEXT_COLOR).get_rect(center=(cx, 118)))

        # Hall of Fame table.
        screen.blit(self.header_font.render("Hall of Fame", True, HEADER_COLOR), (cx - 320, 170))
        cols = [("#", cx - 320), ("Empire", cx - 290), ("Race", cx - 90),
                ("Outcome", cx + 70), ("Turn", cx + 210), ("Score", cx + 280)]
        for label, x in cols:
            screen.blit(self.small_font.render(label, True, HINT_COLOR), (x, 200))

        y = 224
        for i, row in enumerate(self._hof):
            rect = pygame.Rect(cx - 326, y, 660, 26)
            pygame.draw.rect(screen, ROW_BG_ALT if i % 2 else ROW_BG, rect)
            cells = [
                (str(i + 1), cx - 320),
                (str(row["empire_name"])[:18], cx - 290),
                (str(row["race"])[:14], cx - 90),
                (str(row["outcome"]), cx + 70),
                (str(row["turn"]), cx + 210),
                (str(row["score"]), cx + 280),
            ]
            for text, x in cells:
                screen.blit(self.small_font.render(text, True, TEXT_COLOR), (x, y + 4))
            y += 28

        prompt = self.body_font.render("Click anywhere to return to the main menu.", True, HINT_COLOR)
        screen.blit(prompt, prompt.get_rect(center=(cx, sh - 40)))

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
from ecs.endgame import (
    record_result, score_breakdown, final_score, SCORE_OUTCOME_BONUS,
    _turn_speed_multiplier,
)
from ecs.db import get_hall_of_fame, get_hall_of_fame_pillar_records


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
        self._pillar_records: dict = {}

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
        self._pillar_records = get_hall_of_fame_pillar_records()

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

    def _draw_score_panel(self, screen, won: bool, mode: str, cx: int):
        """Two-column-ish breakdown: pillar name, count, raw points.
        Below: outcome bonus + turn-speed multiplier => final score."""
        player = self.game.player_empire()
        if player is None:
            return
        # The score the player is being recorded with: Conquest /
        # Diplomatic on a win, "Defeat" on a loss.
        perspective = mode if won else "Defeat"
        bd = score_breakdown(self.game, player.id)
        pillars = bd["pillars"]
        counts = bd["counts"]
        raw = bd["raw"]
        bonus = SCORE_OUTCOME_BONUS.get(perspective, 1.0)
        speed = _turn_speed_multiplier(getattr(self.game.galaxy, "turn", 0))
        final = int(round(raw * bonus * speed))

        screen.blit(self.header_font.render("Your Score", True, HEADER_COLOR),
                    (cx - 320, 160))

        x_name, x_count, x_pts = cx - 320, cx - 130, cx + 60
        screen.blit(self.small_font.render("Pillar", True, HINT_COLOR), (x_name, 188))
        screen.blit(self.small_font.render("Count", True, HINT_COLOR), (x_count, 188))
        screen.blit(self.small_font.render("Points", True, HINT_COLOR), (x_pts, 188))

        y = 210
        for name, pts in pillars.items():
            screen.blit(self.body_font.render(name, True, TEXT_COLOR), (x_name, y))
            screen.blit(self.body_font.render(str(counts.get(name, "")), True, TEXT_COLOR),
                        (x_count, y))
            screen.blit(self.body_font.render(str(pts), True, TEXT_COLOR),
                        (x_pts, y))
            y += 22

        # Totals + multipliers.
        y += 4
        line = pygame.Rect(x_name, y, 660, 1)
        pygame.draw.rect(screen, HINT_COLOR, line)
        y += 6
        screen.blit(self.body_font.render("Raw score", True, HINT_COLOR), (x_name, y))
        screen.blit(self.body_font.render(str(raw), True, TEXT_COLOR), (x_pts, y))
        y += 22
        screen.blit(self.body_font.render(
            f"× {perspective} bonus", True, HINT_COLOR), (x_name, y))
        screen.blit(self.body_font.render(f"× {bonus:.2f}", True, TEXT_COLOR), (x_pts, y))
        y += 22
        screen.blit(self.body_font.render(
            f"× speed (turn {getattr(self.game.galaxy, 'turn', 0)})",
            True, HINT_COLOR), (x_name, y))
        screen.blit(self.body_font.render(f"× {speed:.2f}", True, TEXT_COLOR), (x_pts, y))
        y += 24
        final_color = TITLE_WIN if won else TEXT_COLOR
        screen.blit(self.header_font.render("Final Score", True, HEADER_COLOR), (x_name, y))
        screen.blit(self.header_font.render(str(final), True, final_color), (x_pts, y))

    def _draw_pillar_records(self, screen, cx, sh):
        """All-time best per pillar across every recorded run. Sits as a
        narrow side column to the right of the Hall of Fame table."""
        if not self._pillar_records:
            return
        x = cx + 360
        y = 380
        screen.blit(self.header_font.render("Records", True, HEADER_COLOR), (x, y))
        y = 410
        screen.blit(self.small_font.render("Pillar", True, HINT_COLOR), (x, y))
        screen.blit(self.small_font.render("Best", True, HINT_COLOR), (x + 110, y))
        y = 434
        for i, label in enumerate(("Population", "Colonies", "Tech",
                                   "Buildings", "Economy", "Military")):
            rec = self._pillar_records.get(label)
            if rec is None:
                continue
            value, empire_name, race = rec
            rect = pygame.Rect(x - 6, y, 240, 26)
            pygame.draw.rect(screen, ROW_BG_ALT if i % 2 else ROW_BG, rect)
            screen.blit(self.small_font.render(label, True, TEXT_COLOR), (x, y + 4))
            screen.blit(self.small_font.render(str(value), True, TEXT_COLOR),
                        (x + 110, y + 4))
            holder = f"{str(empire_name)[:10]} ({str(race)[:8]})"
            screen.blit(self.small_font.render(holder, True, HINT_COLOR),
                        (x + 160, y + 4))
            y += 28

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
        if won and mode == "Antaran":
            sub = "Antares lies in ruins. The galaxy is free — and yours."
        elif won:
            sub = f"{mode} Victory — you rule the galaxy."
        elif winner is not None:
            sub = f"{mode} Victory for {winner.name} ({winner.race_type}). You have fallen."
        else:
            sub = "Your empire has been wiped out."
        screen.blit(self.header_font.render(sub, True, TEXT_COLOR),
                    self.header_font.render(sub, True, TEXT_COLOR).get_rect(center=(cx, 118)))

        # Player's score breakdown — surfaces the six pillars so they
        # can see what drove the number. Recorded into the Hall of Fame
        # with the same maths via final_score().
        self._draw_score_panel(screen, won, mode, cx)

        # Hall of Fame table.
        screen.blit(self.header_font.render("Hall of Fame", True, HEADER_COLOR), (cx - 320, 380))
        cols = [("#", cx - 320), ("Empire", cx - 290), ("Race", cx - 90),
                ("Outcome", cx + 70), ("Turn", cx + 210), ("Score", cx + 280)]
        for label, x in cols:
            screen.blit(self.small_font.render(label, True, HINT_COLOR), (x, 410))

        y = 434
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

        self._draw_pillar_records(screen, cx, sh)

        prompt = self.body_font.render("Click anywhere to return to the main menu.", True, HINT_COLOR)
        screen.blit(prompt, prompt.get_rect(center=(cx, sh - 40)))

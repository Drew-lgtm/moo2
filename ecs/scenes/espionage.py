"""Espionage screen — train spies and assign missions.

Left: a status line (treasury, spy pool, defenders, tech bonuses) and a
row per rival empire with Steal-Tech / Sabotage allocation steppers.
Right: a rolling log of recent espionage events.

Spies not assigned to an offensive mission defend the home empire
(counter-intelligence). Training a spy costs BC. All changes persist
immediately. Esc / Close returns to the galaxy view.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire, TechState
from ecs.palette import empire_color
from ecs.espionage import SPY_COST, MISSIONS
from ecs.techs import (
    empire_spy_offense, empire_spy_defense, empire_has_stealth, empire_has_mind_scan,
)
from ecs.db import get_connection, update_empire_economy


BG_COLOR = (10, 12, 24, 235)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
ROW_BG = (24, 28, 42)
BTN_BG = (50, 56, 84)
BTN_BORDER = (150, 160, 200)
GOOD_COLOR = (150, 220, 160)
BAD_COLOR = (240, 130, 130)


class EspionageScene(Scene):
    # Five missions now share a row; height bumped so the steppers can
    # wrap onto two short rows under the empire name.
    ROW_H = 86

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 15, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 13, bold=True)

        self.banner: str = ""
        self.banner_color = HINT_COLOR
        # (action, payload, rect) refreshed each draw for hit testing.
        self._hits: list[tuple[str, object, pygame.Rect]] = []
        self._close_rect = pygame.Rect(0, 0, 0, 0)

    def on_enter(self):
        self._close_rect = pygame.Rect(self.game.screen_width - 100, 16, 80, 32)

    # ------------------------------------------------------------------ helpers

    def _player(self):
        return self.game.player_empire()

    def _player_unlocked(self) -> set[str]:
        player = self._player()
        if player is None:
            return set()
        for _eid, tech in self.game.component_mgr.get_all(TechState):
            if tech.empire_id == player.id:
                return set(tech.unlocked)
        return set()

    def _others(self):
        player = self._player()
        pid = player.id if player else None
        return [emp for _eid, emp in self.game.component_mgr.get_all(Empire)
                if emp.id != pid]

    # ------------------------------------------------------------------ input

    def tooltip_at(self, pos):
        """Train button + each empire's mission steppers."""
        player = self._player()
        esp = self.game.espionage
        if player is None or esp is None:
            return None
        for action, payload, rect in self._hits:
            if not rect.collidepoint(pos):
                continue
            if action == "train":
                return [
                    "Train Spy",
                    f"hint: {SPY_COST} BC for one operative",
                    "hint: untasked spies defend the empire (counter-intel)",
                ]
            if action == "auto_train":
                target = esp.auto_train_target_for(player.id)
                return [
                    "Auto-train target",
                    f"hint: currently {target}",
                    f"hint: each turn while under target, 1 spy "
                    f"auto-trained for {SPY_COST} BC",
                    "hint: set-and-forget replacement for fallen spies",
                ]
            if action == "mission":
                target_id, mission, delta = payload
                from ecs.tooltips import spy_mission_tooltip
                lines = spy_mission_tooltip(mission)
                cur = esp.mission_count(player.id, target_id, mission)
                lines.append(f"hint: currently {cur} assigned vs target")
                if delta > 0:
                    lines.append("hint: click to add one")
                else:
                    lines.append("hint: click to remove one")
                return lines
        return None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.scenes.replace("galaxy")
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if self._close_rect.collidepoint(event.pos):
            self.game.scenes.replace("galaxy")
            return
        for action, payload, rect in self._hits:
            if rect.collidepoint(event.pos):
                self._do(action, payload)
                return

    def _do(self, action, payload):
        esp = self.game.espionage
        player = self._player()
        if esp is None or player is None:
            return
        if action == "train":
            if player.bc >= SPY_COST:
                player.bc -= SPY_COST
                esp.train_spy(player.id)
                with get_connection() as conn:
                    update_empire_economy(conn, player.id, player.bc, player.research_points)
                    conn.commit()
                esp.save()
                self.banner, self.banner_color = "Trained a new spy.", GOOD_COLOR
            else:
                self.banner, self.banner_color = "Not enough BC to train a spy.", BAD_COLOR
        elif action == "mission":
            target_id, mission, delta = payload
            before = esp.mission_count(player.id, target_id, mission)
            esp.adjust_mission(player.id, target_id, mission, delta)
            after = esp.mission_count(player.id, target_id, mission)
            if delta > 0 and after == before:
                self.banner, self.banner_color = "No free spies to assign.", BAD_COLOR
            else:
                self.banner = ""
            esp.save()
        elif action == "auto_train":
            delta = payload
            cur = esp.auto_train_target_for(player.id)
            esp.set_auto_train_target(player.id, cur + delta)
            esp.save()
            self.banner = ""

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._hits = []

        screen.blit(self.title_font.render("Espionage", True, TITLE_COLOR), (20, 12))

        esp = self.game.espionage
        player = self._player()
        if esp is None or player is None:
            screen.blit(self.header_font.render("No player empire.", True, HINT_COLOR), (20, 60))
            self._draw_close(screen)
            return

        unlocked = self._player_unlocked()
        spies = esp.spy_count(player.id)
        defenders = esp.defense_count(player.id)
        off = empire_spy_offense(unlocked)
        deff = empire_spy_defense(unlocked)

        # Status line.
        status = (f"BC: {player.bc}    Spies: {spies}    Defending: {defenders}"
                  f"    Spy Skill +{off}    Security +{deff}")
        screen.blit(self.header_font.render(status, True, TEXT_COLOR), (20, 48))
        tags = []
        if empire_has_stealth(unlocked):
            tags.append("Stealth Suit")
        if empire_has_mind_scan(unlocked):
            tags.append("Mind Scan")
        if tags:
            screen.blit(self.small_font.render("Active: " + ", ".join(tags), True, GOOD_COLOR),
                        (20, 72))

        # Train button + auto-train stepper. The Train Spy button is the
        # one-shot. Below it sits a small "Auto-train: N" picker that
        # tells the espionage tick to keep replacing fallen spies up to
        # this count each turn (costs SPY_COST each, paid automatically).
        train_rect = pygame.Rect(sw - 230, 48, 200, 30)
        afford = player.bc >= SPY_COST
        pygame.draw.rect(screen, BTN_BG if afford else (40, 40, 52), train_rect)
        pygame.draw.rect(screen, BTN_BORDER, train_rect, 1)
        tcolor = TEXT_COLOR if afford else (130, 130, 150)
        tlabel = self.body_font.render(f"Train Spy  ({SPY_COST} BC)", True, tcolor)
        screen.blit(tlabel, tlabel.get_rect(center=train_rect.center))
        self._hits.append(("train", None, train_rect))

        # Auto-train stepper, sitting directly under the train button.
        at_target = esp.auto_train_target_for(player.id)
        at_y = train_rect.bottom + 6
        at_label = self.small_font.render(
            f"Auto-train target:  {at_target}", True,
            TEXT_COLOR if at_target > 0 else HINT_COLOR,
        )
        screen.blit(at_label, (train_rect.x, at_y))
        # Two steppers, right side of the row.
        bx = train_rect.right - 60
        minus = self._stepper(screen, bx, at_y - 2, "-")
        plus  = self._stepper(screen, bx + 30, at_y - 2, "+")
        self._hits.append(("auto_train", -1, minus))
        self._hits.append(("auto_train", +1, plus))

        # Banner.
        if self.banner:
            screen.blit(self.body_font.render(self.banner, True, self.banner_color), (20, 96))

        # Rival rows on the left; log panel on the right.
        left_w = int(sw * 0.62)
        self._draw_rows(screen, player, esp, left_w)
        self._draw_log(screen, esp, left_w + 20, sw - 20)

        self._draw_close(screen)
        hint = self.small_font.render(
            "Assign spies to Steal Tech or Sabotage. Unassigned spies defend you.   Esc returns.",
            True, HINT_COLOR)
        screen.blit(hint, (20, sh - hint.get_height() - 12))

    def _draw_rows(self, screen, player, esp, right_edge):
        top = 124
        y = top
        # Three missions on row 1, two on row 2 — keeps cell width
        # roughly equal so the labels don't overlap.
        ROWS = [
            (("steal",       "Steal"),
             ("sabotage",    "Sabotage"),
             ("assassinate", "Assassin")),
            (("incite",      "Incite"),
             ("frame",       "Frame"),
             ("hide",        "Hide")),
        ]
        for emp in self._others():
            rect = pygame.Rect(20, y, right_edge - 40, self.ROW_H - 8)
            pygame.draw.rect(screen, ROW_BG, rect)
            pygame.draw.rect(screen, empire_color(emp.color),
                             pygame.Rect(rect.x + 6, rect.y + 6, 16, rect.height - 12))
            name = self.body_font.render(f"{emp.name}  ({emp.race_type})", True, TEXT_COLOR)
            screen.blit(name, (rect.x + 32, rect.y + 6))

            for row_idx, row in enumerate(ROWS):
                mx = rect.x + 32
                my = rect.y + 30 + row_idx * 26
                for mission, label in row:
                    count = esp.mission_count(player.id, emp.id, mission)
                    lbl = self.small_font.render(label, True, HINT_COLOR)
                    screen.blit(lbl, (mx, my))
                    bx = mx + 70
                    minus = self._stepper(screen, bx, my - 2, "-")
                    cnt = self.body_font.render(str(count), True, TEXT_COLOR)
                    screen.blit(cnt, cnt.get_rect(center=(bx + 36, my + 7)))
                    plus = self._stepper(screen, bx + 54, my - 2, "+")
                    self._hits.append(("mission", (emp.id, mission, -1), minus))
                    self._hits.append(("mission", (emp.id, mission, +1), plus))
                    mx = bx + 100
            y += self.ROW_H
            if y > self.game.screen_height - 80:
                break

    def _stepper(self, screen, x, y, sign):
        rect = pygame.Rect(x, y, 22, 22)
        pygame.draw.rect(screen, BTN_BG, rect)
        pygame.draw.rect(screen, BTN_BORDER, rect, 1)
        s = self.body_font.render(sign, True, TEXT_COLOR)
        screen.blit(s, s.get_rect(center=rect.center))
        return rect

    def _draw_log(self, screen, esp, x0, x1):
        screen.blit(self.header_font.render("Intelligence Reports", True, TITLE_COLOR), (x0, 100))
        y = 126
        width = x1 - x0
        for line in reversed(esp.log[-16:]):
            for chunk in self._wrap(line, width):
                screen.blit(self.small_font.render(chunk, True, TEXT_COLOR), (x0, y))
                y += 18
            y += 4
            if y > self.game.screen_height - 60:
                break
        if not esp.log:
            screen.blit(self.small_font.render("No reports yet.", True, HINT_COLOR), (x0, y))

    def _wrap(self, text, width):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if self.small_font.size(test)[0] <= width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [text]

    def _draw_close(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

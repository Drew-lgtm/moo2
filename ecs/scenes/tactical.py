"""Tactical hex-grid combat scene.

Picks up a ``TacticalBattle`` from ``game.pending_engagements`` (queued
by the strategic ``combat_tick`` and reached only when the player picks
"Attack" on the Combat Options screen), lets the player drive one
engagement, then applies the result back to the strategic layer and
routes to the next engagement or back to galaxy.

Mechanics:
- Click your own ship to select it (cyan ring).
- Click an in-range empty hex to move (spends movement points).
- Click any enemy ship to fire (one shot per round, range-gated).
- End Turn runs the enemy AI, then advances the round (shields regen).
- Auto hands the rest of the fight to the shared auto-resolver.

Damage obeys the canonical model in ``ecs/battle.py`` — identical to
the auto-resolve and strategic paths.

There is deliberately no Escape-to-forfeit: a committed battle plays to
a decision (MOO2 behaviour). The queue is owned by ``_finalise``.

Layout:
- Hex grid on the left, side panel on the right with selected-ship
  info and the End Turn / Auto buttons.
- Bottom strip shows the combat log (latest first).
"""
from __future__ import annotations

import math
import random
import pygame

from ecs.scene import Scene
from ecs.components import Empire, Name
from ecs.palette import empire_color
from ecs.tactical import (
    TacticalBattle, TacticalShip,
    GRID_COLS, GRID_ROWS, HEX_SIZE, HEX_WIDTH, HEX_V_SPACING,
    hex_to_pixel, pixel_to_hex, hex_distance,
    ai_take_turn,
)


BG_COLOR = (6, 8, 18)
GRID_LINE = (50, 60, 90)
GRID_FILL = (16, 20, 36)
HOVER_FILL = (40, 60, 100)
MOVE_RANGE_FILL = (40, 90, 120, 90)
ATTACK_TARGET_FILL = (130, 50, 50, 90)
SELECT_RING = (90, 220, 220)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (235, 235, 235)
HINT_COLOR = (160, 170, 200)
PANEL_BG = (18, 22, 38)
PANEL_BORDER = (90, 100, 140)
BTN_BG = (50, 56, 84)
BTN_BORDER = (160, 170, 210)
BTN_HOVER = (75, 82, 115)
LOG_BG = (10, 14, 28)


# Hex grid origin on the play area — anchored top-left with margin.
ORIGIN_X = 20
ORIGIN_Y = 70

# Side panel.
PANEL_X = 920
PANEL_W = 260

# Log strip at the bottom of the grid area.
LOG_TOP_Y = 540
LOG_H = 220


class TacticalScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 22, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 14, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 12, bold=True)

        self.battle: TacticalBattle | None = None
        self.selected: TacticalShip | None = None
        self.log_lines: list[str] = []
        self._rng = random.Random()
        self._buttons: list[tuple[str, pygame.Rect]] = []

    # --------------------------------------------------------------- lifecycle

    def on_enter(self):
        queue = getattr(self.game, "pending_engagements", None) or []
        if not queue:
            self.game.scenes.replace("galaxy")
            return
        self.battle = queue[0]
        self.selected = None
        self.log_lines = []
        # Snapshot each side's total attack before anyone dies, for the
        # post-battle combat report.
        self._attack_before = {
            eid: sum(s.attack for s in self.battle.ships_for(eid))
            for eid in self.battle.empires_present()
        }
        self._log(f"Engagement at {self.battle.star_name} — round 1")

    def on_exit(self):
        # NOTE: the queue is owned exclusively by ``_finalise`` — do NOT
        # pop it here. on_exit fires on every scene transition (including
        # a legitimate finalise route), so popping here would double-pop,
        # and transiently leaving the scene would forfeit the battle.
        return

    # --------------------------------------------------------------- helpers

    def _player_empire_id(self) -> int:
        return self.battle.player_id if self.battle else -1

    def _log(self, line: str):
        self.log_lines.append(line)
        if len(self.log_lines) > 30:
            self.log_lines = self.log_lines[-30:]

    def _empire(self, eid):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.id == eid:
                return emp
        return None

    def _empire_color(self, eid):
        emp = self._empire(eid)
        return empire_color(emp.color) if emp else (200, 200, 200)

    def _ship_radius(self) -> int:
        # Ships fit inside their hex with a bit of breathing room.
        return int(HEX_SIZE * 0.5)

    def _hex_under(self, pos) -> tuple[int, int]:
        return pixel_to_hex(pos[0], pos[1], ORIGIN_X, ORIGIN_Y)

    # --------------------------------------------------------------- input

    def handle_event(self, event):
        if self.battle is None:
            return
        # No Escape-to-forfeit: a committed battle must be resolved via
        # End Turn or Auto. (Leaving the scene would strand the battle
        # at the head of the queue.) Swallow Escape so it's a no-op.
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        for action, rect in self._buttons:
            if rect.collidepoint(event.pos):
                self._do_action(action)
                return
        # Click in the grid area: figure out which hex.
        if event.pos[0] < PANEL_X and event.pos[1] >= ORIGIN_Y and event.pos[1] < LOG_TOP_Y:
            col, row = self._hex_under(event.pos)
            self._click_hex(col, row)

    def _click_hex(self, col, row):
        if not (0 <= col < GRID_COLS and 0 <= row < GRID_ROWS):
            return
        target_ship = self.battle.ship_at(col, row)
        player_id = self._player_empire_id()
        if target_ship is not None and target_ship.empire_id == player_id:
            # Select your own ship.
            self.selected = target_ship
            return
        if self.selected is None or self.selected.empire_id != player_id:
            return
        if target_ship is not None and target_ship.empire_id != player_id:
            result = self.battle.attack(self.selected, target_ship, self._rng)
            if not result["fired"]:
                self._log(f"{self.selected.name}: {result['reason']}.")
                return
            tag = " — DESTROYED!" if result["destroyed"] else ""
            detail_bits = []
            if result["to_shield"]:
                detail_bits.append(f"{result['to_shield']} shield")
            if result["to_hull"]:
                detail_bits.append(f"{result['to_hull']} hull")
            detail = ", ".join(detail_bits) if detail_bits else f"{result['damage']}"
            self._log(f"{self.selected.name} hits {target_ship.name} ({detail}){tag}")
            self._check_winner_and_maybe_finish()
            return
        # Empty hex — try to move.
        if self.battle.move_ship(self.selected, col, row):
            self._log(f"{self.selected.name} moves to ({col}, {row}).")

    def _do_action(self, action: str):
        if action == "end_turn":
            self._end_turn()
        elif action == "auto":
            self._auto_resolve()

    def _end_turn(self):
        # Enemy empires take their AI turn — every empire except the
        # player's, in any order.
        present = self.battle.empires_present()
        player_id = self._player_empire_id()
        for eid in [e for e in present if e != player_id]:
            for line in ai_take_turn(self.battle, eid, self._rng):
                self._log(line)
        self._check_winner_and_maybe_finish()
        if self.battle.finished:
            return
        self.battle.end_round()
        self._log(f"--- Round {self.battle.round} ---")
        # If the round end itself spotted a winner, finalise.
        self._check_winner_and_maybe_finish()

    def _auto_resolve(self):
        """Hand the rest of the fight to the shared auto-resolver
        (``tactical.auto_resolve`` → ``battle.resolve_auto``), so the
        Auto button and a manually-played battle obey the same damage
        model. Then finalise."""
        from ecs.tactical import auto_resolve
        auto_resolve(self.battle, self._rng)
        self._log("Auto-resolved.")
        self._finalise()

    def _check_winner_and_maybe_finish(self):
        empires = self.battle.empires_present()
        if len(empires) <= 1:
            self.battle.finished = True
            self.battle.winner_id = next(iter(empires), None)
            self._finalise()

    def _finalise(self):
        """Apply destroyed ships back to the strategic layer, then exit
        to galaxy (or to the next pending battle)."""
        from ecs.combat import _destroy_ship
        from ecs.db import get_connection, delete_ship
        from ecs.components import Ship
        cm = self.game.component_mgr
        destroyed_entities = self.battle.destroyed_entity_ids()
        if destroyed_entities:
            with get_connection() as conn:
                for ship_entity in destroyed_entities:
                    ship = cm.get_component(ship_entity, Ship)
                    if ship is not None:
                        delete_ship(conn, ship.id)
                conn.commit()
            for ship_entity in destroyed_entities:
                _destroy_ship(self.game, ship_entity)

        # A guardian cleared in this battle must be persisted dead NOW
        # (before any save), not on the next turn's monster_tick.
        from ecs.monsters import reconcile_kills
        reconcile_kills(self.game)

        # Queue a combat-report row so the player gets the same
        # post-battle summary an auto-resolved fight produces.
        from ecs.tactical import battle_report
        report = battle_report(self.battle,
                               getattr(self, "_attack_before", {}))
        existing = getattr(self.game, "pending_combat_reports", None) or []
        self.game.pending_combat_reports = list(existing) + [report]

        # Pop battle off the queue and route — if more engagements are
        # pending, hand back to the decision scene, else to galaxy.
        queue = getattr(self.game, "pending_engagements", None) or []
        if queue and queue[0] is self.battle:
            queue.pop(0)
        if queue:
            self.battle = None  # on_exit won't double-pop
            self.game.scenes.replace("combat_decision")
        else:
            self.game.pending_engagements = None
            self.battle = None
            self.game.scenes.replace("galaxy")

    # --------------------------------------------------------------- draw

    def draw(self, screen):
        screen.fill(BG_COLOR)
        if self.battle is None:
            return
        self._draw_title(screen)
        self._draw_grid(screen)
        self._draw_ships(screen)
        self._draw_side_panel(screen)
        self._draw_log(screen)

    def _draw_title(self, screen):
        b = self.battle
        screen.blit(
            self.title_font.render(
                f"Tactical Combat — {b.star_name} (Round {b.round})",
                True, TITLE_COLOR,
            ),
            (20, 20),
        )

    def _draw_grid(self, screen):
        # Hover hex highlight.
        hover = pygame.mouse.get_pos()
        in_grid = (hover[0] < PANEL_X and hover[1] >= ORIGIN_Y
                   and hover[1] < LOG_TOP_Y)
        hover_hex = self._hex_under(hover) if in_grid else (-1, -1)
        # Player's selected ship: precompute reachable hexes (movement
        # range) and in-firing-range targets (so we can paint them).
        in_move_range: set[tuple[int, int]] = set()
        in_short_range: set[tuple[int, int]] = set()
        in_long_range: set[tuple[int, int]] = set()
        if self.selected is not None and not self.selected.is_station:
            sel = self.selected
            for col in range(GRID_COLS):
                for row in range(GRID_ROWS):
                    d = hex_distance(sel.col, sel.row, col, row)
                    if 0 < d <= sel.moves_left:
                        in_move_range.add((col, row))
                    if 0 < d <= 4:  # SHORT_RANGE
                        in_short_range.add((col, row))
                    elif d <= 8:    # LONG_RANGE
                        in_long_range.add((col, row))
        for col in range(GRID_COLS):
            for row in range(GRID_ROWS):
                center = hex_to_pixel(col, row, ORIGIN_X, ORIGIN_Y)
                points = _hex_corners(center)
                fill = GRID_FILL
                if (col, row) == hover_hex:
                    fill = HOVER_FILL
                pygame.draw.polygon(screen, fill, points)
                # Layered overlays (drawn before the hex outline):
                #   1. Long range — faint pink ring of in-range cells
                #   2. Short range — slightly stronger red overlay
                #   3. Movement range — blue if the cell is empty
                # Cells that the selected ship occupies get nothing.
                if self.selected is not None:
                    self_cell = (col == self.selected.col and row == self.selected.row)
                    if not self_cell:
                        if (col, row) in in_long_range:
                            self._fill_hex(screen, center, points,
                                            (200, 80, 80, 35))
                        if (col, row) in in_short_range:
                            self._fill_hex(screen, center, points,
                                            ATTACK_TARGET_FILL)
                        if ((col, row) in in_move_range
                                and self.battle.ship_at(col, row) is None):
                            self._fill_hex(screen, center, points,
                                            MOVE_RANGE_FILL)
                pygame.draw.polygon(screen, GRID_LINE, points, 1)

    def _fill_hex(self, screen, center, corners, color_rgba):
        """Alpha-blit a coloured hex over the existing fill so range
        and movement overlays can stack."""
        ox, oy = center
        overlay = pygame.Surface((HEX_WIDTH * 2, HEX_SIZE * 2), pygame.SRCALPHA)
        local = [(p[0] - ox + HEX_WIDTH, p[1] - oy + HEX_SIZE)
                 for p in corners]
        pygame.draw.polygon(overlay, color_rgba, local)
        screen.blit(overlay, (ox - HEX_WIDTH, oy - HEX_SIZE))

    def _draw_ships(self, screen):
        for ship in self.battle.ships:
            if ship.destroyed:
                continue
            cx, cy = hex_to_pixel(ship.col, ship.row, ORIGIN_X, ORIGIN_Y)
            color = self._empire_color(ship.empire_id)
            r = self._ship_radius()
            # Stations draw as squares so they read as "fortified
            # structure" rather than "ship". Selection ring is a square
            # too for consistency.
            if ship.is_station:
                rect = pygame.Rect(int(cx - r), int(cy - r), r * 2, r * 2)
                pygame.draw.rect(screen, color, rect)
                pygame.draw.rect(screen, (0, 0, 0), rect, 1)
                if ship is self.selected:
                    pygame.draw.rect(screen, SELECT_RING,
                                      rect.inflate(8, 8), 2)
            else:
                pygame.draw.circle(screen, color, (int(cx), int(cy)), r)
                pygame.draw.circle(screen, (0, 0, 0), (int(cx), int(cy)), r + 1, 1)
                if ship is self.selected:
                    pygame.draw.circle(screen, SELECT_RING,
                                        (int(cx), int(cy)), r + 4, 2)
            glyph_char = "★" if ship.is_station else ship.ship_class[0].upper()
            glyph = self.small_font.render(glyph_char, True, (255, 255, 255))
            screen.blit(glyph, glyph.get_rect(center=(int(cx), int(cy))))

            # Shield ring above the hull bar. Subtle blue arc whose
            # length tracks shield_current / shield_max.
            bar_w = int(HEX_WIDTH * 0.7)
            bar_h = 4
            bar_x = int(cx - bar_w / 2)
            bar_y = int(cy + r + 4)
            if ship.shield_max > 0:
                sh_pct = ship.shield_current / max(1, ship.shield_max)
                pygame.draw.rect(screen, (30, 30, 30),
                                  (bar_x, bar_y, bar_w, bar_h))
                pygame.draw.rect(screen, (110, 170, 240),
                                  (bar_x, bar_y, int(bar_w * sh_pct), bar_h))
                bar_y += bar_h + 1
            # Hull bar.
            pct = ship.hull / max(1, ship.max_hull)
            hp_color = (
                (110, 220, 110) if pct > 0.6
                else (240, 220, 110) if pct > 0.3
                else (240, 110, 110)
            )
            pygame.draw.rect(screen, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
            pygame.draw.rect(screen, hp_color,
                              (bar_x, bar_y, int(bar_w * pct), bar_h))

    def _draw_side_panel(self, screen):
        panel = pygame.Rect(PANEL_X, ORIGIN_Y, PANEL_W, 540 - ORIGIN_Y + 60)
        pygame.draw.rect(screen, PANEL_BG, panel)
        pygame.draw.rect(screen, PANEL_BORDER, panel, 1)

        y = panel.y + 12
        screen.blit(self.header_font.render("Selected Ship", True, TITLE_COLOR),
                     (panel.x + 12, y))
        y += 24
        s = self.selected
        if s is None or s.destroyed or s.empire_id != self._player_empire_id():
            screen.blit(self.body_font.render("— click a ship to select —",
                                                True, HINT_COLOR),
                         (panel.x + 12, y))
            y += 28
        else:
            emp = self._empire(s.empire_id)
            ename = emp.name if emp else "?"
            cls_label = (s.ship_class.replace("_", " ").title()
                          if not s.is_station else "Station")
            for line in (
                f"{s.name}",
                cls_label,
                f"Owner: {ename}",
                f"Shield: {s.shield_current}/{s.shield_max}"
                + (f"  (+{s.shield_regen}/rd)" if s.shield_regen else ""),
                f"Armor:  {s.armor}",
                f"Hull:   {s.hull}/{s.max_hull}",
                f"Attack: {s.attack}",
                f"Move:   {s.moves_left}/{s.speed} MP",
                f"Fired:  {'yes' if s.has_fired else 'no'}",
            ):
                screen.blit(self.body_font.render(line, True, TEXT_COLOR),
                             (panel.x + 12, y))
                y += 20

        # Sides summary.
        y += 8
        screen.blit(self.header_font.render("Forces", True, TITLE_COLOR),
                     (panel.x + 12, y))
        y += 22
        for eid in self.battle.empires_present():
            emp = self._empire(eid)
            label = emp.name if emp else f"Empire {eid}"
            ships_here = self.battle.ships_for(eid)
            color = self._empire_color(eid)
            pygame.draw.rect(screen, color, (panel.x + 12, y + 4, 10, 10))
            text = f"{label}: {len(ships_here)} ship{'s' if len(ships_here) != 1 else ''}"
            screen.blit(self.body_font.render(text, True, TEXT_COLOR),
                         (panel.x + 28, y))
            y += 22

        # Buttons.
        self._buttons = []
        btn_y = panel.bottom - 90
        for action, label in (("end_turn", "End Turn"), ("auto", "Auto-resolve")):
            rect = pygame.Rect(panel.x + 12, btn_y, PANEL_W - 24, 32)
            self._buttons.append((action, rect))
            hovered = rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, BTN_HOVER if hovered else BTN_BG, rect)
            pygame.draw.rect(screen, BTN_BORDER, rect, 1)
            screen.blit(
                self.body_font.render(label, True, TEXT_COLOR),
                self.body_font.render(label, True, TEXT_COLOR).get_rect(center=rect.center),
            )
            btn_y += 38

    def _draw_log(self, screen):
        log_rect = pygame.Rect(20, LOG_TOP_Y, PANEL_X - 40, LOG_H)
        pygame.draw.rect(screen, LOG_BG, log_rect)
        pygame.draw.rect(screen, PANEL_BORDER, log_rect, 1)
        screen.blit(self.header_font.render("Combat Log", True, TITLE_COLOR),
                     (log_rect.x + 12, log_rect.y + 6))
        y = log_rect.y + 28
        for line in self.log_lines[-10:][::-1]:
            screen.blit(self.body_font.render(line, True, TEXT_COLOR),
                         (log_rect.x + 12, y))
            y += 18


# ---- hex polygon ----------------------------------------------------------

def _hex_corners(center: tuple[float, float]) -> list[tuple[int, int]]:
    cx, cy = center
    corners = []
    for i in range(6):
        # Pointy-top: corners at 30°, 90°, 150°, 210°, 270°, 330°.
        angle = math.radians(30 + 60 * i)
        x = cx + HEX_SIZE * math.cos(angle)
        y = cy + HEX_SIZE * math.sin(angle)
        corners.append((int(x), int(y)))
    return corners

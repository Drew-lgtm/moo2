"""Dedicated Research scene — MOO2-style field/tier tree.

5 fields render as columns (Construction / Power / Sociology /
Computers / Biology). Each tier within a field renders as a row. Each
tech is a clickable box: dark when locked, bright when available,
yellow when currently researching, green when unlocked.

The Info-panel "Research" section still works as a summary view —
this scene is just a fuller picture.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import TechState
from ecs.techs import (
    TECHS, FIELDS, FIELD_NAMES, FIELD_COLORS,
    techs_in_field, is_available,
)
from ecs.db import get_connection, update_empire_tech


BG_COLOR = (10, 12, 24, 230)
TITLE_COLOR = (255, 230, 120)
HINT_COLOR = (180, 180, 180)
TEXT_COLOR = (240, 240, 240)


class ResearchScene(Scene):
    # Each tier slot stacks up to 3 alternative cards (MOO2 choice point).
    TIER_H = 92            # vertical room per tier slot
    ALT_H = 26             # each alternative inside a tier
    ALT_GAP = 3
    TIER_GAP = 8
    PADDING_X = 16
    HEADER_H = 56

    def __init__(self, game):
        super().__init__(game)
        # Bigger + bold so the tech card text stays sharp under SCALED.
        self.title_font = pygame.font.SysFont("Arial", 26, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 18, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 15, bold=True)
        self.cost_font = pygame.font.SysFont("Arial", 14, bold=True)
        # (tech_id, rect, available) — refreshed each draw for hit testing.
        self._tech_hits: list[tuple[str, pygame.Rect, bool]] = []
        self._close_rect = pygame.Rect(0, 0, 0, 0)

    # ------------------------------------------------------------------ lifecycle

    def on_enter(self):
        sw = self.game.screen_width
        self._close_rect = pygame.Rect(sw - 100, 16, 80, 32)

    # ------------------------------------------------------------------ helpers

    def _player_tech_state(self) -> TechState | None:
        player = self.game.player_empire()
        if player is None:
            return None
        for _eid, tech in self.game.component_mgr.get_all(TechState):
            if tech.empire_id == player.id:
                return tech
        return None

    def _set_target(self, tech_state: TechState, tech_id: str):
        if tech_state.current_target == tech_id:
            tech_state.current_target = None
            tech_state.progress = 0
        else:
            tech_state.current_target = tech_id
            tech_state.progress = 0
        with get_connection() as conn:
            update_empire_tech(conn, tech_state.empire_id, tech_state.current_target, tech_state.progress)
            conn.commit()

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.scenes.replace("galaxy")
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if self._close_rect.collidepoint(event.pos):
            self.game.scenes.replace("galaxy")
            return
        tech_state = self._player_tech_state()
        if tech_state is None:
            return
        for tech_id, rect, available in self._tech_hits:
            if available and rect.collidepoint(event.pos):
                self._set_target(tech_state, tech_id)
                return

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height

        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))

        screen.blit(self.title_font.render("Research", True, TITLE_COLOR), (self.PADDING_X, 12))

        self._tech_hits = []
        tech_state = self._player_tech_state()
        if tech_state is None:
            screen.blit(self.header_font.render("No player empire.", True, HINT_COLOR),
                        (self.PADDING_X, 60))
            self._draw_close_button(screen)
            return

        unlocked = set(tech_state.unlocked)
        locked = set(tech_state.locked_out)
        current = tech_state.current_target

        # Current target line.
        if current:
            proj = TECHS.get(current, {})
            target_line = f"Researching: {proj.get('name', current)} ({tech_state.progress}/{proj.get('cost', '?')})"
            screen.blit(self.header_font.render(target_line, True, (220, 200, 120)),
                        (self.PADDING_X, 48))
        else:
            screen.blit(self.header_font.render(
                "No active research — pick a tech below (one per tier; the others get locked).",
                True, HINT_COLOR), (self.PADDING_X, 48))

        col_area_w = sw - 2 * self.PADDING_X
        col_w = col_area_w // len(FIELDS)
        top_y = self.HEADER_H + 36

        # Group techs by (field, tier) for stacked alternatives.
        for col, field in enumerate(FIELDS):
            x = self.PADDING_X + col * col_w
            field_name = FIELD_NAMES.get(field, field.title())
            field_color = FIELD_COLORS.get(field, TEXT_COLOR)
            label = self.header_font.render(field_name, True, field_color)
            screen.blit(label, (x + 6, top_y - 28))

            # Find all tiers present in this field.
            tiers = sorted({t.get("tier", 1) for t in techs_in_field(field)})
            for tier in tiers:
                alts = [t for t in techs_in_field(field) if t.get("tier") == tier]
                slot_y = top_y + (tier - 1) * (self.TIER_H + self.TIER_GAP)
                self._draw_tier_slot(
                    screen, x + 2, slot_y, col_w - 6, alts,
                    tech_state, unlocked, locked, current, field_color,
                )

        self._draw_close_button(screen)

        hint = self.body_font.render(
            "Click an alternative to research it. Completing one locks the others (steal them later).   Esc returns.",
            True, HINT_COLOR,
        )
        screen.blit(hint, (self.PADDING_X, sh - hint.get_height() - 10))

    def _draw_tier_slot(self, screen, x, y, w, alts, tech_state, unlocked,
                        locked, current, field_color):
        """Render up to 3 alternative tech cards stacked inside one tier slot."""
        # Vertically center if fewer than 3 alternatives.
        used = len(alts) * self.ALT_H + (len(alts) - 1) * self.ALT_GAP
        oy = (self.TIER_H - used) // 2
        for i, tech in enumerate(alts):
            rect = pygame.Rect(x, y + oy + i * (self.ALT_H + self.ALT_GAP),
                               w, self.ALT_H)
            self._draw_alt_card(screen, rect, tech, tech_state, unlocked,
                                locked, current, field_color)

    def _draw_alt_card(self, screen, rect, tech, tech_state, unlocked, locked,
                       current, field_color):
        tech_id = tech["id"]
        is_unlocked = tech_id in unlocked
        is_locked = tech_id in locked
        is_current = current == tech_id
        is_stub = bool(tech.get("effect_stub"))
        available = (not is_unlocked and not is_locked and not is_current
                     and is_available(tech_id, unlocked, locked))

        if is_unlocked:
            fill, border, name_color = (28, 60, 36), (90, 200, 110), (220, 240, 220)
        elif is_current:
            fill, border, name_color = (60, 56, 24), (220, 200, 120), (240, 230, 180)
        elif is_locked:
            fill, border, name_color = (50, 22, 26), (180, 90, 100), (200, 140, 150)
        elif available:
            fill, border, name_color = (32, 36, 56), field_color, (220, 230, 245)
        else:
            fill, border, name_color = (22, 24, 36), (70, 70, 90), (130, 130, 150)

        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, border, rect, 2 if is_current else 1)

        name = tech["name"] + (" *" if is_stub else "")
        name_surf = self.cost_font.render(name, True, name_color)
        screen.blit(name_surf, (rect.x + 5, rect.y + 3))

        # Status line at bottom-right of the small card.
        if is_unlocked:
            status, sc = "OK", (160, 220, 160)
        elif is_current:
            status, sc = f"{tech_state.progress}/{tech['cost']}", (220, 200, 120)
        elif is_locked:
            status, sc = "Lost", (220, 130, 140)
        elif available:
            status, sc = str(tech["cost"]), (180, 200, 240)
        else:
            status, sc = "—", (130, 130, 150)
        status_surf = self.cost_font.render(status, True, sc)
        screen.blit(status_surf, status_surf.get_rect(midright=(rect.right - 6, rect.centery)))

        self._tech_hits.append((tech_id, rect, available))

    def _draw_close_button(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

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
    # Slightly taller cards now that body font is 15pt; gap unchanged.
    TIER_H = 110
    GAP = 12
    PADDING_X = 20
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
        current = tech_state.current_target

        # Current target line.
        if current:
            proj = TECHS.get(current, {})
            target_line = f"Researching: {proj.get('name', current)} ({tech_state.progress}/{proj.get('cost', '?')})"
            screen.blit(self.header_font.render(target_line, True, (220, 200, 120)),
                        (self.PADDING_X, 48))
        else:
            screen.blit(self.header_font.render("No active research — click an available tech below.",
                                                True, HINT_COLOR),
                        (self.PADDING_X, 48))

        # 5 columns. Each col_w = total_w / 5 minus padding.
        col_area_w = sw - 2 * self.PADDING_X
        col_w = col_area_w // len(FIELDS)
        top_y = self.HEADER_H + 40

        for col, field in enumerate(FIELDS):
            x = self.PADDING_X + col * col_w
            field_name = FIELD_NAMES.get(field, field.title())
            field_color = FIELD_COLORS.get(field, TEXT_COLOR)
            label = self.header_font.render(field_name, True, field_color)
            screen.blit(label, (x + 6, top_y - 28))

            # Tier columns: each tech laid out top-to-bottom by tier.
            for tech in techs_in_field(field):
                tier = tech.get("tier", 1)
                rect = pygame.Rect(
                    x + 4,
                    top_y + (tier - 1) * (self.TIER_H + self.GAP),
                    col_w - 8,
                    self.TIER_H,
                )
                is_unlocked = tech["id"] in unlocked
                is_current = current == tech["id"]
                available = is_available(tech["id"], unlocked) and not is_current

                # State-driven colors.
                if is_unlocked:
                    fill = (28, 60, 36)
                    border = (90, 200, 110)
                    status_color = (160, 220, 160)
                    status = "Unlocked"
                elif is_current:
                    fill = (60, 56, 24)
                    border = (220, 200, 120)
                    status_color = (220, 200, 120)
                    status = f"Researching {tech_state.progress}/{tech['cost']}"
                elif available:
                    fill = (40, 44, 64)
                    border = field_color
                    status_color = (200, 220, 240)
                    status = f"Cost {tech['cost']}"
                else:
                    fill = (24, 24, 36)
                    border = (90, 90, 110)
                    status_color = (130, 130, 150)
                    missing = [TECHS[p]["name"] for p in tech["prereqs"] if p not in unlocked]
                    status = "Needs " + ", ".join(missing) if missing else "Locked"

                pygame.draw.rect(screen, fill, rect)
                pygame.draw.rect(screen, border, rect, 2 if (is_unlocked or is_current) else 1)

                name_color = TEXT_COLOR if (is_unlocked or is_current or available) else (140, 140, 160)
                name_surf = self.body_font.render(tech["name"], True, name_color)
                screen.blit(name_surf, (rect.x + 8, rect.y + 8))

                # Description (wrap by hand to one line for now)
                desc = tech.get("description", "")
                desc_surf = self.cost_font.render(desc, True, name_color)
                screen.blit(desc_surf, (rect.x + 8, rect.y + 32))

                status_surf = self.cost_font.render(status, True, status_color)
                screen.blit(status_surf, (rect.x + 8, rect.bottom - status_surf.get_height() - 8))

                self._tech_hits.append((tech["id"], rect, available))

        self._draw_close_button(screen)

        hint = self.body_font.render(
            "Click an available tech to set as research target.   Esc returns to galaxy.",
            True, HINT_COLOR,
        )
        screen.blit(hint, (self.PADDING_X, sh - hint.get_height() - 12))

    def _draw_close_button(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

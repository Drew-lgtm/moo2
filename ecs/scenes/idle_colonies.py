"""Idle-colony review — the start-of-turn 'awaiting orders' prompt.

After combat + council resolve, the turn flow stops here if any of the
player's colonies have no active build and an empty queue (wasting
industry). Each idle colony is a clickable row that jumps straight to
its Build screen; a Dismiss button (or Esc) skips to free play.

The list is recomputed live, so as the player assigns orders and comes
back it reflects what's still idle.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Planet, Orbiting, Name
from ecs.palette import planet_color


BG_COLOR = (10, 12, 24, 235)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
ROW_BG = (26, 30, 46)
ROW_HOVER = (44, 50, 76)
BTN_BG = (50, 56, 84)
BTN_BORDER = (160, 170, 210)


class IdleColoniesScene(Scene):
    ROW_H = 44

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 26, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 18, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 14, bold=True)
        self._row_hits: list[tuple[int, pygame.Rect]] = []
        self._dismiss_rect = pygame.Rect(0, 0, 0, 0)

    def on_enter(self):
        # Consume the flag so this prompt shows once per turn.
        self.game.pending_idle_review = False

    # ------------------------------------------------------------------ helpers

    def _star_name(self, planet_entity) -> str:
        orbit = self.game.component_mgr.get_component(planet_entity, Orbiting)
        if orbit is None:
            return "?"
        n = self.game.component_mgr.get_component(orbit.star_entity, Name)
        return n.value if n else "?"

    def _open_colony(self, planet_entity):
        orbit = self.game.component_mgr.get_component(planet_entity, Orbiting)
        self.game.selected_planet = planet_entity
        if orbit is not None:
            self.game.selected_star = orbit.star_entity
        self.game.scenes.replace("build")

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
            self.game.scenes.replace("galaxy")
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._dismiss_rect.collidepoint(event.pos):
                self.game.scenes.replace("galaxy")
                return
            for planet_entity, rect in self._row_hits:
                if rect.collidepoint(event.pos):
                    self._open_colony(planet_entity)
                    return

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._row_hits = []

        cm = self.game.component_mgr
        idle = self.game.idle_colonies()

        screen.blit(self.title_font.render("Colonies Awaiting Orders", True, TITLE_COLOR), (40, 28))
        if not idle:
            screen.blit(self.body_font.render("All colonies have build orders.", True, HINT_COLOR), (40, 80))
        else:
            screen.blit(self.small_font.render(
                f"{len(idle)} colony(ies) are idle. Click one to assign production, or Dismiss.",
                True, HINT_COLOR), (40, 70))

        mouse = pygame.mouse.get_pos()
        x, y = 40, 104
        w = min(620, sw - 80)
        for planet_entity in idle:
            planet = cm.get_component(planet_entity, Planet)
            if planet is None:
                continue
            rect = pygame.Rect(x, y, w, self.ROW_H)
            hovered = rect.collidepoint(mouse)
            pygame.draw.rect(screen, ROW_HOVER if hovered else ROW_BG, rect)
            pygame.draw.rect(screen, (70, 78, 110), rect, 1)
            # Planet type dot.
            pygame.draw.circle(screen, planet_color(planet.planet_type), (rect.x + 16, rect.centery), 7)
            label = f"{self._star_name(planet_entity)} — {planet.planet_type} {planet.size}"
            screen.blit(self.body_font.render(label, True, TEXT_COLOR), (rect.x + 34, rect.y + 4))
            screen.blit(self.small_font.render("idle — needs build orders", True, HINT_COLOR),
                        (rect.x + 34, rect.y + 24))
            self._row_hits.append((planet_entity, rect))
            y += self.ROW_H + 6

        # Dismiss button.
        self._dismiss_rect = pygame.Rect(40, sh - 70, 200, 40)
        pygame.draw.rect(screen, BTN_BG, self._dismiss_rect)
        pygame.draw.rect(screen, BTN_BORDER, self._dismiss_rect, 1)
        label = "Dismiss" if idle else "Continue"
        surf = self.body_font.render(label, True, TEXT_COLOR)
        screen.blit(surf, surf.get_rect(center=self._dismiss_rect.center))

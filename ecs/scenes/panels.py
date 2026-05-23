"""Panel scenes shown when the user clicks a bottom-bar button.

Each panel is a full-screen overlay above the bottom UI bar. Esc returns
to the galaxy view; clicking another bottom-bar button switches panels
without going through galaxy (bindings live in Game._bind_game_ui).
"""
from __future__ import annotations

import os
import pygame

from ecs.scene import Scene
from ecs.components import Planet, Orbiting, Name, Owner, Empire, StarVisual
from assets.loader import load_image


PANEL_BG = (10, 12, 24, 220)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (220, 220, 220)
HINT_COLOR = (180, 180, 180)


class PanelScene(Scene):
    """Base class: draws the overlay, title, hint, and the bottom UI bar.

    Subclasses set `title` and implement `draw_content(screen, rect, font)`,
    where `rect` is the body area (below the title, above the hint).
    """

    title = "Panel"

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 22, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 14)

    @property
    def _panel_rect(self) -> pygame.Rect:
        # Above the bottom bar (which takes screen_height // 6).
        bar_height = self.game.screen_height // 6
        return pygame.Rect(0, 0, self.game.screen_width, self.game.screen_height - bar_height)

    def handle_event(self, event):
        self.game.ui_bar.handle_event(event)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.scenes.replace("galaxy")

    def draw(self, screen):
        panel = self._panel_rect
        overlay = pygame.Surface(panel.size, pygame.SRCALPHA)
        overlay.fill(PANEL_BG)
        screen.blit(overlay, panel.topleft)

        title_surf = self.title_font.render(self.title, True, TITLE_COLOR)
        screen.blit(title_surf, (panel.x + 20, panel.y + 16))

        hint = self.body_font.render("Esc to return to galaxy", True, HINT_COLOR)
        screen.blit(hint, (panel.right - hint.get_width() - 20, panel.bottom - hint.get_height() - 10))

        body = pygame.Rect(panel.x + 20, panel.y + 60, panel.width - 40, panel.height - 100)
        self.draw_content(screen, body, self.body_font)

        self.game.ui_bar.draw(screen)

    def draw_content(self, screen, rect, font):
        raise NotImplementedError

    # ---- helpers shared across subclasses --------------------------------

    def _empires_by_id(self) -> dict[int, Empire]:
        return {emp.id: emp for _eid, emp in self.game.component_mgr.get_all(Empire)}

    def _list_owned_planets(self):
        """Yield (planet, owner_id, star_name) for every planet with an Owner."""
        cm = self.game.component_mgr
        for entity_id, owner in cm.get_all(Owner):
            planet = cm.get_component(entity_id, Planet)
            orbit = cm.get_component(entity_id, Orbiting)
            if planet is None or orbit is None:
                continue
            name = cm.get_component(orbit.star_entity, Name)
            yield planet, owner.empire_id, (name.value if name else "?")


def _draw_lines(screen, font, lines, rect, color=TEXT_COLOR, line_height=20):
    y = rect.y
    for line in lines:
        if y + line_height > rect.bottom:
            break
        screen.blit(font.render(line, True, color), (rect.x, y))
        y += line_height


class ColoniesScene(PanelScene):
    title = "Colonies"

    def draw_content(self, screen, rect, font):
        empires = self._empires_by_id()
        lines = []
        for planet, owner_id, star_name in self._list_owned_planets():
            empire = empires.get(owner_id)
            empire_label = empire.name if empire else f"Empire #{owner_id}"
            lines.append(f"{star_name:<14}  {planet.planet_type:<10} {planet.size:<6}  {empire_label}")
        if not lines:
            lines = ["No colonies yet."]
        _draw_lines(screen, font, lines, rect)


class PlanetsScene(PanelScene):
    title = "Planets"

    def draw_content(self, screen, rect, font):
        cm = self.game.component_mgr
        # Group planets by their parent star name.
        by_star: dict[str, list[Planet]] = {}
        for entity_id, planet in cm.get_all(Planet):
            orbit = cm.get_component(entity_id, Orbiting)
            if orbit is None:
                continue
            star_name = cm.get_component(orbit.star_entity, Name)
            key = star_name.value if star_name else "?"
            by_star.setdefault(key, []).append(planet)

        lines = []
        for star_name in sorted(by_star):
            lines.append(f"{star_name}:")
            for p in by_star[star_name]:
                flag = "*" if p.colonizable else " "
                lines.append(f"   {flag} {p.planet_type:<10} {p.size}")
        if not lines:
            lines = ["No planets generated."]
        _draw_lines(screen, font, lines, rect)


class LeadersScene(PanelScene):
    title = "Leaders"

    def draw_content(self, screen, rect, font):
        _draw_lines(screen, font, ["Leaders not implemented yet."], rect, color=HINT_COLOR)


class RacesScene(PanelScene):
    title = "Races"

    THUMB_SIZE = (96, 96)

    def __init__(self, game):
        super().__init__(game)
        self._thumbs: list[tuple[str, pygame.Surface]] = []

    def on_enter(self):
        if self._thumbs:
            return
        races_dir = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "races")
        for fname in sorted(os.listdir(races_dir)):
            if not fname.lower().endswith(".png"):
                continue
            race_name = os.path.splitext(fname)[0]
            surface = load_image(f"races/{fname}", size=self.THUMB_SIZE)
            self._thumbs.append((race_name, surface))

    def draw_content(self, screen, rect, font):
        cols = max(1, rect.width // (self.THUMB_SIZE[0] + 20))
        cell_w = self.THUMB_SIZE[0] + 20
        cell_h = self.THUMB_SIZE[1] + 30
        for idx, (race_name, surface) in enumerate(self._thumbs):
            col, row = idx % cols, idx // cols
            x = rect.x + col * cell_w
            y = rect.y + row * cell_h
            if y + cell_h > rect.bottom:
                break
            screen.blit(surface, (x, y))
            label = font.render(race_name, True, TEXT_COLOR)
            screen.blit(label, (x + (self.THUMB_SIZE[0] - label.get_width()) // 2, y + self.THUMB_SIZE[1] + 4))


class InfoScene(PanelScene):
    title = "Info"

    def draw_content(self, screen, rect, font):
        cm = self.game.component_mgr
        galaxy = self.game.galaxy
        star_count = sum(1 for _ in cm.get_all(StarVisual))
        planet_count = sum(1 for _ in cm.get_all(Planet))
        empire_count = sum(1 for _ in cm.get_all(Empire))

        lines = [
            f"Turn:    {galaxy.turn if galaxy else '-'}",
            f"Seed:    {galaxy.seed if galaxy else '-'}",
            f"Stars:   {star_count}",
            f"Planets: {planet_count}",
            f"Empires: {empire_count}",
        ]
        _draw_lines(screen, font, lines, rect)

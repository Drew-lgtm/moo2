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
from ecs.palette import empire_color, planet_color
from assets.loader import load_image, find_race_portrait


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

    PORTRAIT_SIZE = (40, 40)
    ROW_HEIGHT = 48
    HEADER_HEIGHT = 24

    # Column x offsets relative to the body rect.
    COL_SWATCH = 0
    COL_PORTRAIT = 24
    COL_STAR = 78
    COL_PLANET = 220
    COL_SIZE = 370
    COL_EMPIRE = 450

    def __init__(self, game):
        super().__init__(game)
        self._portraits: dict[str, pygame.Surface] = {}
        self._header_font = pygame.font.SysFont("Arial", 13, bold=True)

    def on_enter(self):
        # Preload portraits for every empire's race so draw() is allocation-free.
        for _eid, empire in self.game.component_mgr.get_all(Empire):
            self._ensure_portrait(empire.race_type)

    def _ensure_portrait(self, race_name: str) -> pygame.Surface | None:
        if race_name in self._portraits:
            return self._portraits[race_name]
        path = find_race_portrait(race_name)
        surface = load_image(path, size=self.PORTRAIT_SIZE) if path else None
        self._portraits[race_name] = surface
        return surface

    def draw_content(self, screen, rect, font):
        empires = self._empires_by_id()
        rows = sorted(
            self._list_owned_planets(),
            key=lambda r: (empires[r[1]].name if r[1] in empires else "", r[2]),
        )

        if not rows:
            _draw_lines(screen, font, ["No colonies yet."], rect, color=HINT_COLOR)
            return

        self._draw_header(screen, rect)
        body_top = rect.y + self.HEADER_HEIGHT
        for i, (planet, owner_id, star_name) in enumerate(rows):
            row_top = body_top + i * self.ROW_HEIGHT
            if row_top + self.ROW_HEIGHT > rect.bottom:
                break
            self._draw_row(screen, font, rect.x, row_top, planet, empires.get(owner_id), star_name)

    def _draw_header(self, screen, rect):
        labels = [
            (self.COL_STAR, "STAR"),
            (self.COL_PLANET, "PLANET"),
            (self.COL_SIZE, "SIZE"),
            (self.COL_EMPIRE, "EMPIRE"),
        ]
        for x_off, text in labels:
            screen.blit(
                self._header_font.render(text, True, HINT_COLOR),
                (rect.x + x_off, rect.y),
            )

    def _draw_row(self, screen, font, x, y, planet, empire, star_name):
        # Empire color swatch (vertical bar).
        if empire is not None:
            pygame.draw.rect(
                screen, empire_color(empire.color),
                pygame.Rect(x + self.COL_SWATCH, y + 4, 12, self.ROW_HEIGHT - 8),
            )

        # Race portrait.
        portrait = self._ensure_portrait(empire.race_type) if empire is not None else None
        if portrait is not None:
            screen.blit(portrait, (x + self.COL_PORTRAIT, y + (self.ROW_HEIGHT - self.PORTRAIT_SIZE[1]) // 2))

        text_y = y + (self.ROW_HEIGHT - font.get_height()) // 2
        screen.blit(font.render(star_name, True, TEXT_COLOR), (x + self.COL_STAR, text_y))

        # Planet type with a colored dot.
        dot_x = x + self.COL_PLANET
        dot_center_y = y + self.ROW_HEIGHT // 2
        pygame.draw.circle(screen, planet_color(planet.planet_type), (dot_x + 6, dot_center_y), 6)
        screen.blit(font.render(planet.planet_type, True, TEXT_COLOR), (dot_x + 18, text_y))

        screen.blit(font.render(planet.size, True, TEXT_COLOR), (x + self.COL_SIZE, text_y))

        empire_label = empire.name if empire is not None else "?"
        screen.blit(font.render(empire_label, True, TEXT_COLOR), (x + self.COL_EMPIRE, text_y))


class PlanetsScene(PanelScene):
    title = "Planets"

    ROW_HEIGHT = 24
    GROUP_HEADER_HEIGHT = 28

    # Column offsets relative to the body rect's left edge.
    COL_INDENT = 16
    COL_DOT = COL_INDENT
    COL_TYPE = COL_INDENT + 18
    COL_SIZE = COL_INDENT + 160
    COL_HABITABLE = COL_INDENT + 240
    COL_OWNER = COL_INDENT + 360

    HABITABLE_COLOR = (120, 220, 120)

    def __init__(self, game):
        super().__init__(game)
        self._group_font = pygame.font.SysFont("Arial", 16, bold=True)

    def draw_content(self, screen, rect, font):
        cm = self.game.component_mgr

        # star_name -> list[(planet, owner_id_or_None)]
        groups: dict[str, list[tuple[Planet, int | None]]] = {}
        for entity_id, planet in cm.get_all(Planet):
            orbit = cm.get_component(entity_id, Orbiting)
            if orbit is None:
                continue
            star_name = cm.get_component(orbit.star_entity, Name)
            key = star_name.value if star_name else "?"
            owner = cm.get_component(entity_id, Owner)
            groups.setdefault(key, []).append((planet, owner.empire_id if owner else None))

        if not groups:
            _draw_lines(screen, font, ["No planets generated."], rect, color=HINT_COLOR)
            return

        empires = self._empires_by_id()
        y = rect.y
        for star_name in sorted(groups):
            if y + self.GROUP_HEADER_HEIGHT > rect.bottom:
                return
            screen.blit(self._group_font.render(star_name, True, TITLE_COLOR), (rect.x, y))
            y += self.GROUP_HEADER_HEIGHT

            for planet, owner_id in groups[star_name]:
                if y + self.ROW_HEIGHT > rect.bottom:
                    return
                self._draw_row(screen, font, rect.x, y, planet, owner_id, empires)
                y += self.ROW_HEIGHT

    def _draw_row(self, screen, font, x, y, planet, owner_id, empires):
        dot_center_y = y + self.ROW_HEIGHT // 2
        pygame.draw.circle(
            screen, planet_color(planet.planet_type),
            (x + self.COL_DOT + 6, dot_center_y), 5,
        )

        text_y = y + (self.ROW_HEIGHT - font.get_height()) // 2
        screen.blit(font.render(planet.planet_type, True, TEXT_COLOR), (x + self.COL_TYPE, text_y))
        screen.blit(font.render(planet.size, True, TEXT_COLOR), (x + self.COL_SIZE, text_y))

        if planet.colonizable:
            screen.blit(
                font.render("habitable", True, self.HABITABLE_COLOR),
                (x + self.COL_HABITABLE, text_y),
            )

        empire = empires.get(owner_id) if owner_id is not None else None
        if empire is not None:
            pygame.draw.rect(
                screen, empire_color(empire.color),
                pygame.Rect(x + self.COL_OWNER, y + 4, 10, self.ROW_HEIGHT - 8),
            )
            screen.blit(
                font.render(empire.name, True, TEXT_COLOR),
                (x + self.COL_OWNER + 16, text_y),
            )


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

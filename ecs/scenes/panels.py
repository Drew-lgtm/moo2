"""Panel scenes shown when the user clicks a bottom-bar button.

Each panel is a full-screen overlay above the bottom UI bar. Esc returns
to the galaxy view; clicking another bottom-bar button switches panels
without going through galaxy (bindings live in Game._bind_game_ui).
"""
from __future__ import annotations

import os
import pygame

from ecs.scene import Scene
from ecs.components import Planet, Orbiting, Name, Owner, Empire, StarVisual, Population, BuildState, TechState
from ecs.palette import empire_color, planet_color
from ecs.economy import planet_output
from ecs.techs import TECHS, TECH_ORDER, is_available
from ecs.db import get_connection, update_empire_tech
from assets.loader import load_image, find_race_portrait


PANEL_BG = (10, 12, 24, 220)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (220, 220, 220)
HINT_COLOR = (180, 180, 180)


class PanelScene(Scene):
    """Base class: draws the overlay, title, hint, scrollbar, UI bar.

    Subclasses set `title` and implement `draw_content(screen, rect, font)`
    where `rect` is the visible body area. Subclasses MUST return the total
    height the content would take if unconstrained; PanelScene uses that to
    clamp scrolling and decide whether to render the scrollbar. Subclasses
    can read `self.scroll_offset` and shift their items by it. The body
    rect is clipped during draw_content, so off-screen items are safe to
    emit unconditionally.

    Subclasses that override on_enter must call super().on_enter() so the
    scroll position resets when the panel is entered.
    """

    title = "Panel"
    SCROLL_STEP = 40
    SCROLLBAR_WIDTH = 6
    SCROLLBAR_PADDING = 2
    SCROLLBAR_TRACK = (40, 40, 60)
    SCROLLBAR_THUMB = (180, 180, 220)

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 22, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 14)
        self.scroll_offset = 0
        self._content_height = 0
        self._body_rect_cache: pygame.Rect | None = None

    def on_enter(self):
        self.scroll_offset = 0

    @property
    def _panel_rect(self) -> pygame.Rect:
        bar_height = self.game.screen_height // 6
        return pygame.Rect(0, 0, self.game.screen_width, self.game.screen_height - bar_height)

    def _max_scroll(self) -> int:
        if self._body_rect_cache is None:
            return 0
        return max(0, self._content_height - self._body_rect_cache.height)

    def _clamp_scroll(self):
        self.scroll_offset = max(0, min(self.scroll_offset, self._max_scroll()))

    def _page_size(self) -> int:
        if self._body_rect_cache is None:
            return 100
        return max(40, self._body_rect_cache.height - 40)

    def handle_event(self, event):
        self.game.ui_bar.handle_event(event)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.game.scenes.replace("galaxy")
                return
            if event.key == pygame.K_PAGEDOWN:
                self.scroll_offset += self._page_size()
            elif event.key == pygame.K_PAGEUP:
                self.scroll_offset -= self._page_size()
            elif event.key == pygame.K_HOME:
                self.scroll_offset = 0
            elif event.key == pygame.K_END:
                self.scroll_offset = self._max_scroll()
            elif event.key == pygame.K_DOWN:
                self.scroll_offset += self.SCROLL_STEP
            elif event.key == pygame.K_UP:
                self.scroll_offset -= self.SCROLL_STEP
            self._clamp_scroll()
        elif event.type == pygame.MOUSEWHEEL:
            self.scroll_offset -= event.y * self.SCROLL_STEP
            self._clamp_scroll()

    def draw(self, screen):
        panel = self._panel_rect
        overlay = pygame.Surface(panel.size, pygame.SRCALPHA)
        overlay.fill(PANEL_BG)
        screen.blit(overlay, panel.topleft)

        title_surf = self.title_font.render(self.title, True, TITLE_COLOR)
        screen.blit(title_surf, (panel.x + 20, panel.y + 16))

        hint = self.body_font.render(
            "Esc to return  ·  scroll / PgUp / PgDn / Home / End",
            True, HINT_COLOR,
        )
        screen.blit(hint, (panel.right - hint.get_width() - 20, panel.bottom - hint.get_height() - 10))

        body = pygame.Rect(panel.x + 20, panel.y + 60, panel.width - 40, panel.height - 100)
        self._body_rect_cache = body

        prev_clip = screen.get_clip()
        screen.set_clip(body)
        height = self.draw_content(screen, body, self.body_font) or 0
        screen.set_clip(prev_clip)

        self._content_height = int(height)
        self._clamp_scroll()
        self._draw_scrollbar(screen, body)

        self.game.ui_bar.draw(screen)

    def _draw_scrollbar(self, screen, body):
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return
        track = pygame.Rect(
            body.right - self.SCROLLBAR_WIDTH - self.SCROLLBAR_PADDING,
            body.y, self.SCROLLBAR_WIDTH, body.height,
        )
        pygame.draw.rect(screen, self.SCROLLBAR_TRACK, track)
        thumb_h = max(20, int(body.height * body.height / max(self._content_height, 1)))
        thumb_y = body.y + int((body.height - thumb_h) * (self.scroll_offset / max_scroll))
        pygame.draw.rect(screen, self.SCROLLBAR_THUMB, (track.x, thumb_y, track.w, thumb_h))

    def draw_content(self, screen, rect, font) -> int:
        """Render content and return the unconstrained content height in px."""
        raise NotImplementedError

    # ---- helpers shared across subclasses --------------------------------

    def _empires_by_id(self) -> dict[int, Empire]:
        return {emp.id: emp for _eid, emp in self.game.component_mgr.get_all(Empire)}

    def _list_owned_planets(self):
        """Yield (entity_id, planet, owner_id, star_name) for every planet with an Owner."""
        cm = self.game.component_mgr
        for entity_id, owner in cm.get_all(Owner):
            planet = cm.get_component(entity_id, Planet)
            orbit = cm.get_component(entity_id, Orbiting)
            if planet is None or orbit is None:
                continue
            name = cm.get_component(orbit.star_entity, Name)
            yield entity_id, planet, owner.empire_id, (name.value if name else "?")


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
    COL_PORTRAIT = 20
    COL_STAR = 68
    COL_PLANET = 190
    COL_SIZE = 310
    COL_POP = 376
    COL_FWS = 440        # F/W/S worker split
    COL_FOOD = 530
    COL_IND = 580
    COL_RES = 630
    COL_BC = 680
    COL_EMPIRE = 740

    def __init__(self, game):
        super().__init__(game)
        self._portraits: dict[str, pygame.Surface] = {}
        self._header_font = pygame.font.SysFont("Arial", 13, bold=True)

    def on_enter(self):
        super().on_enter()
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
            key=lambda r: (empires[r[2]].name if r[2] in empires else "", r[3]),
        )

        if not rows:
            _draw_lines(screen, font, ["No colonies yet."], rect, color=HINT_COLOR)
            return 0

        # Sticky column header sits at body top and never scrolls.
        self._draw_header(screen, rect)

        # Rows scroll within a sub-clip below the header.
        scroll_area = pygame.Rect(
            rect.x, rect.y + self.HEADER_HEIGHT,
            rect.width, rect.height - self.HEADER_HEIGHT,
        )
        prev_clip = screen.get_clip()
        screen.set_clip(scroll_area)
        cm = self.game.component_mgr
        for i, (entity_id, planet, owner_id, star_name) in enumerate(rows):
            row_top = scroll_area.y + i * self.ROW_HEIGHT - self.scroll_offset
            if row_top + self.ROW_HEIGHT < scroll_area.y or row_top > scroll_area.bottom:
                continue
            population = cm.get_component(entity_id, Population)
            build_state = cm.get_component(entity_id, BuildState)
            self._draw_row(screen, font, rect.x, row_top, planet, population, build_state, empires.get(owner_id), star_name)
        screen.set_clip(prev_clip)

        return self.HEADER_HEIGHT + len(rows) * self.ROW_HEIGHT

    def _draw_header(self, screen, rect):
        labels = [
            (self.COL_STAR, "STAR"),
            (self.COL_PLANET, "PLANET"),
            (self.COL_SIZE, "SIZE"),
            (self.COL_POP, "POP"),
            (self.COL_FWS, "F/W/S"),
            (self.COL_FOOD, "FOOD"),
            (self.COL_IND, "IND"),
            (self.COL_RES, "RES"),
            (self.COL_BC, "BC"),
            (self.COL_EMPIRE, "EMPIRE"),
        ]
        for x_off, text in labels:
            screen.blit(
                self._header_font.render(text, True, HINT_COLOR),
                (rect.x + x_off, rect.y),
            )

    def _draw_row(self, screen, font, x, y, planet, population, build_state, empire, star_name):
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

        pop_label = f"{population.current}/{population.max}" if population is not None else "-"
        screen.blit(font.render(pop_label, True, TEXT_COLOR), (x + self.COL_POP, text_y))

        if population is not None:
            fws_label = f"{population.farmers}/{population.workers}/{population.scientists}"
        else:
            fws_label = "-"
        screen.blit(font.render(fws_label, True, TEXT_COLOR), (x + self.COL_FWS, text_y))

        food, industry, research, bonus_bc = planet_output(planet, population, build_state)
        # Industry diverts to project progress while building; otherwise it
        # becomes BC, on top of any flat building bonus.
        building = bool(build_state and build_state.current_project)
        bc_to_empire = bonus_bc + (0 if building else industry)
        screen.blit(font.render(str(food), True, TEXT_COLOR), (x + self.COL_FOOD, text_y))
        screen.blit(font.render(str(industry), True, TEXT_COLOR), (x + self.COL_IND, text_y))
        screen.blit(font.render(str(research), True, TEXT_COLOR), (x + self.COL_RES, text_y))
        screen.blit(font.render(str(bc_to_empire), True, TEXT_COLOR), (x + self.COL_BC, text_y))

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
            return 0

        empires = self._empires_by_id()
        total = 0
        base_y = rect.y - self.scroll_offset
        for star_name in sorted(groups):
            y = base_y + total
            if rect.y - self.GROUP_HEADER_HEIGHT < y < rect.bottom:
                screen.blit(self._group_font.render(star_name, True, TITLE_COLOR), (rect.x, y))
            total += self.GROUP_HEADER_HEIGHT

            for planet, owner_id in groups[star_name]:
                y = base_y + total
                if rect.y - self.ROW_HEIGHT < y < rect.bottom:
                    self._draw_row(screen, font, rect.x, y, planet, owner_id, empires)
                total += self.ROW_HEIGHT

        return total

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
        super().on_enter()
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

    SECTION_HEADER_COLOR = (255, 230, 120)
    TECH_ROW_HEIGHT = 22

    def __init__(self, game):
        super().__init__(game)
        self._section_font = pygame.font.SysFont("Arial", 16, bold=True)
        # (tech_id, rect, available) recorded per draw so handle_event can hit-test.
        self._tech_row_hits: list[tuple[str, pygame.Rect, bool]] = []

    def _player_tech_state(self) -> TechState | None:
        player = self.game.player_empire()
        if player is None:
            return None
        for _eid, tech in self.game.component_mgr.get_all(TechState):
            if tech.empire_id == player.id:
                return tech
        return None

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            tech_state = self._player_tech_state()
            if tech_state is not None:
                for tech_id, rect, available in self._tech_row_hits:
                    if available and rect.collidepoint(event.pos):
                        self._set_tech_target(tech_state, tech_id)
                        return
        super().handle_event(event)

    def _set_tech_target(self, tech_state: TechState, tech_id: str):
        # Switching mid-research keeps progress only if same target; otherwise reset.
        if tech_state.current_target == tech_id:
            tech_state.current_target = None  # toggle off
        else:
            tech_state.current_target = tech_id
            tech_state.progress = 0
        with get_connection() as conn:
            update_empire_tech(conn, tech_state.empire_id, tech_state.current_target, tech_state.progress)
            conn.commit()

    def draw_content(self, screen, rect, font):
        cm = self.game.component_mgr
        galaxy = self.game.galaxy
        star_count = sum(1 for _ in cm.get_all(StarVisual))
        planet_count = sum(1 for _ in cm.get_all(Planet))
        empire_count = sum(1 for _ in cm.get_all(Empire))

        y = rect.y
        # ---- Empire Stats ----
        screen.blit(self._section_font.render("Empire Stats", True, self.SECTION_HEADER_COLOR), (rect.x, y))
        y += 24
        stat_lines = [
            f"Turn:    {galaxy.turn if galaxy else '-'}",
            f"Seed:    {galaxy.seed if galaxy else '-'}",
            f"Stars:   {star_count}",
            f"Planets: {planet_count}",
            f"Empires: {empire_count}",
        ]
        for line in stat_lines:
            screen.blit(font.render(line, True, TEXT_COLOR), (rect.x, y))
            y += 20
        y += 12

        # ---- Research ----
        screen.blit(self._section_font.render("Research", True, self.SECTION_HEADER_COLOR), (rect.x, y))
        y += 24

        tech_state = self._player_tech_state()
        self._tech_row_hits = []
        if tech_state is None:
            screen.blit(font.render("No player empire.", True, HINT_COLOR), (rect.x, y))
            return y - rect.y

        # Current target line.
        if tech_state.current_target:
            proj = TECHS.get(tech_state.current_target, {})
            target_label = f"Current: {proj.get('name', tech_state.current_target)} ({tech_state.progress}/{proj.get('cost', '?')})"
            color = (220, 200, 120)
        else:
            target_label = "Current: (none — click a tech below to start research)"
            color = HINT_COLOR
        screen.blit(font.render(target_label, True, color), (rect.x, y))
        y += 22

        unlocked = set(tech_state.unlocked)
        # ---- Tech list ----
        for tech_id in TECH_ORDER:
            tech = TECHS[tech_id]
            row_rect = pygame.Rect(rect.x, y, rect.width - 20, self.TECH_ROW_HEIGHT)
            is_unlocked = tech_id in unlocked
            is_current = tech_state.current_target == tech_id
            available = (not is_unlocked) and is_available(tech_id, unlocked) and not is_current

            if is_unlocked:
                marker = "✓"
                row_color = (160, 200, 160)
                status = "unlocked"
            elif is_current:
                marker = "▶"
                row_color = (220, 200, 120)
                status = "researching"
            elif available:
                marker = "○"
                row_color = TEXT_COLOR
                status = f"cost {tech['cost']}"
            else:
                marker = "✕"
                row_color = (130, 130, 150)
                prereqs = [TECHS[p]["name"] for p in tech["prereqs"] if p not in unlocked]
                status = f"needs {', '.join(prereqs)}" if prereqs else "locked"

            label = f"{marker} {tech['name']:<24} {status}"
            screen.blit(font.render(label, True, row_color), (row_rect.x, y))
            self._tech_row_hits.append((tech_id, row_rect, available))
            y += self.TECH_ROW_HEIGHT

        return y - rect.y

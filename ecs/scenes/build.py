"""Dedicated build picker for one planet.

Reached from ColonyScene via the Build button. Layout matches MOO2's
build screen: categorised list on the left (Economy / Farming /
Science / Military), the current planet's queue on the right,
search field across the top.

Click a row to add the project to the planet's queue. Locked-by-tech
items render dimmed and clicking them is a no-op. Already-built
buildings render as "BUILT" and can't be queued again. Ship projects
can be queued multiple times because completion spawns a unit rather
than entering ``BuildState.completed``.

Esc / Close returns to ColonyScene for the same planet.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Planet, BuildState, Owner, Empire, TechState, Name, Orbiting
from ecs.projects import (
    PROJECTS, CATEGORIES, CATEGORY_LABEL, CATEGORY_COLOR,
    projects_in_category, project_is_available,
)
from ecs.techs import TECHS
from ecs.ship_design import loadout_summary
from ecs.db import get_connection, update_planet_build, save_planet_build_queue


BG_COLOR = (10, 12, 24, 235)
TITLE_COLOR = (255, 230, 120)
HEADER_COLOR = (200, 200, 220)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
FIELD_BG = (28, 32, 48)
FIELD_BORDER = (140, 150, 180)
ROW_BG = (24, 28, 42)
ROW_BG_HOVER = (40, 46, 70)
ROW_LOCKED_BG = (18, 20, 30)
SELECTED_RING = (255, 230, 120)


class BuildScene(Scene):
    HEADER_H = 56
    SEARCH_H = 32
    TAB_H = 30
    ROW_H = 56
    LEFT_PANEL_W_FRAC = 0.62  # left list takes ~62% of width

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 15, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 13, bold=True)

        # State.
        self._planet_entity: int | None = None
        self.active_category: str = "economy"
        self.search_text: str = ""
        self.search_focused: bool = False

        # Layout rects (rebuilt on enter).
        self._close_rect = pygame.Rect(0, 0, 0, 0)
        self._search_rect = pygame.Rect(0, 0, 0, 0)
        self._tab_rects: list[tuple[str, pygame.Rect]] = []
        # (project_id, row_rect, available)
        self._row_hits: list[tuple[str, pygame.Rect, bool]] = []
        # Right-side queue interaction.
        # ("remove", index, rect) — click to drop from queue
        self._queue_hits: list[tuple[str, int, pygame.Rect]] = []
        self._scroll_offset = 0

    # ------------------------------------------------------------------ lifecycle

    def on_enter(self):
        self._planet_entity = getattr(self.game, "selected_planet", None)
        if self._planet_entity is None:
            self.game.scenes.replace("galaxy")
            return
        self._layout()
        pygame.key.set_repeat(400, 50)

    def on_exit(self):
        pygame.key.set_repeat(0)
        self._planet_entity = None

    def _layout(self):
        sw, sh = self.game.screen_width, self.game.screen_height
        self._close_rect = pygame.Rect(sw - 100, 16, 80, 32)

        # Search field below the title row, full width on the left
        # portion (so categories can sit beneath it).
        left_w = int(sw * self.LEFT_PANEL_W_FRAC)
        self._search_rect = pygame.Rect(24, self.HEADER_H, left_w - 48, self.SEARCH_H)

        # Category tabs across the top of the list, beneath the search
        # field.
        tab_y = self.HEADER_H + self.SEARCH_H + 8
        tab_w = (left_w - 48) // len(CATEGORIES)
        self._tab_rects = []
        for i, (key, _label, _color) in enumerate(CATEGORIES):
            rect = pygame.Rect(24 + i * tab_w, tab_y, tab_w - 4, self.TAB_H)
            self._tab_rects.append((key, rect))

    # ------------------------------------------------------------------ helpers

    def _planet_components(self):
        cm = self.game.component_mgr
        if self._planet_entity is None:
            return None, None, None
        planet = cm.get_component(self._planet_entity, Planet)
        build_state = cm.get_component(self._planet_entity, BuildState)
        owner = cm.get_component(self._planet_entity, Owner)
        return planet, build_state, owner

    def _star_name(self) -> str:
        if self._planet_entity is None:
            return ""
        orbit = self.game.component_mgr.get_component(self._planet_entity, Orbiting)
        if orbit is None:
            return ""
        name = self.game.component_mgr.get_component(orbit.star_entity, Name)
        return name.value if name else ""

    def _player_empire_id(self):
        for _eid, emp in self.game.component_mgr.get_all(Empire):
            if emp.is_player:
                return emp.id
        return None

    def _player_owns_this(self, owner) -> bool:
        return owner is not None and owner.empire_id == self._player_empire_id()

    def _player_unlocked_techs(self) -> set[str]:
        player_id = self._player_empire_id()
        if player_id is None:
            return set()
        for _eid, tech in self.game.component_mgr.get_all(TechState):
            if tech.empire_id == player_id:
                return set(tech.unlocked)
        return set()

    def _filtered_projects(self, build_state, unlocked) -> list[dict]:
        """Projects shown in the list, after category + search filter.

        For the Ships tab we group by ship_kind so civilian vessels sit
        above military ones (with a subheader between them, rendered in
        ``_draw_list``). Search ignores the category and matches across
        every project.
        """
        if self.search_text.strip():
            needle = self.search_text.strip().lower()
            items = [
                p for p in PROJECTS.values()
                if needle in p["name"].lower()
                or needle in p.get("description", "").lower()
            ]
            items.sort(key=lambda p: p["name"].lower())
            return items
        if self.active_category == "ships":
            # Civilian first (Scout/Freighter/Outpost/Colony), then
            # Military (Troop Transport + Frigate→Dreadnought).
            # Alphabetical within each group.
            civ = sorted(
                (p for p in PROJECTS.values()
                 if p.get("category") == "ships" and p.get("ship_kind") == "civilian"),
                key=lambda p: p["name"].lower(),
            )
            mil = sorted(
                (p for p in PROJECTS.values()
                 if p.get("category") == "ships" and p.get("ship_kind") == "military"),
                key=lambda p: p["name"].lower(),
            )
            return civ + mil
        return projects_in_category(self.active_category)

    # ------------------------------------------------------------------ input

    def tooltip_at(self, pos):
        """Right-click a project row -> cost, tech requirement,
        effects. Ship projects also surface the auto-loadout the new
        hull would carry given current research."""
        for project_id, row_rect, _avail in self._row_hits:
            if not row_rect.collidepoint(pos):
                continue
            proj = PROJECTS.get(project_id, {})
            lines = [proj.get("name", project_id)]
            cat = proj.get("category", "")
            cost = proj.get("cost", "?")
            if proj.get("type") == "ship":
                lines.append(f"Ship · {cost} production")
                ship_class = proj.get("ship_class")
                if ship_class:
                    lines.append(loadout_summary(ship_class, self._player_unlocked_techs()))
            else:
                lines.append(f"{cat.title()} · {cost} production")
                effects = proj.get("effects", {})
                if effects:
                    bits = [f"+{v} {k}" for k, v in effects.items()]
                    lines.append("Effects: " + ", ".join(bits))
            req = proj.get("required_tech")
            if req:
                lines.append(f"hint:needs {TECHS.get(req, {}).get('name', req)}")
            desc = proj.get("description")
            if desc and desc not in lines:
                lines.append(f"hint:{desc}")
            return lines
        return None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._return_to_colony()
                return
            if self.search_focused:
                if event.key == pygame.K_BACKSPACE:
                    self.search_text = self.search_text[:-1]
                    return
                if event.key == pygame.K_RETURN:
                    self.search_focused = False
                    return
                if event.unicode and event.unicode.isprintable():
                    self.search_text += event.unicode
                return
            # Number keys 1..4 jump to categories.
            if pygame.K_1 <= event.key <= pygame.K_4:
                idx = event.key - pygame.K_1
                if idx < len(CATEGORIES):
                    self.active_category = CATEGORIES[idx][0]
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 4:
                self._scroll_offset = max(0, self._scroll_offset - self.ROW_H)
                return
            if event.button == 5:
                self._scroll_offset += self.ROW_H
                return
            if event.button != 1:
                return
            pos = event.pos
            if self._close_rect.collidepoint(pos):
                self._return_to_colony()
                return
            if self._search_rect.collidepoint(pos):
                self.search_focused = True
                return
            else:
                self.search_focused = False
            for key, rect in self._tab_rects:
                if rect.collidepoint(pos):
                    self.active_category = key
                    self.search_text = ""
                    self._scroll_offset = 0
                    return
            for project_id, row_rect, available in self._row_hits:
                if available and row_rect.collidepoint(pos):
                    self._queue_project(project_id)
                    return
            for action, index, rect in self._queue_hits:
                if rect.collidepoint(pos):
                    if action == "remove":
                        self._remove_from_queue(index)
                    return

    def _return_to_colony(self):
        self.game.scenes.replace("colony")

    def _queue_project(self, project_id: str):
        planet, build_state, owner = self._planet_components()
        if planet is None or build_state is None or not self._player_owns_this(owner):
            return
        proj = PROJECTS.get(project_id)
        if proj is None:
            return
        is_ship = proj.get("type") == "ship"
        if not is_ship and project_id in build_state.completed:
            return
        if not project_is_available(project_id, self._player_unlocked_techs()):
            return
        if not is_ship and build_state.current_project == project_id:
            return

        current_changed = False
        queue_changed = False
        if is_ship:
            if build_state.current_project is None:
                build_state.current_project = project_id
                current_changed = True
            else:
                build_state.queue.append(project_id)
                queue_changed = True
        elif project_id in build_state.queue:
            # Treat repeat-click as remove for buildings.
            build_state.queue.remove(project_id)
            queue_changed = True
        elif build_state.current_project is None:
            build_state.current_project = project_id
            current_changed = True
        else:
            build_state.queue.append(project_id)
            queue_changed = True

        with get_connection() as conn:
            if current_changed:
                update_planet_build(conn, planet.id, build_state.current_project, build_state.progress)
            if queue_changed:
                save_planet_build_queue(conn, planet.id, list(build_state.queue))
            conn.commit()

    def _remove_from_queue(self, index: int):
        planet, build_state, owner = self._planet_components()
        if planet is None or build_state is None or not self._player_owns_this(owner):
            return
        if 0 <= index < len(build_state.queue):
            build_state.queue.pop(index)
            with get_connection() as conn:
                save_planet_build_queue(conn, planet.id, list(build_state.queue))
                conn.commit()

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))

        planet, build_state, owner = self._planet_components()
        if planet is None:
            return

        # Title.
        title = f"Build at {self._star_name()} — {planet.planet_type} {planet.size}"
        screen.blit(self.title_font.render(title, True, TITLE_COLOR), (24, 16))

        self._draw_search(screen)
        self._draw_tabs(screen)
        self._draw_list(screen, build_state)
        self._draw_queue_panel(screen, build_state)
        self._draw_close_button(screen)

        hint = self.small_font.render(
            "Click to queue.  Type to search.  Esc returns to colony.",
            True, HINT_COLOR,
        )
        screen.blit(hint, (24, sh - hint.get_height() - 12))

    def _draw_search(self, screen):
        rect = self._search_rect
        bg = FIELD_BG if not self.search_focused else (40, 46, 70)
        border = FIELD_BORDER if not self.search_focused else SELECTED_RING
        pygame.draw.rect(screen, bg, rect)
        pygame.draw.rect(screen, border, rect, 2 if self.search_focused else 1)
        # Magnifier glyph + text.
        label_text = self.search_text or "Search projects..."
        color = TEXT_COLOR if self.search_text else HINT_COLOR
        label = self.body_font.render(f"⌕  {label_text}", True, color)
        screen.blit(label, label.get_rect(midleft=(rect.x + 10, rect.centery)))

    def _draw_tabs(self, screen):
        searching = bool(self.search_text.strip())
        for key, rect in self._tab_rects:
            active = (key == self.active_category) and not searching
            label_text = CATEGORY_LABEL.get(key, key)
            base = CATEGORY_COLOR.get(key, TEXT_COLOR)
            bg = (40, 46, 70) if active else (24, 28, 42)
            border = base if active else (90, 100, 130)
            pygame.draw.rect(screen, bg, rect)
            pygame.draw.rect(screen, border, rect, 2 if active else 1)
            label = self.header_font.render(label_text, True, base if active else HEADER_COLOR)
            screen.blit(label, label.get_rect(center=rect.center))

    def _list_area(self) -> pygame.Rect:
        sw, sh = self.game.screen_width, self.game.screen_height
        left_w = int(sw * self.LEFT_PANEL_W_FRAC)
        top = self.HEADER_H + self.SEARCH_H + 8 + self.TAB_H + 12
        bottom_margin = 60
        return pygame.Rect(24, top, left_w - 48, sh - top - bottom_margin)

    SUBHEADER_H = 28

    def _draw_list(self, screen, build_state):
        area = self._list_area()
        prev_clip = screen.get_clip()
        screen.set_clip(area)

        unlocked = self._player_unlocked_techs()
        items = self._filtered_projects(build_state, unlocked)
        self._row_hits = []

        if not items:
            empty = self.body_font.render("No matching projects.", True, HINT_COLOR)
            screen.blit(empty, (area.x + 12, area.y + 16))
            screen.set_clip(prev_clip)
            return

        # Build a render schedule: (kind, payload). For the Ships tab
        # without an active search we insert subheaders before the first
        # civilian and military ship; everything else is just a row.
        searching = bool(self.search_text.strip())
        schedule: list[tuple[str, object]] = []
        if self.active_category == "ships" and not searching:
            last_kind: str | None = None
            for proj in items:
                kind = proj.get("ship_kind", "military")
                if kind != last_kind:
                    label = "Civilian" if kind == "civilian" else "Military"
                    schedule.append(("header", label))
                    last_kind = kind
                schedule.append(("row", proj))
        else:
            for proj in items:
                schedule.append(("row", proj))

        # Compute total height + clamp scroll.
        total_h = 0
        for kind, _ in schedule:
            total_h += self.SUBHEADER_H if kind == "header" else self.ROW_H
        max_scroll = max(0, total_h - area.height)
        self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

        y_cursor = area.y - self._scroll_offset
        for kind, payload in schedule:
            h = self.SUBHEADER_H if kind == "header" else self.ROW_H
            if y_cursor + h >= area.y and y_cursor <= area.bottom:
                if kind == "header":
                    self._draw_subheader(screen, area, y_cursor, payload)
                else:
                    self._draw_row(screen, payload, area, y_cursor, build_state, unlocked)
            y_cursor += h

        screen.set_clip(prev_clip)

    def _draw_subheader(self, screen, area, y, label):
        # A thin colored band between groups.
        rect = pygame.Rect(area.x, y, area.width, self.SUBHEADER_H - 6)
        pygame.draw.rect(screen, (22, 26, 40), rect)
        # Left underline tinted by the parent category accent.
        accent = CATEGORY_COLOR.get(self.active_category, TEXT_COLOR)
        pygame.draw.line(
            screen, accent,
            (rect.x + 8, rect.bottom - 2),
            (rect.x + 8 + 80, rect.bottom - 2),
            2,
        )
        text = self.header_font.render(label, True, accent)
        screen.blit(text, (rect.x + 12, rect.y + 4))

    def _draw_row(self, screen, proj, area, row_top, build_state, unlocked):
        is_ship = proj.get("type") == "ship"
        proj_id = proj["id"]
        already_built = build_state is not None and (not is_ship) and proj_id in build_state.completed
        currently_building = build_state is not None and build_state.current_project == proj_id
        queued = build_state is not None and proj_id in build_state.queue
        tech_locked = not project_is_available(proj_id, unlocked)
        available = not tech_locked and not already_built

        rect = pygame.Rect(area.x, row_top, area.width, self.ROW_H - 4)

        # Backdrop tint.
        if not available:
            bg = ROW_LOCKED_BG
        elif currently_building:
            bg = (40, 46, 70)
        else:
            bg = ROW_BG
        pygame.draw.rect(screen, bg, rect)

        # Left bar: category accent.
        cat_color = CATEGORY_COLOR.get(proj.get("category", ""), (120, 120, 140))
        pygame.draw.rect(screen, cat_color, pygame.Rect(rect.x, rect.y + 6, 4, rect.height - 12))

        # Border: highlight when currently building / queued.
        if currently_building:
            border = SELECTED_RING
            border_w = 2
        elif queued:
            border = (120, 180, 255)
            border_w = 2
        else:
            border = (60, 70, 100) if available else (50, 50, 70)
            border_w = 1
        pygame.draw.rect(screen, border, rect, border_w)

        # Name.
        name_color = TEXT_COLOR if available else (140, 140, 160)
        name = self.header_font.render(proj["name"], True, name_color)
        screen.blit(name, (rect.x + 14, rect.y + 6))

        # Description, lighter. For ship projects, show the live auto-
        # loadout summary based on the player's current tech — so the
        # player sees what their ships will actually be equipped with.
        desc_color = HINT_COLOR if available else (120, 120, 140)
        desc_text = proj.get("description", "")
        if proj.get("type") == "ship":
            ship_class = proj.get("ship_class")
            if ship_class:
                desc_text = loadout_summary(ship_class, unlocked)
        desc = self.small_font.render(desc_text, True, desc_color)
        screen.blit(desc, (rect.x + 14, rect.y + rect.height - desc.get_height() - 6))

        # Right side: cost / status pill. Cost is in production (industry
        # gathered by workers), NOT BC — the colony's workforce builds it
        # over time.
        if already_built:
            status_text = "BUILT"
            status_color = (160, 220, 160)
        elif currently_building:
            status_text = f"BUILDING {build_state.progress}/{proj['cost']}"
            status_color = SELECTED_RING
        elif queued:
            status_text = "QUEUED"
            status_color = (120, 180, 255)
        elif tech_locked:
            required = proj.get("required_tech")
            tech_name = TECHS.get(required, {}).get("name", required or "?")
            status_text = f"Needs {tech_name}"
            status_color = (160, 120, 120)
        else:
            status_text = f"{proj['cost']} prod"
            status_color = (200, 220, 240)
        status = self.body_font.render(status_text, True, status_color)
        screen.blit(status, status.get_rect(midright=(rect.right - 12, rect.centery)))

        if available:
            self._row_hits.append((proj_id, rect, True))

    def _draw_queue_panel(self, screen, build_state):
        sw, sh = self.game.screen_width, self.game.screen_height
        x = int(sw * self.LEFT_PANEL_W_FRAC) + 8
        top = self.HEADER_H
        w = sw - x - 24
        h = sh - top - 60
        rect = pygame.Rect(x, top, w, h)

        pygame.draw.rect(screen, (16, 18, 30), rect)
        pygame.draw.rect(screen, FIELD_BORDER, rect, 1)

        screen.blit(self.header_font.render("Build queue", True, TITLE_COLOR), (rect.x + 14, rect.y + 10))

        # Active project.
        y = rect.y + 42
        self._queue_hits = []
        if build_state is None or build_state.current_project is None:
            screen.blit(self.body_font.render("(idle)", True, HINT_COLOR), (rect.x + 18, y))
            y += 28
        else:
            current = build_state.current_project
            proj = PROJECTS.get(current, {})
            screen.blit(self.body_font.render("Building:", True, HINT_COLOR), (rect.x + 14, y))
            y += 20
            line = f"{proj.get('name', current)}  {build_state.progress}/{proj.get('cost', '?')}"
            screen.blit(self.body_font.render(line, True, SELECTED_RING), (rect.x + 18, y))
            y += 30

        if build_state is not None and build_state.queue:
            screen.blit(self.body_font.render("Next:", True, HINT_COLOR), (rect.x + 14, y))
            y += 22
            for i, pid in enumerate(build_state.queue):
                proj = PROJECTS.get(pid, {})
                row = pygame.Rect(rect.x + 14, y, rect.width - 28, 24)
                pygame.draw.rect(screen, (24, 28, 42), row)
                pygame.draw.rect(screen, (90, 100, 130), row, 1)
                screen.blit(self.body_font.render(proj.get("name", pid), True, TEXT_COLOR),
                            (row.x + 8, row.y + 4))
                # X button on the right for removal.
                xbtn = pygame.Rect(row.right - 22, row.y + 4, 16, row.height - 8)
                pygame.draw.rect(screen, (120, 40, 40), xbtn)
                pygame.draw.rect(screen, (220, 140, 140), xbtn, 1)
                x_lbl = self.small_font.render("x", True, (240, 220, 220))
                screen.blit(x_lbl, x_lbl.get_rect(center=xbtn.center))
                self._queue_hits.append(("remove", i, xbtn))
                y += row.height + 4

    def _draw_close_button(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

"""Colony screen — one planet's details, workers, and build queue.

Reached from SystemView by clicking a planet. Modelled after MOO2's
planet-info screen: pop + worker assignment at the top, completed
buildings + active build + queue in the middle, project picker at the
bottom (buildings row + ships row, tech-gated).

Esc returns to SystemView for the same star.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import (
    Planet, Orbiting, Position, Population, BuildState, Owner, Empire,
    Name, StarVisual,
)
from ecs.palette import planet_color, empire_color
from ecs.projects import PROJECTS
from ecs.planet_features import SPECIAL_FEATURES, RICHNESS_INDUSTRY_MULT, GRAVITY_OUTPUT_MULT
from ecs.db import (
    get_connection, update_planet_workers,
)


BG_COLOR = (10, 12, 24, 230)
TITLE_COLOR = (255, 230, 120)
HEADER_COLOR = (200, 200, 220)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
SELECTED_RING = (255, 230, 120)


class ColonyScene(Scene):
    WORKER_BTN_SIZE = (32, 32)
    WORKER_ROLES = [("farmers", "Farmers"), ("workers", "Workers"), ("scientists", "Scientists")]

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 14, bold=True)
        self.glyph_font = pygame.font.SysFont("Arial", 18, bold=True)

        # Hit rects rebuilt on layout.
        self._worker_widgets: list[tuple] = []  # (role, minus, plus)
        self._close_rect = pygame.Rect(0, 0, 0, 0)
        self._build_rect = pygame.Rect(0, 0, 0, 0)
        self._planet_entity: int | None = None

    # ------------------------------------------------------------------ lifecycle

    def on_enter(self):
        self._planet_entity = getattr(self.game, "selected_planet", None)
        # If we lost track of which planet, bail back.
        if self._planet_entity is None:
            self._return_to_system()
            return
        self._layout()

    def on_exit(self):
        self._planet_entity = None

    def _return_to_system(self):
        self.game.scenes.replace("system")

    def _return_to_galaxy(self):
        self.game.scenes.replace("galaxy")

    # ------------------------------------------------------------------ layout

    def _layout(self):
        sw, sh = self.game.screen_width, self.game.screen_height
        self._close_rect = pygame.Rect(sw - 100, 16, 80, 32)
        # Build button sits to the left of Close so the player can jump
        # to the categorised build screen.
        self._build_rect = pygame.Rect(sw - 100 - 110, 16, 100, 32)

        # Worker pickers across the upper third.
        self._worker_widgets.clear()
        btn_w, btn_h = self.WORKER_BTN_SIZE
        cluster_w = 200
        total_w = len(self.WORKER_ROLES) * cluster_w
        start_x = (sw - total_w) // 2
        # Worker pickers sit below the descriptor chip row.
        y = 168
        for i, (role, _label) in enumerate(self.WORKER_ROLES):
            cluster_x = start_x + i * cluster_w
            minus_rect = pygame.Rect(cluster_x + 40, y, btn_w, btn_h)
            plus_rect = pygame.Rect(cluster_x + cluster_w - 40 - btn_w, y, btn_w, btn_h)
            self._worker_widgets.append((role, minus_rect, plus_rect))

    # ------------------------------------------------------------------ helpers

    def _planet_components(self):
        cm = self.game.component_mgr
        if self._planet_entity is None:
            return None, None, None, None
        planet = cm.get_component(self._planet_entity, Planet)
        pop = cm.get_component(self._planet_entity, Population)
        build_state = cm.get_component(self._planet_entity, BuildState)
        owner = cm.get_component(self._planet_entity, Owner)
        return planet, pop, build_state, owner

    def _star_name(self) -> str:
        if self._planet_entity is None:
            return ""
        orbit = self.game.component_mgr.get_component(self._planet_entity, Orbiting)
        if orbit is None:
            return ""
        name = self.game.component_mgr.get_component(orbit.star_entity, Name)
        return name.value if name else ""

    def _player_empire_id(self):
        for _eid, empire in self.game.component_mgr.get_all(Empire):
            if empire.is_player:
                return empire.id
        return None

    def _player_owns_this(self, owner) -> bool:
        return owner is not None and owner.empire_id == self._player_empire_id()

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._return_to_system()
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        if self._close_rect.collidepoint(event.pos):
            self._return_to_galaxy()
            return
        if self._build_rect.collidepoint(event.pos):
            # Open the categorised build screen for this planet.
            self.game.scenes.replace("build")
            return

        # Worker +/- buttons
        for role, minus_rect, plus_rect in self._worker_widgets:
            if minus_rect.collidepoint(event.pos):
                self._try_shift_worker(role, -1)
                return
            if plus_rect.collidepoint(event.pos):
                self._try_shift_worker(role, +1)
                return

    def _try_shift_worker(self, role: str, delta: int):
        _planet, pop, _bs, owner = self._planet_components()
        if pop is None or not self._player_owns_this(owner):
            return

        other_order = [r for r in ("workers", "scientists", "farmers") if r != role]
        if delta > 0:
            for src in other_order:
                if getattr(pop, src) > 0:
                    setattr(pop, src, getattr(pop, src) - 1)
                    setattr(pop, role, getattr(pop, role) + 1)
                    break
            else:
                return
        else:
            if getattr(pop, role) <= 0:
                return
            setattr(pop, role, getattr(pop, role) - 1)
            setattr(pop, other_order[0], getattr(pop, other_order[0]) + 1)

        planet, _, _, _ = self._planet_components()
        if planet is not None:
            with get_connection() as conn:
                update_planet_workers(conn, planet.id, pop.farmers, pop.workers, pop.scientists)
                conn.commit()

    # Project selection moved to BuildScene (reached via Build button).

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height

        # Overlay
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))

        planet, pop, build_state, owner = self._planet_components()
        if planet is None:
            return

        self._draw_header(screen, planet, owner)
        self._draw_pop_block(screen, pop, owner)
        self._draw_worker_widgets(screen, pop, owner)
        self._draw_build_summary(screen, build_state)
        self._draw_build_button(screen, owner)
        self._draw_close_button(screen)

    def _draw_close_button(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

    def _draw_build_button(self, screen, owner):
        # Disabled if the player doesn't own this colony.
        owns = self._player_owns_this(owner)
        bg = (60, 100, 60) if owns else (40, 44, 56)
        border = (180, 220, 180) if owns else (90, 90, 110)
        fg = TEXT_COLOR if owns else (130, 130, 150)
        pygame.draw.rect(screen, bg, self._build_rect)
        pygame.draw.rect(screen, border, self._build_rect, 1)
        label = self.body_font.render("Build", True, fg)
        screen.blit(label, label.get_rect(center=self._build_rect.center))

    def _draw_header(self, screen, planet, owner):
        cm = self.game.component_mgr
        star_name = self._star_name()
        title = f"{star_name} - {planet.planet_type} {planet.size}"
        title_surf = self.title_font.render(title, True, TITLE_COLOR)
        screen.blit(title_surf, (24, 16))

        # Type dot
        pygame.draw.circle(screen, planet_color(planet.planet_type), (24 + 8, 60), 8)
        # Owner color bar
        if owner is not None:
            emp = next((e for _eid, e in cm.get_all(Empire) if e.id == owner.empire_id), None)
            if emp is not None:
                pygame.draw.rect(screen, empire_color(emp.color), pygame.Rect(48, 50, 8, 20))
                emp_label = self.header_font.render(emp.name, True, TEXT_COLOR)
                screen.blit(emp_label, (64, 52))
        else:
            screen.blit(self.header_font.render("Uncolonized", True, HINT_COLOR), (48, 52))

        # Descriptors line: Richness · Gravity · Specials. Sits under the
        # title and to the right of the type dot/owner.
        rich_mult = RICHNESS_INDUSTRY_MULT.get(planet.richness, 1.0)
        grav_mult = GRAVITY_OUTPUT_MULT.get(planet.gravity, 1.0)
        chips = [
            (f"{planet.richness} (Ind ×{rich_mult:g})",
             (200, 180, 120) if rich_mult >= 1.0 else (220, 140, 120)),
            (f"{planet.gravity} grav (×{grav_mult:g})",
             (180, 200, 220) if grav_mult >= 1.0 else (220, 140, 120)),
        ]
        for key in planet.special:
            meta = SPECIAL_FEATURES.get(key, {})
            chips.append((meta.get("name", key), (220, 200, 120)))

        cx = 24
        cy = 76
        for text, color in chips:
            chip = self.body_font.render(text, True, color)
            chip_rect = chip.get_rect()
            bg_rect = chip_rect.inflate(12, 6).move(cx, cy)
            pygame.draw.rect(screen, (30, 34, 50), bg_rect)
            pygame.draw.rect(screen, color, bg_rect, width=1)
            screen.blit(chip, (bg_rect.x + 6, bg_rect.y + 3))
            cx += bg_rect.width + 8

    def _draw_pop_block(self, screen, pop, owner):
        # Sits between the descriptor chips (~y=76-100) and worker widgets (y=168).
        if pop is None:
            screen.blit(self.header_font.render("No population", True, HINT_COLOR), (24, 124))
            return
        # 1 pop unit = 1 million inhabitants (MOO2 convention).
        line = f"Population: {pop.current}M / {pop.max}M    F:{pop.farmers}  W:{pop.workers}  S:{pop.scientists}"
        screen.blit(self.header_font.render(line, True, TEXT_COLOR), (24, 124))

    def _draw_worker_widgets(self, screen, pop, owner):
        editable = pop is not None and self._player_owns_this(owner)
        for role, minus_rect, plus_rect in self._worker_widgets:
            # Label above the cluster
            short = {"farmers": "Farmers", "workers": "Workers", "scientists": "Scientists"}[role]
            label_surf = self.body_font.render(short, True, TEXT_COLOR)
            mid_x = (minus_rect.left + plus_rect.right) // 2
            screen.blit(label_surf, label_surf.get_rect(midtop=(mid_x, minus_rect.top - 22)))

            count = getattr(pop, role) if pop is not None else 0
            value_surf = self.title_font.render(str(count), True, TEXT_COLOR)
            screen.blit(value_surf, value_surf.get_rect(center=(mid_x, minus_rect.centery)))

            for btn_rect, glyph in ((minus_rect, "−"), (plus_rect, "+")):
                bg = (60, 64, 96) if editable else (40, 44, 60)
                border = (180, 180, 220) if editable else (90, 90, 110)
                fg = TEXT_COLOR if editable else (130, 130, 150)
                pygame.draw.rect(screen, bg, btn_rect)
                pygame.draw.rect(screen, border, btn_rect, 1)
                gs = self.glyph_font.render(glyph, True, fg)
                screen.blit(gs, gs.get_rect(center=btn_rect.center))

    def _draw_build_summary(self, screen, build_state):
        x, y = 24, 220
        if build_state is None:
            screen.blit(self.body_font.render("No build state.", True, HINT_COLOR), (x, y))
            return
        # Completed
        if build_state.completed:
            names = [PROJECTS[pid]["name"] for pid in build_state.completed if pid in PROJECTS]
            completed_str = "Buildings: " + ", ".join(names)
        else:
            completed_str = "Buildings: (none)"
        screen.blit(self.body_font.render(completed_str, True, TEXT_COLOR), (x, y))

        # Active project
        if build_state.current_project:
            proj = PROJECTS.get(build_state.current_project, {})
            active = f"Building: {proj.get('name', build_state.current_project)} {build_state.progress}/{proj.get('cost', '?')}"
            screen.blit(self.body_font.render(active, True, (220, 200, 120)), (x, y + 22))
        else:
            screen.blit(self.body_font.render("Building: (idle)", True, HINT_COLOR), (x, y + 22))

        # Queue
        if build_state.queue:
            queue_names = [PROJECTS[pid]["name"] for pid in build_state.queue if pid in PROJECTS]
            queue_str = "Queue: " + " > ".join(queue_names)
            screen.blit(self.body_font.render(queue_str, True, (120, 180, 255)), (x, y + 44))


import pygame

from ecs.components import Planet, Orbiting, Position, Population, BuildState, Owner, Empire
from ecs.palette import planet_color
from ecs.projects import PROJECTS, PROJECT_ORDER
from ecs.db import get_connection, update_planet_build


SIZE_RADIUS = {
    "Tiny": 4,
    "Small": 6,
    "Medium": 9,
    "Large": 12,
    "Huge": 15,
}


class SystemView:
    """Overlay shown for one star system.

    Owned planets are clickable: clicking one focuses it and lets the
    player assign a construction project from the bottom-edge picker.
    """

    PROJECT_BTN_SIZE = (180, 60)
    PROJECT_BTN_GAP = 16

    def __init__(self, screen, component_mgr, star_id):
        self.screen = screen
        self.component_mgr = component_mgr
        self.star_id = star_id
        self.is_open = True
        self.close_button_rect = pygame.Rect(screen.get_width() - 100, 20, 80, 30)

        self.star_pos = component_mgr.get_component(star_id, Position)

        # Cache (entity_id, planet, center_pos, radius) for hit testing + draw.
        center = (screen.get_width() // 2, screen.get_height() // 2)
        self.planet_layout: list[tuple[int, Planet, tuple[int, int], int]] = []
        i = 0
        for entity_id, orbit in component_mgr.get_all(Orbiting):
            if orbit.star_entity != star_id:
                continue
            planet = component_mgr.get_component(entity_id, Planet)
            if planet is None:
                continue
            orbit_radius = 60 + i * 40
            pos = (center[0] + orbit_radius, center[1])
            radius = SIZE_RADIUS.get(planet.size, 8)
            self.planet_layout.append((entity_id, planet, pos, radius))
            i += 1

        # Default focus: first owned planet (the homeworld in a 1-empire system).
        self.selected_entity: int | None = self._first_owned_entity()

        # Lazily computed during draw; cached for hit testing.
        self._project_button_rects: list[tuple[str, pygame.Rect]] = []
        self._layout_project_buttons()

    def _first_owned_entity(self):
        for entity_id, _planet, _pos, _radius in self.planet_layout:
            if self.component_mgr.get_component(entity_id, Owner) is not None:
                return entity_id
        return None

    def _player_empire_id(self):
        for _eid, empire in self.component_mgr.get_all(Empire):
            if empire.is_player:
                return empire.id
        return None

    def _layout_project_buttons(self):
        btn_w, btn_h = self.PROJECT_BTN_SIZE
        gap = self.PROJECT_BTN_GAP
        total_w = len(PROJECT_ORDER) * btn_w + (len(PROJECT_ORDER) - 1) * gap
        start_x = (self.screen.get_width() - total_w) // 2
        y = self.screen.get_height() - btn_h - 24
        self._project_button_rects = []
        for i, project_id in enumerate(PROJECT_ORDER):
            rect = pygame.Rect(start_x + i * (btn_w + gap), y, btn_w, btn_h)
            self._project_button_rects.append((project_id, rect))

    # ---- input ------------------------------------------------------------

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_button_rect.collidepoint(event.pos):
                self.is_open = False
                return
            # Project picker
            for project_id, rect in self._project_button_rects:
                if rect.collidepoint(event.pos):
                    self._try_set_project(project_id)
                    return
            # Planet selection
            for entity_id, _planet, pos, radius in self.planet_layout:
                # Hit-box is slightly larger than the rendered planet for usability.
                hit = max(radius + 6, 12)
                dx = event.pos[0] - pos[0]
                dy = event.pos[1] - pos[1]
                if dx * dx + dy * dy <= hit * hit:
                    self.selected_entity = entity_id
                    return
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.is_open = False

    def _try_set_project(self, project_id):
        if self.selected_entity is None:
            return
        # Only the player can change projects on their own planets.
        player_id = self._player_empire_id()
        owner = self.component_mgr.get_component(self.selected_entity, Owner)
        if owner is None or owner.empire_id != player_id:
            return
        build_state = self.component_mgr.get_component(self.selected_entity, BuildState)
        if build_state is None:
            return
        # Already completed projects can't be queued again.
        if project_id in build_state.completed:
            return
        # Picking a new project mid-build resets progress.
        build_state.current_project = project_id
        build_state.progress = 0
        # Persist immediately: saving between pick and turn-end shouldn't
        # silently revert the choice.
        planet = self.component_mgr.get_component(self.selected_entity, Planet)
        if planet is not None:
            with get_connection() as conn:
                update_planet_build(conn, planet.id, project_id, 0)
                conn.commit()

    # ---- draw -------------------------------------------------------------

    def draw(self, font):
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))

        center = (self.screen.get_width() // 2, self.screen.get_height() // 2)
        # Star at center.
        pygame.draw.circle(overlay, (255, 230, 120), center, 12)

        for entity_id, planet, pos, radius in self.planet_layout:
            # Orbit ring.
            orbit_radius = pos[0] - center[0]
            pygame.draw.circle(overlay, (100, 100, 100), center, orbit_radius, 1)

            # Selection highlight ring (drawn behind so it doesn't overwrite the planet).
            if entity_id == self.selected_entity:
                pygame.draw.circle(overlay, (255, 230, 120), pos, radius + 5, 2)

            # Planet body.
            pygame.draw.circle(overlay, planet_color(planet.planet_type), pos, radius)

            self._draw_planet_labels(overlay, font, entity_id, planet, pos)

        # Close button.
        pygame.draw.rect(overlay, (150, 0, 0), self.close_button_rect)
        close_text = font.render("Close", True, (255, 255, 255))
        overlay.blit(close_text, (self.close_button_rect.x + 10, self.close_button_rect.y + 5))

        self._draw_project_picker(overlay, font)

        self.screen.blit(overlay, (0, 0))

    def _draw_planet_labels(self, overlay, font, entity_id, planet, pos):
        x, y = pos
        line_y = y + 14
        # Line 1: type + size shorthand.
        type_label = font.render(f"{planet.planet_type[:3]} {planet.size[:1]}", True, (255, 255, 255))
        overlay.blit(type_label, (x - 15, line_y))
        line_y += 14

        # Line 2: population (only for colonized planets).
        population = self.component_mgr.get_component(entity_id, Population)
        if population is not None:
            pop_label = font.render(f"{population.current}/{population.max}", True, (180, 220, 255))
            overlay.blit(pop_label, (x - 15, line_y))
            line_y += 14

        # Line 3: project status.
        build_state = self.component_mgr.get_component(entity_id, BuildState)
        if build_state is not None:
            if build_state.current_project:
                proj = PROJECTS.get(build_state.current_project, {})
                text = f"{proj.get('name', build_state.current_project)} {build_state.progress}/{proj.get('cost', '?')}"
                color = (220, 200, 120)
            elif build_state.completed:
                text = f"Built: {len(build_state.completed)}"
                color = (160, 200, 160)
            else:
                text = "(idle)"
                color = (160, 160, 160)
            overlay.blit(font.render(text, True, color), (x - 35, line_y))

    def _draw_project_picker(self, overlay, font):
        # Show what the picker targets so the player understands the click action.
        if self.selected_entity is not None:
            owner = self.component_mgr.get_component(self.selected_entity, Owner)
            build_state = self.component_mgr.get_component(self.selected_entity, BuildState)
            player_id = self._player_empire_id()
            owned_by_player = owner is not None and owner.empire_id == player_id
        else:
            owner = build_state = None
            owned_by_player = False

        # Hint line.
        if not owned_by_player:
            hint = font.render(
                "Click an owned planet to focus, then a project to build it.",
                True, (180, 180, 180),
            )
            overlay.blit(hint, (24, self.screen.get_height() - 110))

        for project_id, rect in self._project_button_rects:
            proj = PROJECTS[project_id]
            already_built = build_state is not None and project_id in build_state.completed
            currently_building = build_state is not None and build_state.current_project == project_id
            available = owned_by_player and not already_built

            bg = (60, 60, 90) if available else (40, 40, 50)
            border = (255, 230, 120) if currently_building else ((180, 180, 220) if available else (90, 90, 110))
            pygame.draw.rect(overlay, bg, rect)
            pygame.draw.rect(overlay, border, rect, width=2 if currently_building else 1)

            name_color = (240, 240, 240) if available else (120, 120, 140)
            name = font.render(proj["name"], True, name_color)
            overlay.blit(name, (rect.x + 12, rect.y + 8))

            cost_text = "BUILT" if already_built else f"Cost {proj['cost']}"
            cost = font.render(cost_text, True, (180, 220, 255) if available else (130, 130, 150))
            overlay.blit(cost, (rect.x + 12, rect.y + 26))

            desc = font.render(proj["description"], True, (200, 200, 200) if available else (110, 110, 130))
            overlay.blit(desc, (rect.x + 12, rect.y + 42))

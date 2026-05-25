import pygame

from ecs.components import Planet, Orbiting, Position, Population, BuildState, Owner, Empire, TechState
from ecs.palette import planet_color
from ecs.projects import PROJECTS, BUILDING_ORDER, SHIP_PROJECT_ORDER, project_is_available
from ecs.techs import TECHS
from ecs.db import get_connection, update_planet_build, update_planet_workers, save_planet_build_queue


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
    WORKER_BTN_SIZE = (28, 28)
    WORKER_ROLES = [("farmers", "F"), ("workers", "W"), ("scientists", "S")]

    def __init__(self, screen, component_mgr, star_id, logical_size=None):
        self.screen = screen
        self.component_mgr = component_mgr
        self.star_id = star_id
        self.is_open = True
        # Use the game's LOGICAL resolution for layout, not whatever the
        # surface reports. pygame.SCALED + FULLSCREEN can hand back a
        # surface with non-logical dimensions; relying on get_width() put
        # the orbital centre offset and the buttons in the wrong place.
        if logical_size is None:
            logical_size = (screen.get_width(), screen.get_height())
        self.logical_w, self.logical_h = logical_size

        self.close_button_rect = pygame.Rect(self.logical_w - 100, 20, 80, 30)

        self.star_pos = component_mgr.get_component(star_id, Position)

        # Cache (entity_id, planet, center_pos, radius) for hit testing + draw.
        center = (self.logical_w // 2, self.logical_h // 2)
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

        # Cached for hit testing; computed once.
        self._project_button_rects: list[tuple[str, pygame.Rect]] = []
        # Each entry: (role, minus_rect, plus_rect, value_pos, label_pos)
        self._worker_widgets: list[tuple] = []
        self._layout_project_buttons()
        self._layout_worker_widgets()

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

    def _player_unlocked_techs(self) -> set[str]:
        player_id = self._player_empire_id()
        if player_id is None:
            return set()
        for _eid, tech in self.component_mgr.get_all(TechState):
            if tech.empire_id == player_id:
                return set(tech.unlocked)
        return set()

    def _layout_project_buttons(self):
        """Two rows: ships on top, buildings beneath, both centered."""
        btn_w, btn_h = self.PROJECT_BTN_SIZE
        gap = self.PROJECT_BTN_GAP
        self._project_button_rects = []
        sw = self.logical_w

        def _row(ids, y):
            total_w = len(ids) * btn_w + (len(ids) - 1) * gap
            start_x = (sw - total_w) // 2
            for i, pid in enumerate(ids):
                self._project_button_rects.append((pid, pygame.Rect(start_x + i * (btn_w + gap), y, btn_w, btn_h)))

        buildings_y = self.logical_h - btn_h - 24
        ships_y = buildings_y - btn_h - 12
        _row(SHIP_PROJECT_ORDER, ships_y)
        _row(BUILDING_ORDER, buildings_y)

    def _layout_worker_widgets(self):
        """Three F/W/S clusters sitting above the project picker row."""
        sw = self.logical_w
        btn_w, btn_h = self.WORKER_BTN_SIZE
        label_w = 16
        value_w = 28
        gap = 6
        cluster_w = label_w + gap + btn_w + gap + value_w + gap + btn_w
        spacing = 50
        total_w = len(self.WORKER_ROLES) * cluster_w + (len(self.WORKER_ROLES) - 1) * spacing
        start_x = (sw - total_w) // 2
        # Above the two project-button rows.
        proj_h = self.PROJECT_BTN_SIZE[1]
        y = self.logical_h - proj_h - 24 - proj_h - 12 - btn_h - 24
        self._worker_widgets = []
        for i, (role, _label) in enumerate(self.WORKER_ROLES):
            cluster_x = start_x + i * (cluster_w + spacing)
            label_pos = (cluster_x, y + (btn_h - 16) // 2)
            minus_rect = pygame.Rect(cluster_x + label_w + gap, y, btn_w, btn_h)
            value_pos = (minus_rect.right + gap, y + (btn_h - 16) // 2)
            plus_rect = pygame.Rect(value_pos[0] + value_w + gap, y, btn_w, btn_h)
            self._worker_widgets.append((role, minus_rect, plus_rect, value_pos, label_pos))

    # ---- input ------------------------------------------------------------

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_button_rect.collidepoint(event.pos):
                self.is_open = False
                return
            # Worker assignment +/-
            for role, minus_rect, plus_rect, _v, _l in self._worker_widgets:
                if minus_rect.collidepoint(event.pos):
                    self._try_shift_worker(role, -1)
                    return
                if plus_rect.collidepoint(event.pos):
                    self._try_shift_worker(role, +1)
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

    def _try_shift_worker(self, role: str, delta: int):
        """Move one pop into or out of `role`. Other roles donate or receive
        in priority order: workers > scientists > farmers.

        Only player-owned planets are editable.
        """
        if self.selected_entity is None or delta == 0:
            return
        player_id = self._player_empire_id()
        owner = self.component_mgr.get_component(self.selected_entity, Owner)
        if owner is None or owner.empire_id != player_id:
            return
        pop = self.component_mgr.get_component(self.selected_entity, Population)
        if pop is None:
            return

        other_order = [r for r in ("workers", "scientists", "farmers") if r != role]
        if delta > 0:
            # Take 1 from the first non-`role` that has > 0.
            for src in other_order:
                if getattr(pop, src) > 0:
                    setattr(pop, src, getattr(pop, src) - 1)
                    setattr(pop, role, getattr(pop, role) + 1)
                    break
            else:
                return  # no donor available
        else:
            if getattr(pop, role) <= 0:
                return
            setattr(pop, role, getattr(pop, role) - 1)
            setattr(pop, other_order[0], getattr(pop, other_order[0]) + 1)

        # Persist immediately so saves between adjustments and turn-end
        # don't lose the assignment.
        planet = self.component_mgr.get_component(self.selected_entity, Planet)
        if planet is not None:
            with get_connection() as conn:
                update_planet_workers(conn, planet.id, pop.farmers, pop.workers, pop.scientists)
                conn.commit()

    def _try_set_project(self, project_id):
        """Clicking a project button:

        - If completed already: no-op.
        - If currently building it: no-op (can't cancel mid-build).
        - If already queued: remove from queue (toggle off).
        - Else if nothing is being built: start it.
        - Else: append to queue.
        """
        if self.selected_entity is None:
            return
        player_id = self._player_empire_id()
        owner = self.component_mgr.get_component(self.selected_entity, Owner)
        if owner is None or owner.empire_id != player_id:
            return
        build_state = self.component_mgr.get_component(self.selected_entity, BuildState)
        if build_state is None:
            return
        if project_id in build_state.completed:
            return
        # Tech-locked projects can't be queued.
        if not project_is_available(project_id, self._player_unlocked_techs()):
            return

        is_ship = PROJECTS.get(project_id, {}).get("type") == "ship"

        # Buildings: clicking the active one is a no-op (can't cancel).
        # Ships can be queued repeatedly even while one is building.
        if not is_ship and build_state.current_project == project_id:
            return

        queue_changed = False
        current_changed = False
        # Ships always append (duplicates OK) so the player can stockpile.
        if is_ship:
            if build_state.current_project is None:
                build_state.current_project = project_id
                current_changed = True
            else:
                build_state.queue.append(project_id)
                queue_changed = True
        elif project_id in build_state.queue:
            build_state.queue.remove(project_id)
            queue_changed = True
        elif build_state.current_project is None:
            build_state.current_project = project_id
            current_changed = True
        else:
            build_state.queue.append(project_id)
            queue_changed = True

        planet = self.component_mgr.get_component(self.selected_entity, Planet)
        if planet is not None:
            with get_connection() as conn:
                if current_changed:
                    update_planet_build(conn, planet.id, build_state.current_project, build_state.progress)
                if queue_changed:
                    save_planet_build_queue(conn, planet.id, list(build_state.queue))
                conn.commit()

    # ---- draw -------------------------------------------------------------

    def draw(self, font):
        overlay = pygame.Surface((self.logical_w, self.logical_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))

        center = (self.logical_w // 2, self.logical_h // 2)
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

        self._draw_worker_widgets(overlay, font)
        self._draw_project_picker(overlay, font)

        self.screen.blit(overlay, (0, 0))

    def _draw_planet_labels(self, overlay, font, entity_id, planet, pos):
        x, y = pos
        line_y = y + 14
        # Line 1: type + size shorthand.
        type_label = font.render(f"{planet.planet_type[:3]} {planet.size[:1]}", True, (255, 255, 255))
        overlay.blit(type_label, (x - 15, line_y))
        line_y += 14

        # Line 2: population + worker split for colonized planets.
        population = self.component_mgr.get_component(entity_id, Population)
        if population is not None:
            pop_label = font.render(
                f"{population.current}/{population.max}  {population.farmers}/{population.workers}/{population.scientists}",
                True, (180, 220, 255),
            )
            overlay.blit(pop_label, (x - 30, line_y))
            line_y += 14

        # Line 3: project status.
        build_state = self.component_mgr.get_component(entity_id, BuildState)
        if build_state is not None:
            if build_state.current_project:
                proj = PROJECTS.get(build_state.current_project, {})
                text = f"{proj.get('name', build_state.current_project)} {build_state.progress}/{proj.get('cost', '?')}"
                if build_state.queue:
                    text += f" +{len(build_state.queue)}"
                color = (220, 200, 120)
            elif build_state.completed:
                text = f"Built: {len(build_state.completed)}"
                color = (160, 200, 160)
            else:
                text = "(idle)"
                color = (160, 160, 160)
            overlay.blit(font.render(text, True, color), (x - 35, line_y))

    def _draw_worker_widgets(self, overlay, font):
        pop = (
            self.component_mgr.get_component(self.selected_entity, Population)
            if self.selected_entity is not None else None
        )
        owner = (
            self.component_mgr.get_component(self.selected_entity, Owner)
            if self.selected_entity is not None else None
        )
        player_id = self._player_empire_id()
        editable = pop is not None and owner is not None and owner.empire_id == player_id

        for role, minus_rect, plus_rect, value_pos, label_pos in self._worker_widgets:
            # Labels and current value reflect the selected planet's pop.
            short = {"farmers": "F", "workers": "W", "scientists": "S"}[role]
            overlay.blit(font.render(short, True, (200, 200, 200)), label_pos)
            value = getattr(pop, role) if pop is not None else 0
            value_surf = font.render(str(value), True, (240, 240, 240))
            overlay.blit(value_surf, value_pos)

            for btn_rect, glyph in ((minus_rect, "−"), (plus_rect, "+")):
                bg = (60, 60, 90) if editable else (40, 40, 50)
                border = (180, 180, 220) if editable else (90, 90, 110)
                pygame.draw.rect(overlay, bg, btn_rect)
                pygame.draw.rect(overlay, border, btn_rect, width=1)
                glyph_color = (240, 240, 240) if editable else (120, 120, 140)
                glyph_surf = font.render(glyph, True, glyph_color)
                overlay.blit(glyph_surf, glyph_surf.get_rect(center=btn_rect.center))

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
            overlay.blit(hint, (24, self.logical_h - 110))

        unlocked = self._player_unlocked_techs()
        for project_id, rect in self._project_button_rects:
            proj = PROJECTS[project_id]
            already_built = build_state is not None and project_id in build_state.completed
            currently_building = build_state is not None and build_state.current_project == project_id
            queue_index = (
                build_state.queue.index(project_id)
                if build_state is not None and project_id in build_state.queue
                else None
            )
            queued = queue_index is not None
            tech_locked = not project_is_available(project_id, unlocked)
            available = owned_by_player and not already_built and not tech_locked

            bg = (60, 60, 90) if available else (40, 40, 50)
            if currently_building:
                border = (255, 230, 120)
            elif queued:
                border = (120, 180, 255)
            elif available:
                border = (180, 180, 220)
            else:
                border = (90, 90, 110)
            pygame.draw.rect(overlay, bg, rect)
            pygame.draw.rect(overlay, border, rect, width=2 if (currently_building or queued) else 1)

            name_color = (240, 240, 240) if available else (120, 120, 140)
            name = font.render(proj["name"], True, name_color)
            overlay.blit(name, (rect.x + 12, rect.y + 8))

            if already_built:
                cost_text = "BUILT"
            elif currently_building:
                cost_text = "BUILDING"
            elif queued:
                cost_text = f"QUEUED #{queue_index + 2}"  # +2: current_project is #1, queue starts at #2
            elif tech_locked:
                required = proj.get("required_tech")
                cost_text = f"Locked: {TECHS.get(required, {}).get('name', required)}"
            else:
                cost_text = f"Cost {proj['cost']}"
            cost = font.render(cost_text, True, (180, 220, 255) if available else (130, 130, 150))
            overlay.blit(cost, (rect.x + 12, rect.y + 26))

            desc = font.render(proj["description"], True, (200, 200, 200) if available else (110, 110, 130))
            overlay.blit(desc, (rect.x + 12, rect.y + 42))

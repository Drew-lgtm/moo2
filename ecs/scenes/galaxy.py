import pygame

from ecs.scene import Scene
from ecs.components import (
    Position, Name, StarVisual, Ship, ShipOwner, ShipAt, ShipInTransit,
    Empire, Owner, Orbiting,
)
from ecs.palette import empire_color
from ecs.economy import empire_per_turn
from ecs.fleet import start_fleet_movement, turns_for, empire_speed_bonus
from assets.loader import load_image


class GalaxyScene(Scene):
    """Main galaxy view: stars on the background, bottom UI bar."""

    def __init__(self, game):
        super().__init__(game)
        # entity_id -> scaled pygame.Surface, rebuilt on_enter from current StarVisuals.
        self._star_surfaces: dict[int, pygame.Surface] = {}
        # Star entity holding the player's currently-selected fleet, if any.
        self.selected_fleet_star: int | None = None
        # ship_class -> count the player has chosen to dispatch.
        self.selected_counts: dict[str, int] = {}
        # Per-frame fleet-picker hit rects: (action, ship_class, rect).
        # action is "minus" or "plus".
        self._fleet_picker_hits: list[tuple[str, str, pygame.Rect]] = []
        self._picker_font_bold: pygame.font.Font | None = None
        # Larger fonts used for galaxy-view labels (star names, fleet
        # badges, HUD). Bumped a couple sizes above the 14pt game font
        # so they read better against the busy background.
        self._label_font: pygame.font.Font | None = None
        self._label_font_bold: pygame.font.Font | None = None

    def on_enter(self):
        self._preload_star_surfaces()
        if self._picker_font_bold is None:
            self._picker_font_bold = pygame.font.SysFont("Arial", 14, bold=True)
        # Star labels: 18pt bold for everything. Bold strokes survive the
        # non-integer scaling that pygame.SCALED does on most laptop
        # screens, where 1px strokes in regular weight get rounded away
        # (e.g. the left leg of 'n' or the curve of '(' would vanish).
        if self._label_font is None:
            self._label_font = pygame.font.SysFont("Arial", 18, bold=True)
        if self._label_font_bold is None:
            self._label_font_bold = pygame.font.SysFont("Arial", 18, bold=True)

    def _preload_star_surfaces(self):
        self._star_surfaces.clear()
        for entity_id, visual in self.game.component_mgr.get_all(StarVisual):
            self._star_surfaces[entity_id] = load_image(
                f"stars/{visual.image_name}", size=(visual.size, visual.size)
            )

    def handle_event(self, event):
        self.game.ui_bar.handle_event(event)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.selected_fleet_star is not None:
                    self.selected_fleet_star = None
                    self.selected_counts = {}
                else:
                    self.game.scenes.replace("pause")
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            # Fleet-picker +/- buttons get first crack so they don't get
            # eclipsed by star clicks behind them.
            if event.button == 1 and self.selected_fleet_star is not None:
                for action, class_id, rect in self._fleet_picker_hits:
                    if rect.collidepoint(event.pos):
                        self._adjust_count(class_id, +1 if action == "plus" else -1)
                        return

            star = self._star_at(event.pos)
            if event.button == 1 and star is not None:
                # Left-click: open System View as before.
                self.game.selected_star = star
                self.game.scenes.replace("system")
            elif event.button == 3 and star is not None:
                # Right-click: select/move fleet.
                self._handle_fleet_click(star)

    def _adjust_count(self, ship_class: str, delta: int):
        max_count = self._max_counts_for(self.selected_fleet_star).get(ship_class, 0)
        current = self.selected_counts.get(ship_class, 0)
        self.selected_counts[ship_class] = max(0, min(max_count, current + delta))

    def _handle_fleet_click(self, star_entity: int):
        """Right-click flow:

        - If we're not selecting a fleet yet and this star has player ships:
          select it; default-fill selected_counts to MAX for every class.
        - If we're already selecting from this star: deselect (toggle).
        - If we're selecting from another star: dispatch the chosen
          ship counts to the new star.
        """
        player = self.game.player_empire()
        if player is None:
            return
        if self.selected_fleet_star is None:
            if self._max_counts_for(star_entity):
                self.selected_fleet_star = star_entity
                self.selected_counts = self._max_counts_for(star_entity).copy()
        elif self.selected_fleet_star == star_entity:
            self.selected_fleet_star = None
            self.selected_counts = {}
        else:
            self._dispatch_selected(star_entity)
            self.selected_fleet_star = None
            self.selected_counts = {}

    def _dispatch_selected(self, dest_star_entity: int):
        """Send selected_counts ships from the source star to the
        destination, picking the right ship classes."""
        cm = self.game.component_mgr
        player = self.game.player_empire()
        if player is None or self.selected_fleet_star is None:
            return
        # Group available ships at source by class.
        by_class: dict[str, list[int]] = {}
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != self.selected_fleet_star:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            ship = cm.get_component(ship_entity, Ship)
            if owner is None or ship is None or owner.empire_id != player.id:
                continue
            by_class.setdefault(ship.ship_class, []).append(ship_entity)

        to_send: list[int] = []
        for class_id, count in self.selected_counts.items():
            available = by_class.get(class_id, [])
            to_send.extend(available[:count])

        if to_send:
            start_fleet_movement(cm, to_send, self.selected_fleet_star, dest_star_entity)

    def _max_counts_for(self, star_entity: int | None) -> dict[str, int]:
        """How many player ships of each class are parked at this star."""
        if star_entity is None:
            return {}
        cm = self.game.component_mgr
        player = self.game.player_empire()
        if player is None:
            return {}
        counts: dict[str, int] = {}
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != star_entity:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            ship = cm.get_component(ship_entity, Ship)
            if owner is None or ship is None or owner.empire_id != player.id:
                continue
            counts[ship.ship_class] = counts.get(ship.ship_class, 0) + 1
        return counts

    def _star_at(self, pos):
        # Right panel covers the strip past play_area_width; positions
        # there shouldn't resolve to a star even if an old save placed
        # one in that region.
        if pos[0] >= self.game.play_area_width:
            return None
        mouse_x, mouse_y = pos
        for entity_id, position in self.game.component_mgr.get_all(Position):
            visual = self.game.component_mgr.get_component(entity_id, StarVisual)
            if not visual:
                continue
            dx = mouse_x - position.x
            dy = mouse_y - position.y
            if (dx * dx + dy * dy) ** 0.5 < visual.size // 2:
                return entity_id
        return None

    def _build_star_ownership(self) -> dict[int, list[tuple[tuple[int, int, int], int]]]:
        """For each star, return a list of (empire_color_rgb, count) for
        empires that own at least one planet at that star. Empty planets
        (no Owner component) don't contribute.
        """
        cm = self.game.component_mgr
        empire_color_by_id = {emp.id: emp.color for _e, emp in cm.get_all(Empire)}
        counts: dict[int, dict[int, int]] = {}
        for planet_entity, owner in cm.get_all(Owner):
            orbit = cm.get_component(planet_entity, Orbiting)
            if orbit is None:
                continue
            star_bucket = counts.setdefault(orbit.star_entity, {})
            star_bucket[owner.empire_id] = star_bucket.get(owner.empire_id, 0) + 1

        result: dict[int, list[tuple[tuple[int, int, int], int]]] = {}
        for star_entity, by_empire in counts.items():
            ratios = [
                (empire_color(empire_color_by_id.get(eid, "blue")), c)
                for eid, c in by_empire.items()
            ]
            ratios.sort(key=lambda r: -r[1])
            result[star_entity] = ratios
        return result

    @staticmethod
    def _render_outlined(font, text: str, fg, outline=(0, 0, 0)):
        """Return a Surface with `text` drawn in fg color and a 1px dark
        outline around every glyph. The outline gives the label
        contrast on both light and dark backdrops."""
        base = font.render(text, True, fg)
        outline_surf = font.render(text, True, outline)
        w, h = base.get_size()
        surf = pygame.Surface((w + 2, h + 2), pygame.SRCALPHA)
        # 8-way 1px outline.
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                surf.blit(outline_surf, (1 + dx, 1 + dy))
        surf.blit(base, (1, 1))
        return surf

    def _draw_star_label(self, screen, name_str, star_class, position, ratios):
        """Bottom label under a star. White + non-bold for unowned stars;
        bold + per-letter empire colors when one or more empires hold
        planets here. The "(Class)" suffix stays white. Both passes get
        a 1px black outline so the label reads on every background."""
        font_bold = self._label_font_bold or self.game.font
        font_norm = self._label_font or self.game.font
        suffix = f" ({star_class})"

        if not ratios:
            text = self._render_outlined(font_norm, f"{name_str}{suffix}", (255, 255, 255))
            rect = text.get_rect(center=(position.x, position.y + 24))
            rect.clamp_ip(screen.get_rect())
            screen.blit(text, rect)
            return

        # Per-letter color: each letter falls into one empire's bucket
        # based on its midpoint position vs cumulative ownership ratios.
        total = sum(c for _rgb, c in ratios)
        n = max(1, len(name_str))
        letter_surfaces: list[pygame.Surface] = []
        for i, ch in enumerate(name_str):
            pos_frac = (i + 0.5) / n
            cum = 0.0
            color = ratios[-1][0]
            for rgb, count in ratios:
                cum += count / total
                if pos_frac <= cum:
                    color = rgb
                    break
            letter_surfaces.append(self._render_outlined(font_bold, ch, color))

        suffix_surface = self._render_outlined(font_norm, suffix, (220, 220, 220))
        total_w = sum(s.get_width() for s in letter_surfaces) + suffix_surface.get_width()
        x = position.x - total_w // 2
        y = position.y + 24
        # Clamp horizontally so labels near the edge don't run off-screen.
        x = max(0, min(x, screen.get_width() - total_w))
        for surf in letter_surfaces:
            screen.blit(surf, (x, y))
            x += surf.get_width()
        screen.blit(suffix_surface, (x, y))

    def draw(self, screen):
        cm = self.game.component_mgr
        font = self.game.font
        # Build owner ratios per star once per frame (O(planets) total).
        star_ownership = self._build_star_ownership()

        for entity_id, position in cm.get_all(Position):
            visual = cm.get_component(entity_id, StarVisual)
            surface = self._star_surfaces.get(entity_id)
            if visual and surface is not None:
                screen.blit(surface, (position.x - visual.size // 2, position.y - visual.size // 2))

            name = cm.get_component(entity_id, Name)
            if name and visual:
                self._draw_star_label(
                    screen, name.value, visual.star_class, position,
                    star_ownership.get(entity_id, []),
                )

        self._draw_in_transit_ships(screen)
        self._draw_selection_ring(screen)
        self._draw_fleet_pathing(screen)
        self._draw_fleet_badges(screen)
        self._draw_right_panel(screen)
        self.game.ui_bar.draw(screen)

    @staticmethod
    def _draw_dashed_line(screen, color, start, end, dash_len=12, gap_len=8, width=2):
        import math as _math
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = _math.hypot(dx, dy)
        if distance < 1:
            return
        ux, uy = dx / distance, dy / distance
        pos = 0
        while pos < distance:
            seg_end = min(pos + dash_len, distance)
            pygame.draw.line(
                screen, color,
                (int(start[0] + ux * pos), int(start[1] + uy * pos)),
                (int(start[0] + ux * seg_end), int(start[1] + uy * seg_end)),
                width,
            )
            pos = seg_end + gap_len

    def _draw_fleet_pathing(self, screen):
        """While a fleet is selected, draw a dashed line from the source
        star to the hovered destination (or to the cursor if not over a
        star). Shows the slowest selected ship's arrival time."""
        if self.selected_fleet_star is None:
            return
        cm = self.game.component_mgr
        src_pos = cm.get_component(self.selected_fleet_star, Position)
        if src_pos is None:
            return

        mouse_pos = pygame.mouse.get_pos()
        hovered_star = self._star_at(mouse_pos)

        if hovered_star is None or hovered_star == self.selected_fleet_star:
            end_xy = mouse_pos
            eta = None
        else:
            dst_pos = cm.get_component(hovered_star, Position)
            if dst_pos is None:
                return
            end_xy = (dst_pos.x, dst_pos.y)
            eta = self._slowest_eta(src_pos, dst_pos)

        self._draw_dashed_line(screen, (255, 230, 120), (src_pos.x, src_pos.y), end_xy)

        if eta is not None:
            label = self._render_outlined(
                self._label_font or self.game.font,
                f"{eta} turn{'s' if eta != 1 else ''}",
                (255, 230, 120),
            )
            mid_x = (src_pos.x + end_xy[0]) // 2
            mid_y = (src_pos.y + end_xy[1]) // 2 - 10
            rect = label.get_rect(center=(mid_x, mid_y))
            screen.blit(label, rect)

    def _slowest_eta(self, src_pos, dst_pos) -> int | None:
        """Max turns_for across selected ship classes (with count > 0)."""
        player = self.game.player_empire()
        bonus = (
            empire_speed_bonus(self.game.component_mgr, player.id)
            if player is not None else 0
        )
        worst = 0
        for class_id, count in self.selected_counts.items():
            if count <= 0:
                continue
            t = turns_for(class_id, src_pos, dst_pos, bonus)
            if t > worst:
                worst = t
        return worst if worst > 0 else None

    def _draw_right_panel(self, screen):
        """MOO2-style sidebar: empire summary at top, contextual section
        below (selected-fleet picker, hovered-star info, or empty)."""
        self._fleet_picker_hits = []
        sw = self.game.screen_width
        panel_w = self.game.GALAXY_RIGHT_PANEL_WIDTH
        panel_x = sw - panel_w
        panel_h = self.game.play_area_height
        panel = pygame.Rect(panel_x, 0, panel_w, panel_h)

        # Solid backing — distinct enough from the map that the eye knows
        # this is UI, not space.
        pygame.draw.rect(screen, (18, 20, 32), panel)
        pygame.draw.line(screen, (90, 100, 140), (panel.x, panel.y), (panel.x, panel.bottom), 2)

        y = self._draw_empire_summary(screen, panel) + 8
        pygame.draw.line(screen, (60, 64, 90), (panel.x + 8, y), (panel.right - 8, y), 1)
        y += 8

        if self.selected_fleet_star is not None:
            self._draw_fleet_picker_section(screen, panel, y)
        else:
            self._draw_hover_info_section(screen, panel, y)

    def _draw_empire_summary(self, screen, panel: pygame.Rect) -> int:
        """Render the top section. Returns the y just below it."""
        font = self._label_font or self.game.font
        font_bold = self._label_font_bold or self.game.font
        galaxy = self.game.galaxy
        player = self.game.player_empire()
        x = panel.x + 12
        y = panel.y + 12

        if player is None:
            label = font.render(f"Turn {galaxy.turn}" if galaxy else "—", True, (240, 240, 240))
            screen.blit(label, (x, y))
            return y + label.get_height()

        # Empire color bar + name.
        pygame.draw.rect(screen, empire_color(player.color), pygame.Rect(x, y + 2, 6, 22))
        name_surf = font_bold.render(player.name, True, (255, 230, 120))
        screen.blit(name_surf, (x + 14, y))
        y += name_surf.get_height() + 6

        per_turn = empire_per_turn(self.game.component_mgr, player.id)
        food = per_turn["food_balance"]
        rows = [
            ("BC",       f"{player.bc} (+{per_turn['bc']})"),
            ("Industry", f"+{per_turn['industry']}"),
            ("Research", f"{player.research_points} (+{per_turn['research']})"),
            ("Food",     f"{food:+d}"),
            ("Turn",     str(galaxy.turn) if galaxy else "—"),
        ]
        # Two-column layout: label / value
        for label, value in rows:
            screen.blit(font.render(label, True, (180, 200, 220)), (x, y))
            v = font_bold.render(value, True, (240, 240, 240))
            screen.blit(v, (panel.right - 12 - v.get_width(), y))
            y += font.get_height() + 4
        return y

    def _draw_hover_info_section(self, screen, panel: pygame.Rect, y: int):
        """Show the star (or empty space) under the cursor."""
        font = self._label_font or self.game.font
        font_bold = self._label_font_bold or self.game.font
        x = panel.x + 12
        mouse_pos = pygame.mouse.get_pos()
        if mouse_pos[0] >= panel.x:
            star = None  # cursor over the panel itself
        else:
            star = self._star_at(mouse_pos)

        screen.blit(font.render("Hover", True, (150, 170, 200)), (x, y))
        y += font.get_height() + 4

        if star is None:
            screen.blit(font.render("(no star)", True, (130, 130, 150)), (x, y))
            return

        cm = self.game.component_mgr
        name = cm.get_component(star, Name)
        visual = cm.get_component(star, StarVisual)
        title = (name.value if name else "?") + (f" ({visual.star_class})" if visual else "")
        screen.blit(font_bold.render(title, True, (240, 240, 240)), (x, y))
        y += font.get_height() + 4

        # Planets at this star, grouped by owner.
        planet_count = 0
        owned_per_empire: dict[int, int] = {}
        for planet_entity, orbit in cm.get_all(Orbiting):
            if orbit.star_entity != star:
                continue
            planet_count += 1
            owner = cm.get_component(planet_entity, Owner)
            if owner is not None:
                owned_per_empire[owner.empire_id] = owned_per_empire.get(owner.empire_id, 0) + 1

        screen.blit(font.render(f"Planets: {planet_count}", True, (240, 240, 240)), (x, y))
        y += font.get_height() + 2

        if owned_per_empire:
            empire_info = {emp.id: (emp.name, emp.color) for _e, emp in cm.get_all(Empire)}
            for eid, count in sorted(owned_per_empire.items()):
                ename, ecolor = empire_info.get(eid, (f"Empire {eid}", "blue"))
                pygame.draw.rect(screen, empire_color(ecolor), pygame.Rect(x, y + 4, 6, 14))
                screen.blit(font.render(f"{ename}: {count}", True, (220, 220, 220)), (x + 12, y))
                y += font.get_height() + 2

        # Ships at this star, by empire.
        ships_per_empire: dict[int, int] = {}
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != star:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            if owner is not None:
                ships_per_empire[owner.empire_id] = ships_per_empire.get(owner.empire_id, 0) + 1
        if ships_per_empire:
            y += 6
            screen.blit(font.render("Fleets:", True, (180, 200, 220)), (x, y))
            y += font.get_height() + 2
            empire_info = {emp.id: (emp.name, emp.color) for _e, emp in cm.get_all(Empire)}
            for eid, count in sorted(ships_per_empire.items()):
                ename, ecolor = empire_info.get(eid, (f"Empire {eid}", "blue"))
                pygame.draw.rect(screen, empire_color(ecolor), pygame.Rect(x, y + 4, 6, 14))
                screen.blit(font.render(f"{ename}: {count}", True, (220, 220, 220)), (x + 12, y))
                y += font.get_height() + 2

    def _draw_fleet_picker_section(self, screen, panel: pygame.Rect, y_start: int):
        """Per-class +/- counts for the selected fleet. Lives in the
        right panel; populates self._fleet_picker_hits for click handling."""
        cm = self.game.component_mgr
        max_counts = self._max_counts_for(self.selected_fleet_star)
        if not max_counts:
            return
        font = self._label_font or self.game.font
        font_bold = self._label_font_bold or self.game.font

        star_name = cm.get_component(self.selected_fleet_star, Name)
        title = f"Fleet at {star_name.value}" if star_name else "Selected fleet"

        x = panel.x + 12
        screen.blit(font_bold.render(title, True, (255, 230, 120)), (x, y_start))
        y = y_start + font_bold.get_height() + 6

        row_h = 26
        btn_w = 26
        for class_id, max_n in sorted(max_counts.items()):
            count = self.selected_counts.get(class_id, max_n)
            name = class_id.replace("ship_", "").capitalize()
            screen.blit(font.render(name, True, (240, 240, 240)), (x, y + 4))

            minus_rect = pygame.Rect(panel.right - 12 - btn_w - 36 - btn_w, y, btn_w, row_h - 4)
            plus_rect = pygame.Rect(panel.right - 12 - btn_w, y, btn_w, row_h - 4)
            pygame.draw.rect(screen, (60, 64, 96), minus_rect)
            pygame.draw.rect(screen, (60, 64, 96), plus_rect)
            pygame.draw.rect(screen, (180, 180, 220), minus_rect, 1)
            pygame.draw.rect(screen, (180, 180, 220), plus_rect, 1)
            for rect, glyph in ((minus_rect, "−"), (plus_rect, "+")):
                gs = font_bold.render(glyph, True, (240, 240, 240))
                screen.blit(gs, gs.get_rect(center=rect.center))

            count_text = font.render(f"{count}/{max_n}", True, (240, 240, 240))
            screen.blit(
                count_text,
                count_text.get_rect(midleft=(minus_rect.right + 8, minus_rect.centery)),
            )
            self._fleet_picker_hits.append(("minus", class_id, minus_rect))
            self._fleet_picker_hits.append(("plus", class_id, plus_rect))
            y += row_h

        y += 6
        hint = font.render("Right-click target star to send.", True, (180, 180, 180))
        screen.blit(hint, (x, y))
        y += font.get_height() + 2
        hint2 = font.render("Esc to cancel.", True, (160, 160, 180))
        screen.blit(hint2, (x, y))

    def _draw_selection_ring(self, screen):
        if self.selected_fleet_star is None:
            return
        cm = self.game.component_mgr
        pos = cm.get_component(self.selected_fleet_star, Position)
        visual = cm.get_component(self.selected_fleet_star, StarVisual)
        if pos is None or visual is None:
            return
        pygame.draw.circle(screen, (255, 230, 120), (pos.x, pos.y), visual.size // 2 + 6, 2)

    def _draw_in_transit_ships(self, screen):
        """Render a small empire-colored dot along each transit line at
        progress = 1 - turns_remaining / total_turns."""
        cm = self.game.component_mgr
        empire_colors_by_id = {emp.id: emp.color for _eid, emp in cm.get_all(Empire)}
        for ship_entity, transit in cm.get_all(ShipInTransit):
            from_pos = cm.get_component(transit.from_star_entity, Position)
            to_pos = cm.get_component(transit.to_star_entity, Position)
            owner = cm.get_component(ship_entity, ShipOwner)
            if from_pos is None or to_pos is None or owner is None:
                continue
            total = max(1, transit.total_turns)
            progress = max(0.0, min(1.0, 1.0 - transit.turns_remaining / total))
            px = int(from_pos.x + (to_pos.x - from_pos.x) * progress)
            py = int(from_pos.y + (to_pos.y - from_pos.y) * progress)
            rgb = empire_color(empire_colors_by_id.get(owner.empire_id, "blue"))
            pygame.draw.circle(screen, rgb, (px, py), 4)
            pygame.draw.circle(screen, (255, 255, 255), (px, py), 4, 1)

    def _draw_fleet_badges(self, screen):
        """Render per-empire ship counts under each star.

        For every star with parked ships, draw a compact strip of
        [color bar][count] tokens, one per owning empire.
        """
        cm = self.game.component_mgr
        # star_entity -> {empire_id: count}
        per_star: dict[int, dict[int, int]] = {}
        for entity_id, at in cm.get_all(ShipAt):
            owner = cm.get_component(entity_id, ShipOwner)
            if owner is None:
                continue
            per_star.setdefault(at.star_entity, {})
            per_star[at.star_entity][owner.empire_id] = per_star[at.star_entity].get(owner.empire_id, 0) + 1

        if not per_star:
            return

        empire_colors_by_id = {emp.id: emp.color for _eid, emp in cm.get_all(Empire)}
        font = self._label_font or self.game.font
        for star_entity, by_empire in per_star.items():
            pos = cm.get_component(star_entity, Position)
            visual = cm.get_component(star_entity, StarVisual)
            if pos is None or visual is None:
                continue
            x = pos.x - 30
            y = pos.y + 42  # below the (now larger) name label
            for empire_id, count in sorted(by_empire.items()):
                color_name = empire_colors_by_id.get(empire_id, "blue")
                rgb = empire_color(color_name)
                pygame.draw.rect(screen, rgb, pygame.Rect(x, y, 6, 16))
                text = self._render_outlined(font, str(count), (240, 240, 240))
                screen.blit(text, (x + 9, y - 2))
                x += 9 + text.get_width() + 4

    # (HUD moved into the right panel — see _draw_empire_summary.)

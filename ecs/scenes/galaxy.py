import pygame

from ecs.scene import Scene
from ecs.components import (
    Position, Name, StarVisual, Ship, ShipOwner, ShipAt, ShipInTransit,
    Empire, Owner, Orbiting,
)
from ecs.palette import empire_color
from ecs.economy import empire_per_turn
from ecs.fleet import start_fleet_movement
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
        self._draw_fleet_badges(screen)
        self._draw_fleet_picker(screen)
        self.game.ui_bar.draw(screen)
        self._draw_hud(screen)

    def _draw_fleet_picker(self, screen):
        """Top-right panel: per-class +/- count picker for the selected fleet."""
        self._fleet_picker_hits = []
        if self.selected_fleet_star is None:
            return
        cm = self.game.component_mgr
        max_counts = self._max_counts_for(self.selected_fleet_star)
        if not max_counts:
            return

        star_name = cm.get_component(self.selected_fleet_star, Name)
        title = f"Fleet at {star_name.value}" if star_name else "Fleet"

        # Layout: panel at top-right.
        row_h = 24
        rows = len(max_counts)
        panel_w = 260
        panel_h = 36 + rows * row_h + 24  # title + rows + hint
        panel_x = self.game.screen_width - panel_w - 8
        panel_y = 56  # below the HUD line
        panel = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        overlay = pygame.Surface(panel.size, pygame.SRCALPHA)
        overlay.fill((10, 12, 24, 220))
        screen.blit(overlay, panel.topleft)
        pygame.draw.rect(screen, (180, 180, 220), panel, 1)

        font = self.game.font
        bold = self._picker_font_bold or font
        screen.blit(bold.render(title, True, (255, 230, 120)), (panel.x + 12, panel.y + 8))

        # Each row: name | [-] count [+] | / max
        y = panel.y + 32
        btn_w = 22
        for class_id, max_n in sorted(max_counts.items()):
            count = self.selected_counts.get(class_id, max_n)
            name = class_id.replace("ship_", "").capitalize()
            screen.blit(font.render(name, True, (240, 240, 240)), (panel.x + 12, y + 4))

            minus_rect = pygame.Rect(panel.x + 110, y, btn_w, row_h - 4)
            plus_rect = pygame.Rect(panel.x + 110 + btn_w + 36, y, btn_w, row_h - 4)
            pygame.draw.rect(screen, (60, 60, 90), minus_rect)
            pygame.draw.rect(screen, (60, 60, 90), plus_rect)
            pygame.draw.rect(screen, (180, 180, 220), minus_rect, 1)
            pygame.draw.rect(screen, (180, 180, 220), plus_rect, 1)
            screen.blit(bold.render("−", True, (240, 240, 240)),
                        bold.render("−", True, (240, 240, 240)).get_rect(center=minus_rect.center))
            screen.blit(bold.render("+", True, (240, 240, 240)),
                        bold.render("+", True, (240, 240, 240)).get_rect(center=plus_rect.center))

            count_text = font.render(f"{count}/{max_n}", True, (240, 240, 240))
            screen.blit(count_text, count_text.get_rect(center=(minus_rect.right + 18, y + (row_h - 4) // 2)))

            self._fleet_picker_hits.append(("minus", class_id, minus_rect))
            self._fleet_picker_hits.append(("plus", class_id, plus_rect))
            y += row_h

        hint = font.render("Right-click target star to send", True, (180, 180, 180))
        screen.blit(hint, (panel.x + 12, panel.bottom - hint.get_height() - 6))

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

    def _draw_hud(self, screen):
        if self.game.galaxy is None:
            return
        font = self._label_font or self.game.font
        player = self.game.player_empire()
        x, y = 8, 8

        if player is not None:
            per_turn = empire_per_turn(self.game.component_mgr, player.id)
            food = per_turn["food_balance"]
            food_label = f"Food {food:+d}"

            # Empire color bar.
            pygame.draw.rect(screen, empire_color(player.color), pygame.Rect(x, y + 2, 6, 16))
            x += 12

            items = [
                player.name,
                f"BC {player.bc} (+{per_turn['bc']})",
                f"Res {player.research_points} (+{per_turn['research']})",
                food_label,
                f"Turn {self.game.galaxy.turn}",
            ]
            for i, text in enumerate(items):
                if i > 0:
                    sep = self._render_outlined(font, "  ·  ", (140, 140, 160))
                    screen.blit(sep, (x, y))
                    x += sep.get_width()
                surf = self._render_outlined(font, text, (255, 255, 255))
                screen.blit(surf, (x, y))
                x += surf.get_width()
        else:
            screen.blit(
                self._render_outlined(font, f"Turn {self.game.galaxy.turn}", (255, 255, 255)),
                (x, y),
            )

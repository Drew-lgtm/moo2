import pygame

from ecs.scene import Scene
from ecs.components import (
    Position, Name, StarVisual, StarRef, Ship, ShipOwner, ShipAt, ShipInTransit,
    Empire, Owner, Orbiting,
)
from ecs.palette import empire_color
from ecs.economy import empire_per_turn
from ecs.fleet import start_fleet_movement, turns_for, empire_speed_bonus
from ecs.fuel import in_fuel_range, supply_stars
from ecs.sensors import sensor_points, empire_sensor_range_px, is_detected
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
        # action is "minus", "plus", or "scrap".
        self._fleet_picker_hits: list[tuple[str, str, pygame.Rect]] = []
        # Scrap needs a confirm (it destroys ships); armed by first click.
        self._scrap_armed: bool = False
        self._picker_font_bold: pygame.font.Font | None = None
        # Larger fonts used for galaxy-view labels (star names, fleet
        # badges, HUD). Bumped a couple sizes above the 14pt game font
        # so they read better against the busy background.
        self._label_font: pygame.font.Font | None = None
        self._label_font_bold: pygame.font.Font | None = None
        # Transient message when a fleet move is rejected (out of fuel range).
        self._fuel_warning: str = ""
        # Per-frame clickable fleet chips: (star_entity, rect) for the
        # player's own parked fleets. Rebuilt every draw.
        self._fleet_chip_hits: list[tuple[int, pygame.Rect]] = []

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

    def update(self, dt):
        # A decided victory/defeat trumps everything else.
        if getattr(self.game, "pending_endgame", None) is not None:
            self.game.scenes.replace("game_over")
            return
        # Start-of-turn attention flow (MOO2-style): for each engagement
        # the player is in, ask Attack / Auto / Retreat → resolve combat
        # reports → Galactic Council → idle-colony review → free play.
        if getattr(self.game, "pending_engagements", None):
            self.game.scenes.replace("combat_decision")
        elif getattr(self.game, "pending_combat_reports", None):
            self.game.scenes.replace("combat_report")
        elif getattr(self.game, "pending_council", None) is not None:
            self.game.scenes.replace("council")
        elif getattr(self.game, "pending_idle_review", False):
            self.game.scenes.replace("idle_colonies")

    def _preload_star_surfaces(self):
        self._star_surfaces.clear()
        for entity_id, visual in self.game.component_mgr.get_all(StarVisual):
            self._star_surfaces[entity_id] = load_image(
                f"stars/{visual.image_name}", size=(visual.size, visual.size)
            )

    def tooltip_at(self, pos):
        """Stars (with fog-of-war respect), player fleet chips, and the
        bottom UI bar."""
        # Bar takes priority since it overlaps the bottom strip.
        bar_tip = self.game.ui_bar.tooltip_at(pos)
        if bar_tip:
            return bar_tip
        # Fleet chip — group ships at that star into a count + loadout
        # peek so the player can see what they've parked.
        for chip_star, chip_rect in self._fleet_chip_hits:
            if chip_rect.collidepoint(pos):
                return self._fleet_chip_tooltip(chip_star)
        star_entity = self._star_at(pos)
        if star_entity is None:
            return None
        cm = self.game.component_mgr
        name_comp = cm.get_component(star_entity, Name)
        name = name_comp.value if name_comp else "Star"
        # Fog of war — has the player explored it?
        exploration = getattr(self.game, "exploration", None)
        player = self.game.player_empire()
        ref = cm.get_component(star_entity, StarRef)
        explored = True
        if exploration is not None and player is not None and ref is not None:
            explored = exploration.is_explored(player.id, ref.db_id)
        # Count planets + collect owner names at the star.
        from ecs.components import Planet, Orbiting
        planet_count = 0
        owners: set[int] = set()
        for planet_entity, orbit in cm.get_all(Orbiting):
            if orbit.star_entity != star_entity:
                continue
            p = cm.get_component(planet_entity, Planet)
            if p is None:
                continue
            planet_count += 1
            o = cm.get_component(planet_entity, Owner)
            if o is not None:
                owners.add(o.empire_id)
        owner_names: list[str] = []
        for _e, emp in cm.get_all(Empire):
            if emp.id in owners:
                owner_names.append(emp.name)
        from ecs.tooltips import star_tooltip
        return star_tooltip(name, planet_count, owner_names, explored)

    def handle_event(self, event):
        self.game.ui_bar.handle_event(event)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.selected_fleet_star is not None:
                    self.selected_fleet_star = None
                    self.selected_counts = {}
                    self._scrap_armed = False
                else:
                    self.game.scenes.replace("pause")
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            # Fleet-picker +/- buttons get first crack so they don't get
            # eclipsed by star clicks behind them.
            if event.button == 1 and self.selected_fleet_star is not None:
                for action, class_id, rect in self._fleet_picker_hits:
                    if rect.collidepoint(event.pos):
                        if action == "scrap":
                            self._handle_scrap_click()
                        else:
                            self._adjust_count(class_id, +1 if action == "plus" else -1)
                            self._scrap_armed = False
                        return

            star = self._star_at(event.pos)
            # A fleet chip resolves to its star for click purposes.
            chip_star = next(
                (se for se, rect in self._fleet_chip_hits if rect.collidepoint(event.pos)),
                None,
            )

            if event.button == 1:
                if self.selected_fleet_star is not None:
                    # A fleet is in hand — clicking a fleet chip or a star
                    # is a move order (clicking the source toggles it off).
                    target = chip_star if chip_star is not None else star
                    if target is not None:
                        self._handle_fleet_click(target)
                    return
                # Nothing selected yet: a fleet chip grabs that fleet;
                # the star body opens the System View.
                if chip_star is not None:
                    self._handle_fleet_click(chip_star)
                    return
                if star is not None:
                    self.game.selected_star = star
                    self.game.scenes.replace("system")
                return

            if event.button == 3 and star is not None:
                # Right-click still works as a select/move shortcut.
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
        self._scrap_armed = False
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

        # Fuel range: refuse moves beyond reach of a supply system.
        if not in_fuel_range(self.game, player.id, dest_star_entity):
            self._fuel_warning = "Destination is out of fuel range."
            return
        self._fuel_warning = ""

        to_send: list[int] = []
        for class_id, count in self.selected_counts.items():
            available = by_class.get(class_id, [])
            to_send.extend(available[:count])

        if to_send:
            start_fleet_movement(cm, to_send, self.selected_fleet_star, dest_star_entity)

    def _selected_ships_at_source(self) -> list[int]:
        """The concrete ship entities matching selected_counts at the
        currently-selected source star."""
        cm = self.game.component_mgr
        player = self.game.player_empire()
        if player is None or self.selected_fleet_star is None:
            return []
        by_class: dict[str, list[int]] = {}
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != self.selected_fleet_star:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            ship = cm.get_component(ship_entity, Ship)
            if owner is None or ship is None or owner.empire_id != player.id:
                continue
            by_class.setdefault(ship.ship_class, []).append(ship_entity)
        picked: list[int] = []
        for class_id, count in self.selected_counts.items():
            picked.extend(by_class.get(class_id, [])[:count])
        return picked

    def _handle_scrap_click(self):
        """Scrap the selected ships for a partial BC refund. Two-click
        confirm — the first click arms the button, the second executes."""
        ships = self._selected_ships_at_source()
        if not ships:
            return
        if not self._scrap_armed:
            self._scrap_armed = True
            return
        from ecs.scrap import scrap_ships
        result = scrap_ships(self.game, ships)
        self._scrap_armed = False
        self.selected_fleet_star = None
        self.selected_counts = {}
        if result["scrapped"]:
            from ecs.turn_log import log as turn_log, CAT_BUILDING
            turn_log(self.game, CAT_BUILDING,
                     f"Scrapped {result['scrapped']} ship(s) (+{result['refund']} BC)")

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

    def _fleet_chip_tooltip(self, star_entity: int) -> list[str]:
        """List the player's ships at this star by class + a sample
        loadout per class."""
        cm = self.game.component_mgr
        player = self.game.player_empire()
        if player is None:
            return ["(no empire)"]
        counts: dict[str, int] = {}
        sample: dict[str, Ship] = {}
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != star_entity:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            ship = cm.get_component(ship_entity, Ship)
            if (owner is None or ship is None
                    or owner.empire_id != player.id):
                continue
            counts[ship.ship_class] = counts.get(ship.ship_class, 0) + 1
            sample.setdefault(ship.ship_class, ship)
        lines = ["Your fleet"]
        from ecs.ship_design import stored_loadout_summary
        for cls, n in sorted(counts.items()):
            lines.append(f"{cls.title()} × {n}")
            lines.append(f"hint: {stored_loadout_summary(sample[cls])}")
        return lines

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
        empires that own at least one planet OR an outpost at that
        star. Outposts contribute one share so unsettled systems still
        read as the empire's once claimed.
        """
        cm = self.game.component_mgr
        from ecs.components import Outpost as _Outpost
        empire_color_by_id = {emp.id: emp.color for _e, emp in cm.get_all(Empire)}
        counts: dict[int, dict[int, int]] = {}
        for planet_entity, owner in cm.get_all(Owner):
            orbit = cm.get_component(planet_entity, Orbiting)
            if orbit is None:
                continue
            star_bucket = counts.setdefault(orbit.star_entity, {})
            star_bucket[owner.empire_id] = star_bucket.get(owner.empire_id, 0) + 1
        for star_entity, op in cm.get_all(_Outpost):
            star_bucket = counts.setdefault(star_entity, {})
            star_bucket[op.empire_id] = star_bucket.get(op.empire_id, 0) + 1

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

    def _draw_unexplored_label(self, screen, position):
        font_norm = self._label_font or self.game.font
        text = self._render_outlined(font_norm, "Unexplored", (150, 150, 165))
        rect = text.get_rect(center=(position.x, position.y + 24))
        rect.clamp_ip(screen.get_rect())
        screen.blit(text, rect)

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

    def _player_explored(self) -> set[int] | None:
        """Set of star DB ids the player has explored, or None when fog
        of war isn't active (no exploration object → reveal everything)."""
        expl = getattr(self.game, "exploration", None)
        player = self.game.player_empire()
        if expl is None or player is None:
            return None
        return expl.explored_stars(player.id)

    def draw(self, screen):
        cm = self.game.component_mgr
        font = self.game.font
        # Build owner ratios per star once per frame (O(planets) total).
        star_ownership = self._build_star_ownership()
        explored = self._player_explored()

        for entity_id, position in cm.get_all(Position):
            visual = cm.get_component(entity_id, StarVisual)
            surface = self._star_surfaces.get(entity_id)
            if visual and surface is not None:
                screen.blit(surface, (position.x - visual.size // 2, position.y - visual.size // 2))

            # Fog of war: only label + colour stars the player has
            # explored. Unexplored stars still show their light, with a
            # faint "Unexplored" tag so the player knows to scout them.
            ref = cm.get_component(entity_id, StarRef)
            is_explored = (explored is None or ref is None or ref.db_id in explored)
            name = cm.get_component(entity_id, Name)
            if name and visual:
                if is_explored:
                    self._draw_star_label(
                        screen, name.value, visual.star_class, position,
                        star_ownership.get(entity_id, []),
                    )
                else:
                    self._draw_unexplored_label(screen, position)

        self._draw_trade_routes(screen)
        self._draw_in_transit_ships(screen)
        self._draw_selection_ring(screen)
        self._draw_fleet_pathing(screen)
        self._draw_fleet_badges(screen)
        self._draw_top_bar(screen)
        # Floating overlays sit on top of the map but below the bottom UI bar.
        self._draw_hover_tooltip(screen)
        self._draw_fleet_picker_overlay(screen)
        self._draw_turn_log(screen)
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

        player = self.game.player_empire()
        in_range = True
        if hovered_star is None or hovered_star == self.selected_fleet_star:
            end_xy = mouse_pos
            eta = None
        else:
            dst_pos = cm.get_component(hovered_star, Position)
            if dst_pos is None:
                return
            end_xy = (dst_pos.x, dst_pos.y)
            eta = self._slowest_eta(src_pos, dst_pos)
            if player is not None:
                in_range = in_fuel_range(self.game, player.id, hovered_star)

        # Green dashed line when reachable, red when out of fuel range.
        line_color = (90, 220, 110) if in_range else (230, 90, 90)
        self._draw_dashed_line(screen, line_color, (src_pos.x, src_pos.y), end_xy)

        if hovered_star is not None and not in_range:
            label = self._render_outlined(
                self._label_font or self.game.font, "Out of fuel range", (240, 120, 120))
            mid_x = (src_pos.x + end_xy[0]) // 2
            mid_y = (src_pos.y + end_xy[1]) // 2 - 10
            screen.blit(label, label.get_rect(center=(mid_x, mid_y)))
        elif eta is not None:
            label = self._render_outlined(
                self._label_font or self.game.font,
                f"{eta} turn{'s' if eta != 1 else ''}",
                (90, 220, 110),
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

    def _draw_top_bar(self, screen):
        """Slim status strip across the very top of the galaxy view.

        Shows: empire color bar, empire name, race, BC, Industry,
        Research, Food balance, Turn. Layout is horizontal cells laid
        out left-to-right. Hover details and the fleet picker float
        below as overlays rather than living in this bar.
        """
        font = self._label_font or self.game.font
        font_bold = self._label_font_bold or self.game.font
        sw = self.game.screen_width
        bar_h = self.game.GALAXY_TOP_BAR_HEIGHT
        bar = pygame.Rect(0, 0, sw, bar_h)
        pygame.draw.rect(screen, (18, 20, 32), bar)
        pygame.draw.line(screen, (90, 100, 140), (0, bar_h), (sw, bar_h), 2)

        galaxy = self.game.galaxy
        player = self.game.player_empire()
        if player is None:
            label = font_bold.render(
                f"Turn {galaxy.turn}" if galaxy else "—",
                True, (240, 240, 240),
            )
            screen.blit(label, label.get_rect(midleft=(12, bar_h // 2)))
            return

        per_turn = empire_per_turn(self.game.component_mgr, player.id,
                                   getattr(self.game, "leaders", None))
        food = per_turn["food_balance"]

        # Build a list of (label, value) cells. Empire identity sits on
        # the left; per-turn metrics + turn on the right.
        race_label = (
            f"Custom ({len([t for t in player.custom_traits.split(',') if t])} traits)"
            if player.race_type == "Custom"
            else player.race_type
        )
        cells = [
            ("BC",   f"{player.bc} (+{per_turn['bc']})"),
            ("IND",  f"+{per_turn['industry']}"),
            ("RES",  f"{player.research_points} (+{per_turn['research']})"),
            ("FOOD", f"{food:+d}"),
            ("TURN", str(galaxy.turn) if galaxy else "—"),
        ]

        # Left side: empire color bar + name + race.
        cy = bar_h // 2
        x = 12
        pygame.draw.rect(screen, empire_color(player.color), pygame.Rect(x, 6, 6, bar_h - 12))
        x += 14
        name_surf = font_bold.render(player.name, True, (255, 230, 120))
        screen.blit(name_surf, name_surf.get_rect(midleft=(x, cy)))
        x += name_surf.get_width() + 10
        race_surf = font.render(race_label, True, (200, 210, 230))
        screen.blit(race_surf, race_surf.get_rect(midleft=(x, cy)))

        # Right side: per-turn metrics. Pack cells right-aligned so
        # they stay visible if the empire name gets long.
        cell_pad = 18
        # Measure first, then position.
        rendered = [
            (font.render(lbl, True, (180, 200, 220)),
             font_bold.render(val, True, (240, 240, 240)))
            for lbl, val in cells
        ]
        total_w = sum(l.get_width() + 6 + v.get_width() for l, v in rendered) + cell_pad * (len(rendered) - 1)
        rx = sw - 12 - total_w
        for label_surf, value_surf in rendered:
            screen.blit(label_surf, label_surf.get_rect(midleft=(rx, cy)))
            rx += label_surf.get_width() + 6
            screen.blit(value_surf, value_surf.get_rect(midleft=(rx, cy)))
            rx += value_surf.get_width() + cell_pad

    def _draw_turn_log(self, screen):
        """Compact 'Last Turn' panel anchored bottom-left of the play
        area. Shows the most recent turn's player-visible events from
        ``game.turn_log`` (buildings, tech, events, combat, colonies,
        diplomacy). Stays out of the way: collapses entirely when there
        are no entries to show."""
        tl = getattr(self.game, "turn_log", None)
        if tl is None or not tl.entries:
            return
        last_turn = tl.last_turn()
        if last_turn is None:
            return
        # Newest entries last in storage; show the most recent few first.
        entries = tl.for_turn(last_turn)[-6:][::-1]
        if not entries:
            return

        font = self._label_font or self.game.font
        title_font = self._label_font_bold or self.game.font
        # Geometry — column anchored to the left edge, just above the bar.
        line_h = font.get_height() + 2
        title_h = title_font.get_height() + 4
        pad_x, pad_y = 10, 8
        max_w = 0
        rendered = []
        for cat, text in entries:
            line = f"[{cat}] {text}"
            surf = font.render(line, True, (220, 220, 220))
            rendered.append(surf)
            max_w = max(max_w, surf.get_width())
        title_surf = title_font.render(
            f"Last Turn (T{last_turn})", True, (255, 230, 120))
        max_w = max(max_w, title_surf.get_width())

        box_w = max_w + pad_x * 2
        box_h = title_h + line_h * len(rendered) + pad_y * 2
        bar_top = self.game.screen_height - self.game.ui_bar.BAR_HEIGHT
        box_x = 10
        box_y = bar_top - box_h - 6

        bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        bg.fill((10, 12, 24, 200))
        screen.blit(bg, (box_x, box_y))
        pygame.draw.rect(screen, (90, 100, 140),
                         (box_x, box_y, box_w, box_h), 1)

        cy = box_y + pad_y
        screen.blit(title_surf, (box_x + pad_x, cy))
        cy += title_h
        for surf in rendered:
            screen.blit(surf, (box_x + pad_x, cy))
            cy += line_h

    def _draw_hover_tooltip(self, screen):
        """Floating box near the cursor showing the hovered star.

        Suppressed when a fleet picker overlay is open (would overlap)
        and when the cursor is over the top status bar."""
        if self.selected_fleet_star is not None:
            return
        mouse_pos = pygame.mouse.get_pos()
        if mouse_pos[1] < self.game.GALAXY_TOP_BAR_HEIGHT:
            return
        star = self._star_at(mouse_pos)
        if star is None:
            return

        font = self._label_font or self.game.font
        font_bold = self._label_font_bold or self.game.font
        cm = self.game.component_mgr
        name = cm.get_component(star, Name)
        visual = cm.get_component(star, StarVisual)

        # Fog of war: an unexplored star shows only a "scout it" prompt.
        explored = self._player_explored()
        ref = cm.get_component(star, StarRef)
        if explored is not None and ref is not None and ref.db_id not in explored:
            self._draw_tooltip_box(screen, mouse_pos, [
                (font_bold.render("Unexplored system", True, (200, 200, 215)), (200, 200, 215)),
                (font.render("Send a ship to scout it.", True, (150, 150, 165)), (150, 150, 165)),
            ])
            return

        lines: list[tuple[pygame.Surface, tuple[int, int, int]]] = []
        title = (name.value if name else "?") + (f" ({visual.star_class})" if visual else "")
        lines.append((font_bold.render(title, True, (255, 230, 120)), (255, 230, 120)))

        # Planets + ownership.
        planet_count = 0
        owned_per_empire: dict[int, int] = {}
        for planet_entity, orbit in cm.get_all(Orbiting):
            if orbit.star_entity != star:
                continue
            planet_count += 1
            owner = cm.get_component(planet_entity, Owner)
            if owner is not None:
                owned_per_empire[owner.empire_id] = owned_per_empire.get(owner.empire_id, 0) + 1
        lines.append((font.render(f"Planets: {planet_count}", True, (240, 240, 240)), (240, 240, 240)))

        empire_info = {emp.id: (emp.name, emp.color) for _e, emp in cm.get_all(Empire)}
        for eid, count in sorted(owned_per_empire.items()):
            ename, ecolor = empire_info.get(eid, (f"Empire {eid}", "blue"))
            lines.append((font.render(f"  {ename}: {count}", True, empire_color(ecolor)), empire_color(ecolor)))

        # Ships at this star.
        ships_per_empire: dict[int, int] = {}
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != star:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            if owner is not None:
                ships_per_empire[owner.empire_id] = ships_per_empire.get(owner.empire_id, 0) + 1
        for eid, count in sorted(ships_per_empire.items()):
            ename, ecolor = empire_info.get(eid, (f"Empire {eid}", "blue"))
            lines.append((font.render(f"Fleet — {ename}: {count}", True, empire_color(ecolor)), empire_color(ecolor)))

        self._draw_tooltip_box(screen, mouse_pos, lines)

    def _draw_tooltip_box(self, screen, mouse_pos, lines):
        """Render a content-sized tooltip box near the cursor, flipping
        to the other side if it would clip off the screen."""
        if not lines:
            return
        pad = 8
        w = max(s.get_width() for s, _ in lines) + pad * 2
        h = sum(s.get_height() for s, _ in lines) + pad * 2 + 4 * (len(lines) - 1)
        bx = mouse_pos[0] + 16
        by = mouse_pos[1] + 16
        if bx + w > self.game.screen_width - 8:
            bx = mouse_pos[0] - 16 - w
        if by + h > self.game.play_area_height + self.game.GALAXY_TOP_BAR_HEIGHT:
            by = mouse_pos[1] - 16 - h
        box = pygame.Rect(bx, by, w, h)
        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill((16, 18, 30, 230))
        screen.blit(bg, box.topleft)
        pygame.draw.rect(screen, (90, 100, 140), box, 1)

        y = box.y + pad
        for surf, _color in lines:
            screen.blit(surf, (box.x + pad, y))
            y += surf.get_height() + 4

    def _draw_fleet_picker_overlay(self, screen):
        """Per-class +/- picker shown when a fleet is selected.

        Anchored to the lower-left corner so it doesn't cover the
        selected star. Populates self._fleet_picker_hits for click
        handling."""
        self._fleet_picker_hits = []
        if self.selected_fleet_star is None:
            return
        cm = self.game.component_mgr
        max_counts = self._max_counts_for(self.selected_fleet_star)
        if not max_counts:
            return

        font = self._label_font or self.game.font
        font_bold = self._label_font_bold or self.game.font
        star_name = cm.get_component(self.selected_fleet_star, Name)
        title = f"Fleet at {star_name.value}" if star_name else "Selected fleet"

        # Lay out into a sized panel anchored bottom-left.
        row_h = 26
        btn_w = 26
        rows = sorted(max_counts.items())
        panel_w = 260
        # +row_h for the Scrap button row below the class list.
        panel_h = (font_bold.get_height() + 8 + row_h * len(rows)
                   + row_h + 6 + font.get_height() * 2 + 18)
        panel_x = 12
        panel_y = self.game.screen_height - self.game.ui_bar.BAR_HEIGHT - panel_h - 12
        panel = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((16, 18, 30, 235))
        screen.blit(bg, panel.topleft)
        pygame.draw.rect(screen, (180, 180, 220), panel, 1)

        x = panel.x + 12
        screen.blit(font_bold.render(title, True, (255, 230, 120)), (x, panel.y + 8))
        y = panel.y + 8 + font_bold.get_height() + 6

        for class_id, max_n in rows:
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

        # Scrap button — decommission the selected ships for a BC refund.
        from ecs.scrap import scrap_value
        total_sel = sum(self.selected_counts.values())
        refund = sum(scrap_value(cid) * n for cid, n in self.selected_counts.items())
        scrap_rect = pygame.Rect(x, y + 2, panel_w - 24, row_h - 4)
        if total_sel <= 0:
            s_bg, s_border, s_fg = (40, 40, 52), (90, 90, 110), (140, 140, 155)
            s_text = "Scrap (select ships)"
        elif self._scrap_armed:
            s_bg, s_border, s_fg = (150, 40, 40), (240, 180, 180), (255, 240, 240)
            s_text = f"Confirm scrap {total_sel}?"
        else:
            s_bg, s_border, s_fg = (110, 70, 30), (230, 180, 120), (245, 235, 220)
            s_text = f"Scrap {total_sel}  (+{refund} BC)"
        pygame.draw.rect(screen, s_bg, scrap_rect)
        pygame.draw.rect(screen, s_border, scrap_rect, 1)
        st = font.render(s_text, True, s_fg)
        screen.blit(st, st.get_rect(center=scrap_rect.center))
        if total_sel > 0:
            self._fleet_picker_hits.append(("scrap", "", scrap_rect))
        y += row_h + 6

        screen.blit(font.render("Right-click target to send.", True, (180, 180, 180)), (x, y))
        y += font.get_height() + 2
        screen.blit(font.render("Esc to cancel.", True, (160, 160, 180)), (x, y))

    def _draw_selection_ring(self, screen):
        if self.selected_fleet_star is None:
            return
        cm = self.game.component_mgr
        pos = cm.get_component(self.selected_fleet_star, Position)
        visual = cm.get_component(self.selected_fleet_star, StarVisual)
        if pos is None or visual is None:
            return
        pygame.draw.circle(screen, (255, 230, 120), (pos.x, pos.y), visual.size // 2 + 6, 2)

    # Relation path colours.
    PATH_OWN = (90, 220, 110)       # green — your fleets
    PATH_FRIENDLY = (235, 205, 90)  # yellow — empires you have a treaty with
    PATH_HOSTILE = (235, 95, 95)    # red — foreign empire, no friendly treaty

    def _relation_path_color(self, owner_empire_id, player):
        if player is not None and owner_empire_id == player.id:
            return self.PATH_OWN
        diplo = getattr(self.game, "diplomacy", None)
        # Yellow only when there's an active treaty and we're not at war;
        # everything else (neutral with no treaty, or at war) is red.
        if (player is not None and diplo is not None
                and not diplo.at_war(player.id, owner_empire_id)
                and diplo.treaties(player.id, owner_empire_id)):
            return self.PATH_FRIENDLY
        return self.PATH_HOSTILE

    def _draw_trade_routes(self, screen):
        """Faint dashed lines from food-surplus colonies to food-deficit
        ones, showing where the player's freighters are running this
        turn. Routes are recomputed every frame from the same logic the
        Trade panel would use — display only, no economy mutation.
        Player perspective: AI freighter movement isn't surfaced."""
        player = self.game.player_empire()
        if player is None:
            return
        cm = self.game.component_mgr
        from ecs.trade import trade_routes
        from ecs.components import Orbiting, Position
        routes = trade_routes(self.game, player.id)
        if not routes:
            return
        for src_planet, dst_planet, _amount in routes:
            src_orbit = cm.get_component(src_planet, Orbiting)
            dst_orbit = cm.get_component(dst_planet, Orbiting)
            if src_orbit is None or dst_orbit is None:
                continue
            sp = cm.get_component(src_orbit.star_entity, Position)
            dp = cm.get_component(dst_orbit.star_entity, Position)
            if sp is None or dp is None:
                continue
            # Faint teal dashes — distinct from the green fleet-pathing
            # preview and the red/yellow detection lines.
            self._draw_dashed_line(
                screen, (90, 180, 200),
                (sp.x, sp.y), (dp.x, dp.y),
                dash_len=6, gap_len=8, width=1,
            )

    def _draw_in_transit_ships(self, screen):
        """Draw every in-transit fleet's remaining path + position dot.

        - Your own fleets are always shown (green path).
        - Other empires' fleets show only when *detected* by your
          sensors — yellow if you hold a treaty with them, red for any
          foreign empire you have no friendly treaty with — invisible
          until a colony or ship picks them up on radar.
        """
        cm = self.game.component_mgr
        player = self.game.player_empire()

        # Player's sensor coverage (skip the work if there's no player).
        if player is not None:
            points = sensor_points(self.game, player.id)
            sensor_r = empire_sensor_range_px(cm, player.id)
        else:
            points, sensor_r = [], 0.0

        for ship_entity, transit in cm.get_all(ShipInTransit):
            from_pos = cm.get_component(transit.from_star_entity, Position)
            to_pos = cm.get_component(transit.to_star_entity, Position)
            owner = cm.get_component(ship_entity, ShipOwner)
            if from_pos is None or to_pos is None or owner is None:
                continue
            total = max(1, transit.total_turns)
            progress = max(0.0, min(1.0, 1.0 - transit.turns_remaining / total))
            px = from_pos.x + (to_pos.x - from_pos.x) * progress
            py = from_pos.y + (to_pos.y - from_pos.y) * progress

            is_own = player is not None and owner.empire_id == player.id
            if not is_own:
                # Fog of war for fleets: only render detected ones.
                if not is_detected(px, py, points, sensor_r):
                    continue

            color = self._relation_path_color(owner.empire_id, player)
            # Remaining path: current position → destination.
            self._draw_dashed_line(screen, color, (int(px), int(py)), (to_pos.x, to_pos.y),
                                   dash_len=8, gap_len=6, width=2)
            pygame.draw.circle(screen, color, (int(px), int(py)), 5)
            pygame.draw.circle(screen, (255, 255, 255), (int(px), int(py)), 5, 1)

    def _draw_fleet_badges(self, screen):
        """Render per-empire ship counts under each star.

        For every star with parked ships, draw a compact strip of
        [color bar][count] tokens, one per owning empire.
        """
        cm = self.game.component_mgr
        self._fleet_chip_hits = []
        player = self.game.player_empire()
        player_id = player.id if player is not None else None

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
        explored = self._player_explored()
        font = self._picker_font_bold or self.game.font
        for star_entity, by_empire in per_star.items():
            pos = cm.get_component(star_entity, Position)
            visual = cm.get_component(star_entity, StarVisual)
            if pos is None or visual is None:
                continue
            # Fog of war: don't reveal fleets parked at stars the player
            # hasn't explored.
            if explored is not None:
                ref = cm.get_component(star_entity, StarRef)
                if ref is not None and ref.db_id not in explored:
                    continue

            # Fleet chips stack down from the star's top-right corner.
            chip_x = pos.x + visual.size // 2 + 2
            chip_y = pos.y - visual.size // 2 - 2
            # Player's own fleet first (the clickable one), then others.
            order = sorted(by_empire, key=lambda e: (e != player_id, e))
            for empire_id in order:
                count = by_empire[empire_id]
                is_own = empire_id == player_id
                rgb = empire_color(empire_colors_by_id.get(empire_id, "blue"))
                count_surf = self._render_outlined(font, str(count), (240, 240, 240))
                chip_w = 22 + count_surf.get_width()
                chip_h = 20
                rect = pygame.Rect(chip_x, chip_y, chip_w, chip_h)

                # Backing — brighter + ringed for the player's clickable
                # chip, especially when this fleet is selected.
                selected = is_own and star_entity == self.selected_fleet_star
                bg = (28, 32, 48) if is_own else (20, 22, 34)
                pygame.draw.rect(screen, bg, rect)
                ring = (255, 230, 120) if selected else rgb
                pygame.draw.rect(screen, ring, rect, 2 if (is_own or selected) else 1)

                # Chevron (fleet glyph) in empire colour + the count.
                cx0 = rect.x + 4
                cy0 = rect.centery
                pygame.draw.polygon(screen, rgb, [
                    (cx0, cy0 - 5), (cx0, cy0 + 5), (cx0 + 9, cy0),
                ])
                screen.blit(count_surf, (cx0 + 13, rect.y + 1))

                if is_own:
                    self._fleet_chip_hits.append((star_entity, rect))
                chip_y += chip_h + 3

    # (HUD moved into the right panel — see _draw_empire_summary.)

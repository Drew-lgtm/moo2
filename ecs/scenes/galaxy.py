import pygame

from ecs.scene import Scene
from ecs.components import Position, Name, StarVisual, Ship, ShipOwner, ShipAt, ShipInTransit, Empire
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

    def on_enter(self):
        self._preload_star_surfaces()

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
                else:
                    self.game.scenes.replace("pause")
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            star = self._star_at(event.pos)
            if event.button == 1 and star is not None:
                # Left-click: open System View as before.
                self.game.selected_star = star
                self.game.scenes.replace("system")
            elif event.button == 3 and star is not None:
                # Right-click: select/move fleet.
                self._handle_fleet_click(star)

    def _handle_fleet_click(self, star_entity: int):
        """Right-click flow:

        - If we're not selecting a fleet yet and this star has player ships:
          select it.
        - If we're already selecting from this star: deselect (toggle).
        - If we're selecting from another star: move those ships here.
        """
        player = self.game.player_empire()
        if player is None:
            return
        ships_here = self._player_ships_at(star_entity, player.id)
        if self.selected_fleet_star is None:
            if ships_here:
                self.selected_fleet_star = star_entity
        elif self.selected_fleet_star == star_entity:
            self.selected_fleet_star = None
        else:
            source_ships = self._player_ships_at(self.selected_fleet_star, player.id)
            if source_ships:
                start_fleet_movement(
                    self.game.component_mgr,
                    source_ships,
                    self.selected_fleet_star,
                    star_entity,
                )
            self.selected_fleet_star = None

    def _player_ships_at(self, star_entity: int, player_empire_id: int) -> list[int]:
        out: list[int] = []
        cm = self.game.component_mgr
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != star_entity:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            if owner is not None and owner.empire_id == player_empire_id:
                out.append(ship_entity)
        return out

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

    def draw(self, screen):
        cm = self.game.component_mgr
        font = self.game.font
        for entity_id, position in cm.get_all(Position):
            visual = cm.get_component(entity_id, StarVisual)
            surface = self._star_surfaces.get(entity_id)
            if visual and surface is not None:
                screen.blit(surface, (position.x - visual.size // 2, position.y - visual.size // 2))

            name = cm.get_component(entity_id, Name)
            if name and visual:
                label = f"{name.value} ({visual.star_class})"
                text_surface = font.render(label, True, (255, 255, 255))
                text_rect = text_surface.get_rect(center=(position.x, position.y + 24))
                text_rect.clamp_ip(screen.get_rect())
                screen.blit(text_surface, text_rect)

        self._draw_in_transit_ships(screen)
        self._draw_selection_ring(screen)
        self._draw_fleet_badges(screen)
        self.game.ui_bar.draw(screen)
        self._draw_hud(screen)

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
        """Render a small empire-colored dot at the midpoint between
        source and destination for each ship in transit. Crude — a future
        pass could animate position based on turns_remaining vs total."""
        cm = self.game.component_mgr
        empire_colors_by_id = {emp.id: emp.color for _eid, emp in cm.get_all(Empire)}
        for ship_entity, transit in cm.get_all(ShipInTransit):
            from_pos = cm.get_component(transit.from_star_entity, Position)
            to_pos = cm.get_component(transit.to_star_entity, Position)
            owner = cm.get_component(ship_entity, ShipOwner)
            if from_pos is None or to_pos is None or owner is None:
                continue
            mid_x = (from_pos.x + to_pos.x) // 2
            mid_y = (from_pos.y + to_pos.y) // 2
            rgb = empire_color(empire_colors_by_id.get(owner.empire_id, "blue"))
            pygame.draw.circle(screen, rgb, (mid_x, mid_y), 4)
            pygame.draw.circle(screen, (255, 255, 255), (mid_x, mid_y), 4, 1)

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
        font = self.game.font
        for star_entity, by_empire in per_star.items():
            pos = cm.get_component(star_entity, Position)
            visual = cm.get_component(star_entity, StarVisual)
            if pos is None or visual is None:
                continue
            x = pos.x - 30
            y = pos.y + 38  # below the name label
            for empire_id, count in sorted(by_empire.items()):
                color_name = empire_colors_by_id.get(empire_id, "blue")
                rgb = empire_color(color_name)
                pygame.draw.rect(screen, rgb, pygame.Rect(x, y, 6, 12))
                text = font.render(str(count), True, (240, 240, 240))
                screen.blit(text, (x + 9, y - 2))
                x += 9 + text.get_width() + 6

    def _draw_hud(self, screen):
        if self.game.galaxy is None:
            return
        font = self.game.font
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
                    sep = font.render("   ·   ", True, (140, 140, 160))
                    screen.blit(sep, (x, y))
                    x += sep.get_width()
                surf = font.render(text, True, (255, 255, 255))
                screen.blit(surf, (x, y))
                x += surf.get_width()
        else:
            screen.blit(
                font.render(f"Turn {self.game.galaxy.turn}", True, (255, 255, 255)),
                (x, y),
            )

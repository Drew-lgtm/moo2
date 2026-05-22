import pygame

from ecs.scene import Scene
from ecs.components import Position, Name, StarVisual
from assets.loader import load_image


class GalaxyScene(Scene):
    """Main galaxy view: stars on the background, bottom UI bar."""

    def __init__(self, game):
        super().__init__(game)
        # entity_id -> scaled pygame.Surface, rebuilt on_enter from current StarVisuals.
        self._star_surfaces: dict[int, pygame.Surface] = {}

    def on_enter(self):
        self._preload_star_surfaces()
        self.game.ui_bar.set_callback("turn", self.game.advance_turn)

    def on_exit(self):
        self.game.ui_bar.set_callback("turn", None)

    def _preload_star_surfaces(self):
        self._star_surfaces.clear()
        for entity_id, visual in self.game.component_mgr.get_all(StarVisual):
            self._star_surfaces[entity_id] = load_image(
                f"stars/{visual.image_name}", size=(visual.size, visual.size)
            )

    def handle_event(self, event):
        self.game.ui_bar.handle_event(event)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.scenes.replace("pause")
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            star = self._star_at(event.pos)
            if star is not None:
                self.game.selected_star = star
                self.game.scenes.replace("system")

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

        self.game.ui_bar.draw(screen)
        self._draw_turn_hud(screen)

    def _draw_turn_hud(self, screen):
        if self.game.galaxy is None:
            return
        text = self.game.font.render(
            f"Turn {self.game.galaxy.turn}", True, (255, 255, 255)
        )
        # 8px padding from top-left.
        screen.blit(text, (8, 8))

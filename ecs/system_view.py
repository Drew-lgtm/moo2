import pygame
from ecs.components import Planet, Orbiting, Position

class SystemView:
    def __init__(self, screen, component_mgr, star_id):
        self.screen = screen
        self.component_mgr = component_mgr
        self.star_id = star_id
        self.is_open = True
        self.close_button_rect = pygame.Rect(700, 20, 80, 30)

        # Preload data
        self.star_pos = component_mgr.get_component(star_id, Position)
        self.planets = []
        for entity_id, orbit in component_mgr.get_all(Orbiting):
            if orbit.star_entity == star_id:
                planet = component_mgr.get_component(entity_id, Planet)
                if planet:
                    self.planets.append(planet)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_button_rect.collidepoint(event.pos):
                self.is_open = False

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.is_open = False

    def draw(self, font):
        # Semi-transparent overlay
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))  # RGBA with alpha

        size_radius = {
            "Tiny": 4,
            "Small": 6,
            "Medium": 9,
            "Large": 12,
            "Huge": 15
        }

        # Draw star and orbits
        center = (self.screen.get_width() // 2, self.screen.get_height() // 2)
        for i, planet in enumerate(self.planets):
            orbit_radius = 60 + i * 40
            pygame.draw.circle(overlay, (100, 100, 100), center, orbit_radius, 1)
            planet_x = center[0] + orbit_radius
            planet_y = center[1]
            planet_colors = {
                "Terran": (100, 200, 255),
                "Ocean": (80, 160, 255),
                "Jungle": (50, 180, 50),
                "Arid": (210, 180, 100),
                "Desert": (230, 200, 120),
                "Tundra": (180, 180, 220),
                "Steppe": (160, 200, 140),
                "Barren": (150, 150, 150),
                "Gaia": (0, 255, 0),
                "Radiated": (255, 100, 255),
                "Toxic": (255, 80, 80),
                "Inferno": (255, 50, 0),
                "Volcanic": (255, 100, 0),
                "Asteroids": (100, 100, 100),
                "Gas Giant": (120, 120, 255),
            }
            color = planet_colors.get(planet.planet_type, (200, 200, 200))
            radius = size_radius.get(planet.size, 8)  # Fallback to 8
            pygame.draw.circle(overlay, color, (planet_x, planet_y), radius)


            label = f"{planet.planet_type[:3]} {planet.size[:1]}"
            text_surface = font.render(label, True, (255, 255, 255))
            overlay.blit(text_surface, (planet_x - 15, planet_y + 14))

        # Draw close button
        pygame.draw.rect(overlay, (150, 0, 0), self.close_button_rect)
        close_text = font.render("Close", True, (255, 255, 255))
        overlay.blit(close_text, (self.close_button_rect.x + 10, self.close_button_rect.y + 5))

        # Blit to screen
        self.screen.blit(overlay, (0, 0))

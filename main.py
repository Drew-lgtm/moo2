import pygame
from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import Position, Name, StarVisual
from assets.loader import load_image, load_random_background
from ecs.galaxy_generator import GalaxyGenerator

# --- Init Pygame ---
pygame.init()
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Master Of Galaxy")
clock = pygame.time.Clock()

# --- ECS Setup ---
entity_mgr = EntityManager()
component_mgr = ComponentManager()

# Generate galaxy once
galaxy = GalaxyGenerator(entity_mgr, component_mgr, SCREEN_WIDTH, SCREEN_HEIGHT, num_stars=40)
galaxy.generate()

# --- Load star image ---
font = pygame.font.SysFont("Arial", 14)


# --- Game loop ---
running = True
while running:
    background = load_random_background()
    background = pygame.transform.scale(background, (SCREEN_WIDTH, SCREEN_HEIGHT))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Draw background first
    screen.blit(background, (0, 0))

    # Draw stars from ECS
    for entity_id, pos in component_mgr.get_all(Position):
        visual = component_mgr.get_component(entity_id, StarVisual)
        if visual:
            star_image = load_image(f"stars/{visual.image_name}", size=(visual.size, visual.size))
            screen.blit(
                star_image,
                (pos.x - visual.size // 2, pos.y - visual.size // 2)
            )

        name = component_mgr.get_component(entity_id, Name)
        visual = component_mgr.get_component(entity_id, StarVisual)

        if name and visual:
            label = f"{name.value} ({visual.star_class})"
            text_surface = font.render(label, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=(pos.x, pos.y + 24))
            screen.blit(text_surface, text_rect)


    pygame.display.flip()
    clock.tick(60)

pygame.quit()

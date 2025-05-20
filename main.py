import pygame
from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import Position, Name, StarVisual, Orbiting, Planet
from assets.loader import load_image, load_random_background
from ecs.galaxy_generator import GalaxyGenerator
from ecs.utils import distance_parsecs
from ecs.system_view import SystemView


selected_star = None
active_system_view = None


# --- Init Pygame ---
pygame.init()
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Master Of Galaxy")
clock = pygame.time.Clock()

# --- Load background once ---
background = load_random_background()
background = pygame.transform.scale(background, (SCREEN_WIDTH, SCREEN_HEIGHT))

# --- ECS Setup ---
entity_mgr = EntityManager()
component_mgr = ComponentManager()

# Generate galaxy once
galaxy = GalaxyGenerator(entity_mgr, component_mgr, SCREEN_WIDTH, SCREEN_HEIGHT, num_stars=40)
galaxy.generate()
positions = list(component_mgr.get_all(Position))
for i, (id1, pos1) in enumerate(positions):
    for id2, pos2 in positions[i+1:]:
        dist = distance_parsecs(pos1, pos2)
        print(f"Distance between Star {id1} and {id2}: {dist} parsecs")

# --- Load star image ---
font = pygame.font.SysFont("Arial", 14)


# --- Game loop ---
running = True
while running:
    events = pygame.event.get()

    # Handle global quit
    for event in events:
        if event.type == pygame.QUIT:
            running = False

    # If system view is open, handle its events first
    if active_system_view:
        for event in events:
            active_system_view.handle_event(event)
        screen.blit(background, (0, 0))
        active_system_view.draw(font)
        if not active_system_view.is_open:
            active_system_view = None
        pygame.display.flip()
        clock.tick(60)
        continue  # Skip galaxy view

    # Handle star selection (left click)
    for event in events:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_x, mouse_y = event.pos
            selected_star = None  # reset

            for entity_id, pos in component_mgr.get_all(Position):
                visual = component_mgr.get_component(entity_id, StarVisual)
                if not visual:
                    continue

                dx = mouse_x - pos.x
                dy = mouse_y - pos.y
                distance = (dx**2 + dy**2) ** 0.5
                if distance < visual.size // 2:
                    active_system_view = SystemView(screen, component_mgr, entity_id)
                    break

    # Draw galaxy background
    screen.blit(background, (0, 0))

    # Draw stars
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
            text_rect.clamp_ip(screen.get_rect())
            screen.blit(text_surface, text_rect)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()

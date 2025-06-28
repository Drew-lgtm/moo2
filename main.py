import pygame
from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import Position, Name, StarVisual, Orbiting, Planet
from assets.loader import load_image, load_random_background
from ecs.galaxy_generator import GalaxyGenerator
from ecs.utils import distance_parsecs
from ecs.system_view import SystemView
from ecs.menu import Menu
from ecs.db import clear_galaxy
from ecs.save_manager import init_save_slots, save_to_slot, load_from_slot
from ecs.ui_bar import BottomUIBar



pygame.init()
init_save_slots()

SCREEN_WIDTH, SCREEN_HEIGHT = 1200, 800
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Master Of Galaxy")
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 14)

# --- State ---
game_state = "main_menu"
selected_star = None
active_system_view = None
galaxy = None

# --- ECS Setup ---
entity_mgr = EntityManager()
component_mgr = ComponentManager()

# --- Load background ---
background = load_random_background()
background = pygame.transform.scale(background, (SCREEN_WIDTH, SCREEN_HEIGHT))

ui_bar = BottomUIBar(SCREEN_WIDTH, SCREEN_HEIGHT)

# --- Menus ---
main_menu = Menu(screen, ["New Game", "Load Game", "Quit"], title="Main Menu")
pause_menu = Menu(screen, ["Resume", "Save Game", "Quit to Menu"], title="Paused")

def start_new_game():
    global entity_mgr, component_mgr, galaxy, background, ui_bar
    clear_galaxy()
    entity_mgr = EntityManager()
    component_mgr = ComponentManager()
    galaxy = GalaxyGenerator(entity_mgr, component_mgr, SCREEN_WIDTH, SCREEN_HEIGHT, num_stars=40)
    galaxy.generate()
    background = load_random_background()
    background = pygame.transform.scale(background, (SCREEN_WIDTH, SCREEN_HEIGHT))
    ui_bar = BottomUIBar(SCREEN_WIDTH, SCREEN_HEIGHT)

def load_game():
    global entity_mgr, component_mgr, galaxy, ui_bar
    entity_mgr = EntityManager()
    component_mgr = ComponentManager()
    galaxy = GalaxyGenerator(entity_mgr, component_mgr, SCREEN_WIDTH, SCREEN_HEIGHT)
    galaxy.load_from_db()
    ui_bar = BottomUIBar(SCREEN_WIDTH, SCREEN_HEIGHT)

def save_game():
    # Placeholder: with hybrid ECS model, DB is already up-to-date each turn/save
    print("Game saved.")

# --- Main Loop ---
running = True
while running:
    events = pygame.event.get()

    for event in events:
        if event.type == pygame.QUIT:
            running = False

    screen.blit(background, (0, 0))

    # MAIN MENU STATE
    if game_state == "main_menu":
        for event in events:
            result = main_menu.handle_event(event)
            if result == "New Game":
                start_new_game()
                game_state = "running"
            elif result == "Load Game":
                load_game()
                game_state = "running"
            elif result == "Quit":
                running = False
        main_menu.draw()
        pygame.display.flip()
        clock.tick(60)
        continue

    # PAUSED STATE
    if game_state == "paused":
        for event in events:
            result = pause_menu.handle_event(event)
            if result == "Resume":
                game_state = "running"
            elif result == "Save Game":
                save_to_slot(1)  # Default slot; replace with menu later
            elif result == "Quit to Menu":
                game_state = "main_menu"

            if event.type == pygame.KEYDOWN:
                if event.key in [pygame.K_1, pygame.K_2, pygame.K_3]:
                    slot = int(pygame.key.name(event.key))
                    save_to_slot(slot)
                elif event.key in [pygame.K_4, pygame.K_5, pygame.K_6]:
                    slot = int(pygame.key.name(event.key)) - 3
                    if load_from_slot(slot):
                        load_game()
                        game_state = "running"

        pause_menu.draw()
        pygame.display.flip()
        clock.tick(60)
        continue

    # GAMEPLAY STATE
    if game_state == "running":
        # Input: Escape → close system view, or pause menu
        for event in events:
            ui_bar.handle_event(event)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if active_system_view:
                        active_system_view.is_open = False
                    else:
                        game_state = "paused"

        # If system view open
        if active_system_view:
            for event in events:
                active_system_view.handle_event(event)
            active_system_view.draw(font)
            if not active_system_view.is_open:
                active_system_view = None
            pygame.display.flip()
            clock.tick(60)
            continue

        # Star selection
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_x, mouse_y = event.pos
                for entity_id, pos in component_mgr.get_all(Position):
                    visual = component_mgr.get_component(entity_id, StarVisual)
                    if not visual:
                        continue
                    dx = mouse_x - pos.x
                    dy = mouse_y - pos.y
                    if (dx ** 2 + dy ** 2) ** 0.5 < visual.size // 2:
                        active_system_view = SystemView(screen, component_mgr, entity_id)
                        break

        # Draw stars
        for entity_id, pos in component_mgr.get_all(Position):
            visual = component_mgr.get_component(entity_id, StarVisual)
            if visual:
                star_image = load_image(f"stars/{visual.image_name}", size=(visual.size, visual.size))
                screen.blit(star_image, (pos.x - visual.size // 2, pos.y - visual.size // 2))

            name = component_mgr.get_component(entity_id, Name)
            if name and visual:
                label = f"{name.value} ({visual.star_class})"
                text_surface = font.render(label, True, (255, 255, 255))
                text_rect = text_surface.get_rect(center=(pos.x, pos.y + 24))
                text_rect.clamp_ip(screen.get_rect())
                screen.blit(text_surface, text_rect)

        ui_bar.draw(screen)

        pygame.display.flip()
        clock.tick(60)

pygame.quit()

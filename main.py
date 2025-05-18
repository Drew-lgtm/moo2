import pygame
from core.galaxy import Galaxy
from ui.renderer import draw_galaxy
from config import SCREEN_WIDTH, SCREEN_HEIGHT

# Init
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Mini Master of Orion")
clock = pygame.time.Clock()

# Galaxy
galaxy = Galaxy(num_stars=20, width=SCREEN_WIDTH, height=SCREEN_HEIGHT)

# Main Loop
running = True
while running:
    screen.fill((0, 0, 20))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    draw_galaxy(screen, galaxy)
    pygame.display.flip()
    clock.tick(60)

pygame.quit()

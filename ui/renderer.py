import pygame
from config import STAR_COLOR

def draw_galaxy(screen, galaxy):
    for star in galaxy.stars:
        pygame.draw.circle(screen, STAR_COLOR, (star.x, star.y), 4)

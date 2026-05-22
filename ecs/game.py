"""Top-level Game container.

Owns the shared world state (ECS managers, galaxy, screen, background,
ui_bar) and the SceneManager. Replaces the module-globals pattern that
used to live in main.py.
"""
from __future__ import annotations

import pygame

from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.galaxy_generator import GalaxyGenerator
from ecs.scene import SceneManager
from ecs.ui_bar import BottomUIBar
from ecs.db import clear_galaxy
from assets.loader import load_random_background


class Game:
    def __init__(self, screen_width=1200, screen_height=800, num_stars=40):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.num_stars = num_stars

        self.screen = pygame.display.set_mode((screen_width, screen_height))
        pygame.display.set_caption("Master Of Galaxy")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 14)

        # World state — populated by start_new_game / load_game.
        self.entity_mgr = EntityManager()
        self.component_mgr = ComponentManager()
        self.galaxy: GalaxyGenerator | None = None

        self.background = self._load_background()
        self.ui_bar = BottomUIBar(screen_width, screen_height)

        self.scenes = SceneManager()
        self.running = True

        # Functions called after each advance_turn(). Receives the new turn
        # number. Future systems (production, research) register hooks here.
        self.turn_callbacks: list = []

    def _load_background(self):
        bg = load_random_background()
        return pygame.transform.scale(bg, (self.screen_width, self.screen_height))

    def _reset_world(self):
        self.entity_mgr = EntityManager()
        self.component_mgr = ComponentManager()
        self.background = self._load_background()
        self.ui_bar = BottomUIBar(self.screen_width, self.screen_height)

    def start_new_game(self):
        clear_galaxy()
        self._reset_world()
        self.galaxy = GalaxyGenerator(
            self.entity_mgr, self.component_mgr,
            self.screen_width, self.screen_height,
            num_stars=self.num_stars,
        )
        self.galaxy.generate()

    def load_game(self):
        self._reset_world()
        self.galaxy = GalaxyGenerator(
            self.entity_mgr, self.component_mgr,
            self.screen_width, self.screen_height,
        )
        self.galaxy.load_from_db()

    def advance_turn(self):
        if self.galaxy is None:
            return None
        new_turn = self.galaxy.advance_turn()
        for cb in self.turn_callbacks:
            cb(new_turn)
        return new_turn

    def quit(self):
        self.running = False

    def run(self, initial_scene):
        self.scenes.replace(initial_scene)
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False
                else:
                    self.scenes.active.handle_event(event)

            self.scenes.active.update(dt)

            self.screen.blit(self.background, (0, 0))
            self.scenes.active.draw(self.screen)
            pygame.display.flip()

        pygame.quit()

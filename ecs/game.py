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
from ecs.components import Empire
from ecs.economy import production_tick, pop_growth_tick
from ecs.ai import ai_tick
from ecs.fleet import fleet_tick
from ecs.combat import combat_tick
from assets.loader import load_random_background


class Game:
    def __init__(self, screen_width=1200, screen_height=800, num_stars=40):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.num_stars = num_stars

        # Start fullscreen at the game's logical resolution; SCALED makes
        # pygame stretch the 1200x800 content to fill whatever physical
        # display the user has. F11 toggles to windowed mode at runtime.
        self.screen = pygame.display.set_mode(
            (screen_width, screen_height),
            pygame.SCALED | pygame.FULLSCREEN,
        )
        pygame.display.set_caption("Master Of Galaxy")
        self.clock = pygame.time.Clock()
        # Bold weight everywhere so 1px strokes survive non-integer
        # display scaling under pygame.SCALED. See galaxy labels for the
        # same fix.
        self.font = pygame.font.SysFont("Arial", 14, bold=True)

        # World state — populated by start_new_game / load_game.
        self.entity_mgr = EntityManager()
        self.component_mgr = ComponentManager()
        self.galaxy: GalaxyGenerator | None = None

        self.background = self._load_background()
        self.ui_bar = BottomUIBar(screen_width, screen_height)

        self.scenes = SceneManager()
        self.running = True

        # Functions called after each advance_turn(). Each receives
        # (game, new_turn). Future systems (production, research) register here.
        self.turn_callbacks: list = []

    @property
    def play_area_height(self) -> int:
        """Vertical room above the bottom UI bar — used by star
        generation and panel scenes so nothing renders under the bar."""
        return self.screen_height - BottomUIBar.BAR_HEIGHT

    def _load_background(self):
        bg = load_random_background()
        # smoothscale gives the nebula clean edges when stretched/shrunk.
        try:
            return pygame.transform.smoothscale(bg, (self.screen_width, self.screen_height))
        except (pygame.error, ValueError):
            return pygame.transform.scale(bg, (self.screen_width, self.screen_height))

    def _reset_world(self):
        self.entity_mgr = EntityManager()
        self.component_mgr = ComponentManager()
        self.background = self._load_background()
        self.ui_bar = BottomUIBar(self.screen_width, self.screen_height)

    def start_new_game(self, player_empire=None, num_empires=2, difficulty="normal"):
        clear_galaxy()
        self._reset_world()
        self.galaxy = GalaxyGenerator(
            self.entity_mgr, self.component_mgr,
            self.screen_width, self.play_area_height,
            num_stars=self.num_stars,
        )
        self.galaxy.generate(num_empires=num_empires, player_empire=player_empire, difficulty=difficulty)
        self._bind_game_ui()

    def load_game(self):
        self._reset_world()
        self.galaxy = GalaxyGenerator(
            self.entity_mgr, self.component_mgr,
            self.screen_width, self.play_area_height,
        )
        self.galaxy.load_from_db()
        self._bind_game_ui()

    def _bind_game_ui(self):
        """Wire the bottom-bar buttons to scene transitions and turn advance.

        Done once per loaded game so panel scenes can share the bar without
        each having to re-bind on entry.
        """
        panel_targets = {
            "colonies": "colonies",
            "planets": "planets",
            "research": "research",
            "leaders": "leaders",
            "races": "races",
            "info": "info",
        }
        for button_name, scene_name in panel_targets.items():
            self.ui_bar.set_callback(
                button_name, lambda s=scene_name: self.scenes.replace(s)
            )
        self.ui_bar.set_callback("turn", self.advance_turn)

        # Register per-turn systems. Order: AI -> growth -> production ->
        # fleet movement -> combat. Combat runs last so ships that arrived
        # this turn engage at the destination star.
        for cb in (ai_tick, pop_growth_tick, production_tick, fleet_tick, combat_tick):
            if cb not in self.turn_callbacks:
                self.turn_callbacks.append(cb)

    def player_empire(self) -> Empire | None:
        for _eid, emp in self.component_mgr.get_all(Empire):
            if emp.is_player:
                return emp
        return None

    def advance_turn(self):
        if self.galaxy is None:
            return None
        new_turn = self.galaxy.advance_turn()
        for cb in self.turn_callbacks:
            cb(self, new_turn)
        return new_turn

    def quit(self):
        self.running = False

    # Global keyboard shortcuts (only fire when an in-game scene is
    # active, never on the main menu / empire setup / pause).
    _SHORTCUT_SCENES = {"galaxy", "colonies", "planets", "research", "leaders", "races", "info", "system", "colony"}
    _SHORTCUT_SCENE_KEYS = {
        pygame.K_c: "colonies",
        pygame.K_p: "planets",
        pygame.K_r: "research",
        pygame.K_l: "leaders",
        pygame.K_i: "info",
        pygame.K_g: "galaxy",
    }

    def _handle_shortcut(self, event) -> bool:
        if event.type != pygame.KEYDOWN:
            return False
        if self.scenes.active_name not in self._SHORTCUT_SCENES:
            return False
        if event.key in self._SHORTCUT_SCENE_KEYS:
            self.scenes.replace(self._SHORTCUT_SCENE_KEYS[event.key])
            return True
        if event.key == pygame.K_t:
            self.advance_turn()
            return True
        return False

    def run(self, initial_scene):
        self.scenes.replace(initial_scene)
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    # F11 toggles between the SCALED window and fullscreen at
                    # the same logical resolution.
                    pygame.display.toggle_fullscreen()
                elif self._handle_shortcut(event):
                    pass  # consumed by the global shortcut handler
                else:
                    self.scenes.active.handle_event(event)

            self.scenes.active.update(dt)

            self.screen.blit(self.background, (0, 0))
            self.scenes.active.draw(self.screen)
            pygame.display.flip()

        pygame.quit()

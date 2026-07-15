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
from ecs.db import clear_galaxy, init_db
from ecs.components import Empire, Owner, Population, BuildState
from ecs.economy import production_tick, pop_growth_tick
from ecs.autobuild import autobuild_tick as _autobuild_tick
from ecs.assimilation import assimilation_tick as _assimilation_tick
from ecs.events import events_tick as _events_tick
from ecs.ai import ai_tick
from ecs.fleet import fleet_tick
from ecs.combat import combat_tick
from ecs.diplomacy import Diplomacy, diplomacy_tick as _diplomacy_tick
from ecs.exploration import Exploration, exploration_tick as _exploration_tick
from ecs.espionage import Espionage, espionage_tick as _espionage_tick
from ecs.leaders import LeadersManager, leaders_tick as _leaders_tick
from ecs.designs import ShipDesignManager
from ecs.tooltip import Tooltip
from ecs.council import is_council_turn, tally_votes
from ecs.endgame import check_endgame
from ecs.turn_log import TurnLog
from ecs.antaran import antaran_tick as _antaran_tick
from ecs.monsters import (
    spawn_guardians as _spawn_guardians, load_guardians as _load_guardians,
    monster_tick as _monster_tick,
)
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
        # Inter-empire diplomacy. Created fresh on new game, loaded on
        # load_game. None until a game is running.
        self.diplomacy: Diplomacy | None = None
        # Per-empire star exploration (fog of war). None until a game runs.
        self.exploration: Exploration | None = None
        # Spies + counter-intelligence. None until a game is running.
        self.espionage: Espionage | None = None
        # Leaders / heroes (colony + ship officers). None until a game runs.
        self.leaders: LeadersManager | None = None
        # Manual ship designs (player + AI blueprints). None until running.
        self.ship_designs: ShipDesignManager | None = None
        # Set by advance_turn when the Galactic Council convenes; the
        # GalaxyScene picks it up and switches to the council screen.
        self.pending_council: dict | None = None
        # Set by combat_tick to battle reports the player fought in; the
        # GalaxyScene shows a combat report screen for them.
        self.pending_combat_reports: list | None = None
        # Set by combat_tick when the player is involved in an
        # engagement — the GalaxyScene routes to the Combat Options
        # decision scene first, which lets the player pick Attack,
        # Auto-resolve, or Retreat per engagement.
        self.pending_engagements: list | None = None
        # Rolling record of recent battles for review.
        self.last_combats: list = []
        # Player-perspective turn log (in-memory). Populated by
        # production, events, combat, colonization, invasion and
        # diplomacy. Surfaced as the "Last Turn" strip on galaxy view.
        self.turn_log: TurnLog = TurnLog()
        # Start-of-turn flag: are there idle player colonies needing
        # build orders? GalaxyScene shows the review screen if so.
        self.pending_idle_review: bool = False
        # Set when a victory/defeat condition is met; routes to the
        # game-over screen. {"result","mode","winner_id"}.
        self.pending_endgame: dict | None = None
        # Save/Load slot screen state (set before switching to "saves").
        self.save_screen_mode: str = "load"     # "load" | "save"
        self.save_screen_return: str = "main_menu"

        self.background = self._load_background()
        self.ui_bar = BottomUIBar(screen_width, screen_height)

        self.scenes = SceneManager()
        self.running = True
        # Shared right-click inspect tooltip. Scenes expose
        # ``tooltip_at(pos)`` to provide content; the run-loop below
        # dispatches RMB to them and draws the widget last each frame.
        self.tooltip = Tooltip()

        # Functions called after each advance_turn(). Each receives
        # (game, new_turn). Future systems (production, research) register here.
        self.turn_callbacks: list = []

    # Galaxy view reserves this many pixels at the top for the slim
    # status strip (empire summary + per-turn stats + turn).
    GALAXY_TOP_BAR_HEIGHT = 36
    # Legacy alias — some saves/scenes may still reference the old
    # right-panel constant. Kept at 0 so any consumer treats the right
    # edge as free space now.
    GALAXY_RIGHT_PANEL_WIDTH = 0

    @property
    def play_area_height(self) -> int:
        """Vertical room between the top status bar and the bottom UI
        bar — used by star generation so nothing renders under either."""
        return self.screen_height - BottomUIBar.BAR_HEIGHT - self.GALAXY_TOP_BAR_HEIGHT

    @property
    def play_area_top(self) -> int:
        """First pixel below the top status bar — stars are placed at y
        coordinates >= this value."""
        return self.GALAXY_TOP_BAR_HEIGHT

    @property
    def play_area_width(self) -> int:
        """Full screen width is now the map's horizontal room."""
        return self.screen_width

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
        # Per-run turn log; previous game's entries shouldn't bleed in.
        self.turn_log = TurnLog()
        # Colonies bombarded this turn — one orbital volley per colony
        # per turn. Cleared at the top of each advance_turn.
        self.bombarded_this_turn: set[int] = set()
        # Active Antaran raid (or None) — transient end-game threat.
        self.antaran_raid = None
        # Living system guardians (space monsters). List of dicts; see
        # ecs.monsters. Set by spawn_guardians / load_guardians.
        self.space_monsters = []

    def start_new_game(self, player_empire=None, num_empires=2, difficulty="normal",
                       galaxy_age="average"):
        clear_galaxy()
        self._reset_world()
        self.galaxy = GalaxyGenerator(
            self.entity_mgr, self.component_mgr,
            self.play_area_width, self.play_area_height,
            num_stars=self.num_stars,
            y_offset=self.play_area_top,
        )
        self.galaxy.generate(
            num_empires=num_empires, player_empire=player_empire,
            difficulty=difficulty, galaxy_age=galaxy_age,
        )
        # Fresh diplomacy — all empires neutral, no treaties. Persist so
        # the (empty) tables exist for the first save/load round-trip.
        self.diplomacy = Diplomacy()
        self.diplomacy.save()
        # Reveal each empire's starting systems before the first render.
        self.exploration = Exploration()
        self.exploration.reveal_from_world(self.component_mgr)
        self.exploration.save()
        # Fresh espionage state — no spies trained yet.
        self.espionage = Espionage()
        self.espionage.save()
        # Fresh leaders — seed a couple of candidates into the pool.
        self.leaders = LeadersManager()
        for _ in range(2):
            self.leaders.generate_candidate()
        self.leaders.save()
        # Fresh ship-design store — empty until the player authors one.
        self.ship_designs = ShipDesignManager()
        self.ship_designs.save()
        # Seed system guardians (space monsters) on the richest unowned
        # systems. Persisted to the space_monsters table.
        _spawn_guardians(self)
        self._bind_game_ui()

    def load_game(self):
        self._reset_world()
        # Bring the loaded DB's schema up to date before reading it — a
        # save from an older build may lack newer tables/columns (e.g.
        # space_monsters). init_db is idempotent (CREATE IF NOT EXISTS +
        # additive migrations, no data loss).
        init_db()
        self.galaxy = GalaxyGenerator(
            self.entity_mgr, self.component_mgr,
            self.play_area_width, self.play_area_height,
            y_offset=self.play_area_top,
        )
        self.galaxy.load_from_db()
        self.diplomacy = Diplomacy()
        self.diplomacy.load()
        self.exploration = Exploration()
        self.exploration.load()
        # Cover saves made before exploration existed: reveal current
        # holdings so the player isn't blind on a freshly-loaded game.
        self.exploration.reveal_from_world(self.component_mgr)
        self.espionage = Espionage()
        self.espionage.load()
        self.leaders = LeadersManager()
        self.leaders.load()
        self.ship_designs = ShipDesignManager()
        self.ship_designs.load()
        # Recreate ECS ships for surviving guardians (killed ones stay
        # dead — persisted in the space_monsters table).
        _load_guardians(self)
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
            "diplomacy": "diplomacy",
            "leaders": "leaders",
            "races": "races",
            "espionage": "espionage",
            "info": "info",
        }
        for button_name, scene_name in panel_targets.items():
            self.ui_bar.set_callback(
                button_name, lambda s=scene_name: self.scenes.replace(s)
            )
        self.ui_bar.set_callback("turn", self.advance_turn)

        # Register per-turn systems. Order: AI -> growth -> production ->
        # fleet movement -> combat -> diplomacy. Combat runs before
        # diplomacy so a fresh war's first battle resolves, then the
        # diplomacy tick ages treaties and decays attitudes.
        # ``_antaran_tick`` runs BEFORE combat so a freshly-spawned raid
        # fleet fights in the same turn it arrives. ``_monster_tick`` runs
        # AFTER combat so it can detect guardians killed in the battle.
        for cb in (ai_tick, _autobuild_tick, pop_growth_tick, production_tick,
                   _leaders_tick, fleet_tick, _antaran_tick, combat_tick,
                   _monster_tick, _exploration_tick, _espionage_tick,
                   _assimilation_tick, _events_tick, _diplomacy_tick):
            if cb not in self.turn_callbacks:
                self.turn_callbacks.append(cb)

        # Wire the diplomacy → player-log channel. Diplomacy fires
        # ``on_player_event(turn, kind, a, b, treaty)`` only when the
        # player is one of the involved empires.
        player = self.player_empire()
        if self.diplomacy is not None and player is not None:
            self.diplomacy.player_id = player.id
            self.diplomacy.on_player_event = self._log_diplomacy_event

    def _log_diplomacy_event(self, turn: int, kind: str, a: int, b: int,
                              treaty: str | None = None):
        """Diplomacy → turn_log bridge. Resolves empire names and writes
        a one-line, player-perspective summary. Only invoked when the
        player is one of (a, b)."""
        from ecs.turn_log import log as turn_log_fn, CAT_DIPLO
        from ecs.diplomacy import TREATY_NAMES
        player = self.player_empire()
        if player is None:
            return
        other_id = b if a == player.id else a
        other = next(
            (e for _x, e in self.component_mgr.get_all(Empire) if e.id == other_id),
            None,
        )
        other_name = other.name if other else f"Empire {other_id}"
        tname = TREATY_NAMES.get(treaty, treaty) if treaty else ""
        text = {
            "declare_war":      f"War declared with {other_name}",
            "make_peace":       f"Peace signed with {other_name}",
            "betrayal":         f"Peace broken with {other_name} — they are now at war",
            "cancel_scheduled": f"{tname} with {other_name} winding down",
            "treaty_ended":     f"{tname} with {other_name} has ended",
        }.get(kind, f"Diplomatic shift with {other_name}")
        turn_log_fn(self, CAT_DIPLO, text)

    def player_empire(self) -> Empire | None:
        for _eid, emp in self.component_mgr.get_all(Empire):
            if emp.is_player:
                return emp
        return None

    def idle_colonies(self) -> list[int]:
        """Player colonies with population but no active build and an
        empty queue — they're wasting industry and want orders."""
        player = self.player_empire()
        if player is None:
            return []
        cm = self.component_mgr
        out: list[int] = []
        for eid, owner in cm.get_all(Owner):
            if owner.empire_id != player.id:
                continue
            pop = cm.get_component(eid, Population)
            bs = cm.get_component(eid, BuildState)
            if pop is None or pop.current <= 0 or bs is None:
                continue
            if not bs.current_project and not bs.queue:
                out.append(eid)
        return out

    def advance_turn(self):
        if self.galaxy is None:
            return None
        # Fresh turn: colonies can be bombarded once more.
        self.bombarded_this_turn = set()
        new_turn = self.galaxy.advance_turn()
        for cb in self.turn_callbacks:
            cb(self, new_turn)
        # Galactic Council convenes on interval turns. Stash the result;
        # the GalaxyScene transitions to the council screen on its next
        # update so the vote is shown after the turn resolves.
        if is_council_turn(new_turn):
            self.pending_council = tally_votes(self)
        # Conquest / elimination check (skip if a result is already
        # pending, e.g. a diplomatic victory from the council).
        if self.pending_endgame is None:
            self.pending_endgame = check_endgame(self)
        # Flag idle colonies so the start-of-turn flow prompts for orders.
        self.pending_idle_review = bool(self.idle_colonies())
        return new_turn

    def quit(self):
        self.running = False

    # Global keyboard shortcuts (only fire when an in-game scene is
    # active, never on the main menu / empire setup / pause).
    _SHORTCUT_SCENES = {"galaxy", "colonies", "planets", "research", "diplomacy", "leaders", "races", "espionage", "info", "system", "colony"}
    _SHORTCUT_SCENE_KEYS = {
        pygame.K_c: "colonies",
        pygame.K_p: "planets",
        pygame.K_r: "research",
        pygame.K_d: "diplomacy",
        pygame.K_l: "leaders",
        pygame.K_e: "espionage",
        pygame.K_i: "info",
        pygame.K_g: "galaxy",
    }

    def _handle_tooltip(self, event) -> bool:
        """Right-click anywhere -> ask the active scene for tooltip
        content under the mouse; left-click or Esc hides it.

        Returns True when the event has been consumed (we don't want a
        spurious left-click stripping a tooltip to also dismiss a
        scene's selection)."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            scene = self.scenes.active
            fn = getattr(scene, "tooltip_at", None)
            lines = fn(event.pos) if fn else None
            if lines:
                self.tooltip.show(lines, event.pos)
            else:
                self.tooltip.hide()
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.tooltip.hide()
            return False  # don't consume — left-click still goes to scene
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.tooltip.visible:
                self.tooltip.hide()
                return True  # swallow this Esc — would otherwise close scene
        return False

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
                elif self._handle_tooltip(event):
                    pass  # consumed: right-click inspect or auto-hide
                elif self._handle_shortcut(event):
                    pass  # consumed by the global shortcut handler
                else:
                    self.scenes.active.handle_event(event)

            self.scenes.active.update(dt)

            self.screen.blit(self.background, (0, 0))
            self.scenes.active.draw(self.screen)
            # Tooltip draws LAST so it overlays everything (and over the
            # next scene if a click changes scenes during the same tick).
            self.tooltip.draw(self.screen)
            pygame.display.flip()

        pygame.quit()

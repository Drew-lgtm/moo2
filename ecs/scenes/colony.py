"""Colony screen — one planet's details, workers, and build queue.

Reached from SystemView by clicking a planet. Modelled after MOO2's
planet-info screen: pop + worker assignment at the top, completed
buildings + active build + queue in the middle, project picker at the
bottom (buildings row + ships row, tech-gated).

Esc returns to SystemView for the same star.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import (
    Planet, Orbiting, Position, Population, BuildState, Owner, Empire,
    Name, StarVisual,
)
from ecs.palette import planet_color, empire_color
from ecs.projects import PROJECTS
from ecs.planet_features import SPECIAL_FEATURES, RICHNESS_INDUSTRY_MULT, GRAVITY_OUTPUT_MULT
from ecs.colonization import can_colonize, colonize_planet
from ecs.invasion import can_invade, invade_planet
from ecs.refit import plan_refit, refit_ships_at_star
from ecs.db import (
    get_connection, update_planet_workers,
)


BG_COLOR = (10, 12, 24, 230)
TITLE_COLOR = (255, 230, 120)
HEADER_COLOR = (200, 200, 220)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
SELECTED_RING = (255, 230, 120)


class ColonyScene(Scene):
    WORKER_BTN_SIZE = (32, 32)
    WORKER_ROLES = [("farmers", "Farmers"), ("workers", "Workers"), ("scientists", "Scientists")]

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 14, bold=True)
        self.glyph_font = pygame.font.SysFont("Arial", 18, bold=True)

        # Hit rects rebuilt on layout.
        self._worker_widgets: list[tuple] = []  # (role, minus, plus)
        self._close_rect = pygame.Rect(0, 0, 0, 0)
        self._build_rect = pygame.Rect(0, 0, 0, 0)
        self._colonize_rect = pygame.Rect(0, 0, 0, 0)
        self._invade_rect = pygame.Rect(0, 0, 0, 0)
        self._refit_rect = pygame.Rect(0, 0, 0, 0)
        # Last invasion result for this entry into the scene — used so
        # the player sees what happened after pressing Invade.
        self._invasion_log: dict | None = None
        # Last refit outcome banner for this entry.
        self._refit_result: dict | None = None
        self._planet_entity: int | None = None

    # ------------------------------------------------------------------ lifecycle

    def on_enter(self):
        self._planet_entity = getattr(self.game, "selected_planet", None)
        # If we lost track of which planet, bail back.
        if self._planet_entity is None:
            self._return_to_system()
            return
        self._invasion_log = None
        self._refit_result = None
        self._layout()

    def on_exit(self):
        self._planet_entity = None
        self._invasion_log = None

    def _return_to_system(self):
        self.game.scenes.replace("system")

    def _return_to_galaxy(self):
        self.game.scenes.replace("galaxy")

    # ------------------------------------------------------------------ layout

    def _layout(self):
        sw, sh = self.game.screen_width, self.game.screen_height
        self._close_rect = pygame.Rect(sw - 100, 16, 80, 32)
        # Build button sits to the left of Close so the player can jump
        # to the categorised build screen.
        self._build_rect = pygame.Rect(sw - 100 - 110, 16, 100, 32)
        # Refit button — to the left of Build, only shown on a player
        # colony with at least one ship parked at the star that's not
        # already running the empire's current best loadout.
        self._refit_rect = pygame.Rect(sw - 100 - 110 - 140, 16, 130, 32)
        # Colonize button overlays the Build slot when the planet is
        # uncolonized; only one of the two will be visible at a time.
        self._colonize_rect = pygame.Rect(sw - 100 - 130, 16, 120, 32)
        # Invade button — shown on enemy planets when the player has
        # Troop Transports parked at the star. Same slot as Colonize.
        self._invade_rect = pygame.Rect(sw - 100 - 130, 16, 120, 32)

        # Worker pickers across the upper third.
        self._worker_widgets.clear()
        btn_w, btn_h = self.WORKER_BTN_SIZE
        cluster_w = 200
        total_w = len(self.WORKER_ROLES) * cluster_w
        start_x = (sw - total_w) // 2
        # Worker pickers sit below the descriptor chip row.
        y = 168
        for i, (role, _label) in enumerate(self.WORKER_ROLES):
            cluster_x = start_x + i * cluster_w
            minus_rect = pygame.Rect(cluster_x + 40, y, btn_w, btn_h)
            plus_rect = pygame.Rect(cluster_x + cluster_w - 40 - btn_w, y, btn_w, btn_h)
            self._worker_widgets.append((role, minus_rect, plus_rect))

    # ------------------------------------------------------------------ helpers

    def _planet_components(self):
        cm = self.game.component_mgr
        if self._planet_entity is None:
            return None, None, None, None
        planet = cm.get_component(self._planet_entity, Planet)
        pop = cm.get_component(self._planet_entity, Population)
        build_state = cm.get_component(self._planet_entity, BuildState)
        owner = cm.get_component(self._planet_entity, Owner)
        return planet, pop, build_state, owner

    def _star_name(self) -> str:
        if self._planet_entity is None:
            return ""
        orbit = self.game.component_mgr.get_component(self._planet_entity, Orbiting)
        if orbit is None:
            return ""
        name = self.game.component_mgr.get_component(orbit.star_entity, Name)
        return name.value if name else ""

    def _player_empire_id(self):
        for _eid, empire in self.game.component_mgr.get_all(Empire):
            if empire.is_player:
                return empire.id
        return None

    def _player_owns_this(self, owner) -> bool:
        return owner is not None and owner.empire_id == self._player_empire_id()

    def _can_colonize_here(self) -> bool:
        """True when the active planet is settleable by the player —
        unowned, habitable, with a colony ship parked at its star."""
        if self._planet_entity is None:
            return False
        empire_id = self._player_empire_id()
        if empire_id is None:
            return False
        return can_colonize(self.game.component_mgr, self._planet_entity, empire_id)

    def _can_invade_here(self) -> bool:
        """True when the planet is enemy-owned and the player has at
        least one Troop Transport parked at its star."""
        if self._planet_entity is None:
            return False
        empire_id = self._player_empire_id()
        if empire_id is None:
            return False
        return can_invade(self.game.component_mgr, self._planet_entity, empire_id)

    def tooltip_at(self, pos):
        """Right-click an action button on the colony screen."""
        if self._build_rect.collidepoint(pos):
            return ["Build",
                    "hint: open the build queue for this colony"]
        if self._refit_rect.collidepoint(pos):
            plan = self._refit_plan()
            if plan and plan["to_refit"] > 0:
                return ["Refit Fleet",
                        f"hint: bring {plan['to_refit']} parked ship(s) up to current tech",
                        f"hint: cost {plan['total_cost']} BC (40% of build cost per ship)"]
            return ["Refit Fleet", "hint: no eligible ships parked here"]
        if self._colonize_rect.collidepoint(pos):
            return ["Colonize",
                    "hint: spend the colony ship parked at this star to found a colony"]
        if self._invade_rect.collidepoint(pos):
            return ["Invade",
                    "hint: send marines from your parked Troop Transports"]
        return None

    def _star_entity(self) -> int | None:
        if self._planet_entity is None:
            return None
        orbit = self.game.component_mgr.get_component(self._planet_entity, Orbiting)
        return orbit.star_entity if orbit is not None else None

    def _refit_plan(self) -> dict | None:
        """Returns the refit summary for the player's ships parked at
        this colony's star, or None if nothing applies (no star, no
        player empire, no ships)."""
        star = self._star_entity()
        empire_id = self._player_empire_id()
        if star is None or empire_id is None:
            return None
        return plan_refit(self.game.component_mgr, star, empire_id)

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._return_to_system()
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        if self._close_rect.collidepoint(event.pos):
            self._return_to_galaxy()
            return
        # Owned planets get a Build button; unowned habitable ones get
        # Colonize; enemy-owned ones get Invade when the player has a
        # Troop Transport parked at the star.
        planet, _pop, _build_state, owner = self._planet_components()
        player_id = self._player_empire_id()
        if owner is None and self._can_colonize_here():
            if self._colonize_rect.collidepoint(event.pos):
                if player_id is not None and self._planet_entity is not None:
                    colonize_planet(self.game, self._planet_entity, player_id)
                    self._return_to_system()
                return
        elif (owner is not None and player_id is not None
              and owner.empire_id != player_id and self._can_invade_here()):
            if self._invade_rect.collidepoint(event.pos):
                if self._planet_entity is not None:
                    self._invasion_log = invade_planet(
                        self.game, self._planet_entity, player_id,
                    )
                return
        elif owner is not None and player_id is not None and owner.empire_id == player_id:
            if self._build_rect.collidepoint(event.pos):
                # Open the categorised build screen for this planet.
                self.game.scenes.replace("build")
                return
            # Refit fleet at this colony — applies the empire's current
            # best loadout to every parked ship for a fraction of build cost.
            plan = self._refit_plan()
            if (plan is not None and plan["to_refit"] > 0
                    and self._refit_rect.collidepoint(event.pos)):
                star = self._star_entity()
                if star is not None:
                    self._refit_result = refit_ships_at_star(
                        self.game, star, player_id,
                    )
                return

        # Worker +/- buttons
        for role, minus_rect, plus_rect in self._worker_widgets:
            if minus_rect.collidepoint(event.pos):
                self._try_shift_worker(role, -1)
                return
            if plus_rect.collidepoint(event.pos):
                self._try_shift_worker(role, +1)
                return

    def _try_shift_worker(self, role: str, delta: int):
        _planet, pop, _bs, owner = self._planet_components()
        if pop is None or not self._player_owns_this(owner):
            return

        other_order = [r for r in ("workers", "scientists", "farmers") if r != role]
        if delta > 0:
            for src in other_order:
                if getattr(pop, src) > 0:
                    setattr(pop, src, getattr(pop, src) - 1)
                    setattr(pop, role, getattr(pop, role) + 1)
                    break
            else:
                return
        else:
            if getattr(pop, role) <= 0:
                return
            setattr(pop, role, getattr(pop, role) - 1)
            setattr(pop, other_order[0], getattr(pop, other_order[0]) + 1)

        planet, _, _, _ = self._planet_components()
        if planet is not None:
            with get_connection() as conn:
                update_planet_workers(conn, planet.id, pop.farmers, pop.workers, pop.scientists)
                conn.commit()

    # Project selection moved to BuildScene (reached via Build button).

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height

        # Overlay
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))

        planet, pop, build_state, owner = self._planet_components()
        if planet is None:
            return

        self._draw_header(screen, planet, owner)
        self._draw_pop_block(screen, pop, owner)
        self._draw_worker_widgets(screen, pop, owner)
        self._draw_build_summary(screen, build_state)
        player_id = self._player_empire_id()
        if owner is None:
            self._draw_colonize_button(screen, planet)
        elif player_id is not None and owner.empire_id != player_id:
            self._draw_invade_button(screen, planet)
        else:
            self._draw_build_button(screen, owner)
            self._draw_refit_button(screen, owner)
        self._draw_close_button(screen)
        self._draw_invasion_log(screen)
        self._draw_refit_banner(screen)

    def _draw_close_button(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

    def _draw_build_button(self, screen, owner):
        # Disabled if the player doesn't own this colony.
        owns = self._player_owns_this(owner)
        bg = (60, 100, 60) if owns else (40, 44, 56)
        border = (180, 220, 180) if owns else (90, 90, 110)
        fg = TEXT_COLOR if owns else (130, 130, 150)
        pygame.draw.rect(screen, bg, self._build_rect)
        pygame.draw.rect(screen, border, self._build_rect, 1)
        label = self.body_font.render("Build", True, fg)
        screen.blit(label, label.get_rect(center=self._build_rect.center))

    def _draw_refit_button(self, screen, owner):
        """Visible only when the player owns this colony AND has at
        least one ship parked at its star that's not already running the
        empire's current best loadout. Shows the total BC cost on the
        button; disabled when broke."""
        if not self._player_owns_this(owner):
            return
        plan = self._refit_plan()
        if plan is None or plan["to_refit"] <= 0:
            return
        cost = plan["total_cost"]
        # Affordable?
        affordable = False
        for _eid, emp in self.game.component_mgr.get_all(Empire):
            if emp.is_player:
                affordable = emp.bc >= cost
                break
        if affordable:
            bg, border, fg = (60, 70, 110), (160, 180, 230), TEXT_COLOR
        else:
            bg, border, fg = (40, 44, 56), (110, 110, 130), (150, 150, 165)
        pygame.draw.rect(screen, bg, self._refit_rect)
        pygame.draw.rect(screen, border, self._refit_rect, 1)
        label = self.body_font.render(
            f"Refit {plan['to_refit']} ({cost} BC)", True, fg)
        screen.blit(label, label.get_rect(center=self._refit_rect.center))

    def _draw_invade_button(self, screen, planet):
        """Visible on enemy-owned planets when the player has Troop
        Transports parked at this star. Red treatment to telegraph that
        the action starts a fight."""
        able = self._can_invade_here()
        if able:
            bg, border, fg = (110, 30, 30), (240, 140, 140), TEXT_COLOR
        else:
            bg, border, fg = (40, 44, 56), (120, 100, 100), (160, 130, 130)
        pygame.draw.rect(screen, bg, self._invade_rect)
        pygame.draw.rect(screen, border, self._invade_rect, 1)
        label = self.body_font.render("Invade", True, fg)
        screen.blit(label, label.get_rect(center=self._invade_rect.center))
        if not able:
            hint_surf = self.body_font.render(
                "Need Troop Transport here", True, HINT_COLOR,
            )
            screen.blit(hint_surf, hint_surf.get_rect(midtop=(
                self._invade_rect.centerx, self._invade_rect.bottom + 4,
            )))

    def _draw_invasion_log(self, screen):
        """One-line summary of the last invasion result on this scene
        entry — sits just under the descriptor chip row so the player
        can see what happened. Cleared when the scene is exited."""
        if self._invasion_log is None:
            return
        log = self._invasion_log
        if log.get("success"):
            text = (
                f"Invasion succeeded — atk {log['attacker_strength']} "
                f"vs def {log['defender_strength']}.  "
                f"Lost {log['transports_lost']} transports, "
                f"pop reduced by {log['pop_lost']}M."
            )
            color = (160, 220, 160)
        elif log.get("reason"):
            text = "Invasion failed: " + log["reason"].replace("_", " ")
            color = (220, 160, 160)
        else:
            text = (
                f"Invasion repelled — atk {log['attacker_strength']} "
                f"vs def {log['defender_strength']}.  "
                f"Lost {log['transports_lost']} transports; "
                f"defenders took {log['pop_lost']}M casualties."
            )
            color = (220, 160, 160)
        surf = self.body_font.render(text, True, color)
        screen.blit(surf, (24, 144))

    def _draw_refit_banner(self, screen):
        """One-line outcome of the last refit on this scene entry."""
        r = self._refit_result
        if r is None:
            return
        status = r.get("status")
        if status == "ok":
            text = f"Refitted {r['refitted']} ship(s) for {r['spent']} BC."
            color = (160, 220, 230)
        elif status == "unaffordable":
            text = (f"Refit needs {r['cost']} BC — you only have {r.get('bc', 0)}.")
            color = (220, 160, 160)
        else:
            text = "All parked ships already carry the current best loadout."
            color = (180, 180, 180)
        surf = self.body_font.render(text, True, color)
        screen.blit(surf, (24, 144))

    def _draw_colonize_button(self, screen, planet):
        """Visible on uncolonized planets. Active when the player has a
        Colony Ship parked at this star and the planet is habitable."""
        able = self._can_colonize_here()
        if able:
            bg, border, fg = (60, 100, 60), (180, 220, 180), TEXT_COLOR
        elif planet is not None and not planet.colonizable:
            bg, border, fg = (40, 44, 56), (90, 90, 110), (130, 130, 150)
        else:
            # Habitable but no colony ship here — hint the player by
            # rendering the button in a "ghost" style.
            bg, border, fg = (40, 44, 56), (120, 120, 140), (160, 160, 170)
        pygame.draw.rect(screen, bg, self._colonize_rect)
        pygame.draw.rect(screen, border, self._colonize_rect, 1)
        label = self.body_font.render("Colonize", True, fg)
        screen.blit(label, label.get_rect(center=self._colonize_rect.center))
        if not able:
            # One-line reason underneath so the player knows what's
            # missing.
            if planet is not None and not planet.colonizable:
                hint = "Not habitable"
            else:
                hint = "Need Colony Ship here"
            hint_surf = self.body_font.render(hint, True, HINT_COLOR)
            screen.blit(hint_surf, hint_surf.get_rect(midtop=(
                self._colonize_rect.centerx, self._colonize_rect.bottom + 4,
            )))

    def _draw_header(self, screen, planet, owner):
        cm = self.game.component_mgr
        star_name = self._star_name()
        title = f"{star_name} - {planet.planet_type} {planet.size}"
        title_surf = self.title_font.render(title, True, TITLE_COLOR)
        screen.blit(title_surf, (24, 16))

        # Type dot
        pygame.draw.circle(screen, planet_color(planet.planet_type), (24 + 8, 60), 8)
        # Owner color bar
        if owner is not None:
            emp = next((e for _eid, e in cm.get_all(Empire) if e.id == owner.empire_id), None)
            if emp is not None:
                pygame.draw.rect(screen, empire_color(emp.color), pygame.Rect(48, 50, 8, 20))
                emp_label = self.header_font.render(emp.name, True, TEXT_COLOR)
                screen.blit(emp_label, (64, 52))
        else:
            screen.blit(self.header_font.render("Uncolonized", True, HINT_COLOR), (48, 52))

        # Descriptors line: Richness · Gravity · Specials. Sits under the
        # title and to the right of the type dot/owner.
        rich_mult = RICHNESS_INDUSTRY_MULT.get(planet.richness, 1.0)
        grav_mult = GRAVITY_OUTPUT_MULT.get(planet.gravity, 1.0)
        chips = [
            (f"{planet.richness} (Ind ×{rich_mult:g})",
             (200, 180, 120) if rich_mult >= 1.0 else (220, 140, 120)),
            (f"{planet.gravity} grav (×{grav_mult:g})",
             (180, 200, 220) if grav_mult >= 1.0 else (220, 140, 120)),
        ]
        for key in planet.special:
            meta = SPECIAL_FEATURES.get(key, {})
            chips.append((meta.get("name", key), (220, 200, 120)))

        cx = 24
        cy = 76
        for text, color in chips:
            chip = self.body_font.render(text, True, color)
            chip_rect = chip.get_rect()
            bg_rect = chip_rect.inflate(12, 6).move(cx, cy)
            pygame.draw.rect(screen, (30, 34, 50), bg_rect)
            pygame.draw.rect(screen, color, bg_rect, width=1)
            screen.blit(chip, (bg_rect.x + 6, bg_rect.y + 3))
            cx += bg_rect.width + 8

    def _draw_pop_block(self, screen, pop, owner):
        # Sits between the descriptor chips (~y=76-100) and worker widgets (y=168).
        if pop is None:
            screen.blit(self.header_font.render("No population", True, HINT_COLOR), (24, 124))
            return
        # 1 pop unit = 1 million inhabitants (MOO2 convention).
        line = f"Population: {pop.current}M / {pop.max}M    F:{pop.farmers}  W:{pop.workers}  S:{pop.scientists}"
        screen.blit(self.header_font.render(line, True, TEXT_COLOR), (24, 124))

    def _draw_worker_widgets(self, screen, pop, owner):
        editable = pop is not None and self._player_owns_this(owner)
        for role, minus_rect, plus_rect in self._worker_widgets:
            # Label above the cluster
            short = {"farmers": "Farmers", "workers": "Workers", "scientists": "Scientists"}[role]
            label_surf = self.body_font.render(short, True, TEXT_COLOR)
            mid_x = (minus_rect.left + plus_rect.right) // 2
            screen.blit(label_surf, label_surf.get_rect(midtop=(mid_x, minus_rect.top - 22)))

            count = getattr(pop, role) if pop is not None else 0
            value_surf = self.title_font.render(str(count), True, TEXT_COLOR)
            screen.blit(value_surf, value_surf.get_rect(center=(mid_x, minus_rect.centery)))

            for btn_rect, glyph in ((minus_rect, "−"), (plus_rect, "+")):
                bg = (60, 64, 96) if editable else (40, 44, 60)
                border = (180, 180, 220) if editable else (90, 90, 110)
                fg = TEXT_COLOR if editable else (130, 130, 150)
                pygame.draw.rect(screen, bg, btn_rect)
                pygame.draw.rect(screen, border, btn_rect, 1)
                gs = self.glyph_font.render(glyph, True, fg)
                screen.blit(gs, gs.get_rect(center=btn_rect.center))

    def _draw_build_summary(self, screen, build_state):
        x, y = 24, 220
        if build_state is None:
            screen.blit(self.body_font.render("No build state.", True, HINT_COLOR), (x, y))
            return
        # Completed
        if build_state.completed:
            names = [PROJECTS[pid]["name"] for pid in build_state.completed if pid in PROJECTS]
            completed_str = "Buildings: " + ", ".join(names)
        else:
            completed_str = "Buildings: (none)"
        screen.blit(self.body_font.render(completed_str, True, TEXT_COLOR), (x, y))

        # Active project
        if build_state.current_project:
            proj = PROJECTS.get(build_state.current_project, {})
            active = f"Building: {proj.get('name', build_state.current_project)} {build_state.progress}/{proj.get('cost', '?')}"
            screen.blit(self.body_font.render(active, True, (220, 200, 120)), (x, y + 22))
        else:
            screen.blit(self.body_font.render("Building: (idle)", True, HINT_COLOR), (x, y + 22))

        # Queue
        if build_state.queue:
            queue_names = [PROJECTS[pid]["name"] for pid in build_state.queue if pid in PROJECTS]
            queue_str = "Queue: " + " > ".join(queue_names)
            screen.blit(self.body_font.render(queue_str, True, (120, 180, 255)), (x, y + 44))


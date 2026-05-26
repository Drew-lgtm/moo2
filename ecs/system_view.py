"""Overlay shown for one star system: orbital map + parked fleets.

Clicking a planet opens that planet's ColonyScene. Esc / Close returns
to the galaxy view. The per-planet worker/build UI lives in ColonyScene
now — this view is intentionally just the orbital overview, matching
MOO2's two-screen flow (system -> planet info).
"""
from __future__ import annotations

import pygame

from ecs.components import (
    Planet, Orbiting, Position, Population, BuildState, Owner, Empire,
    Ship, ShipOwner, ShipAt,
)
from ecs.palette import planet_color, empire_color
from ecs.projects import PROJECTS


SIZE_RADIUS = {
    "Tiny":   10,
    "Small":  18,
    "Medium": 28,
    "Large":  38,
    "Huge":   50,
}
STAR_RADIUS = 36         # central star disc — was 12
ORBIT_BASE = 110         # innermost orbit radius — was 60
ORBIT_STEP = 80          # additional radius per orbit — was 40


class SystemView:
    """Orbital map for one star.

    Public flags consumed by the SystemViewScene wrapper:
    - ``is_open``: False when the user wants to close the view.
    - ``pending_planet_click``: set to an entity id when a planet was
      clicked this tick; the wrapper transitions to ColonyScene with
      that planet selected, then clears it.
    """

    def __init__(self, screen, component_mgr, star_id, logical_size=None):
        self.screen = screen
        self.component_mgr = component_mgr
        self.star_id = star_id
        self.is_open = True
        self.pending_planet_click: int | None = None

        if logical_size is None:
            logical_size = (screen.get_width(), screen.get_height())
        self.logical_w, self.logical_h = logical_size

        self.close_button_rect = pygame.Rect(self.logical_w - 100, 20, 80, 30)
        self.star_pos = component_mgr.get_component(star_id, Position)

        # (entity_id, planet, center_pos, hit_radius) — fixed at construction.
        center = (self.logical_w // 2, self.logical_h // 2)
        self.planet_layout: list[tuple[int, Planet, tuple[int, int], int]] = []
        i = 0
        for entity_id, orbit in component_mgr.get_all(Orbiting):
            if orbit.star_entity != star_id:
                continue
            planet = component_mgr.get_component(entity_id, Planet)
            if planet is None:
                continue
            orbit_radius = ORBIT_BASE + i * ORBIT_STEP
            pos = (center[0] + orbit_radius, center[1])
            radius = SIZE_RADIUS.get(planet.size, 20)
            self.planet_layout.append((entity_id, planet, pos, radius))
            i += 1

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.is_open = False
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_button_rect.collidepoint(event.pos):
                self.is_open = False
                return
            for entity_id, _planet, pos, radius in self.planet_layout:
                hit = max(radius + 6, 14)
                dx = event.pos[0] - pos[0]
                dy = event.pos[1] - pos[1]
                if dx * dx + dy * dy <= hit * hit:
                    self.pending_planet_click = entity_id
                    return

    # ------------------------------------------------------------------ draw

    def draw(self, font):
        overlay = pygame.Surface((self.logical_w, self.logical_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))

        center = (self.logical_w // 2, self.logical_h // 2)
        # Star at center: layered discs build a soft halo that survives
        # SCALED's non-integer downscaling. Thin (1-2 px) strokes were
        # vanishing in places on laptop displays — every ring here is at
        # least 3 px wide so the outline reads cleanly.
        pygame.draw.circle(overlay, (180, 130, 50), center, STAR_RADIUS + 10, 3)
        pygame.draw.circle(overlay, (255, 200, 90), center, STAR_RADIUS + 4, 3)
        pygame.draw.circle(overlay, (255, 230, 120), center, STAR_RADIUS)

        for entity_id, planet, pos, radius in self.planet_layout:
            # Orbit ring: 2 px wide for visibility — single-pixel rings
            # disappeared at fractional scale factors.
            orbit_radius = pos[0] - center[0]
            pygame.draw.circle(overlay, (110, 110, 130), center, orbit_radius, 2)

            # Planet body + a black ring just inside the white halo gives
            # the outline contrast against bright planet colors (Desert,
            # Tundra) on dark space; 3 px white ring outside reads as
            # "clickable".
            pygame.draw.circle(overlay, planet_color(planet.planet_type), pos, radius)
            pygame.draw.circle(overlay, (0, 0, 0), pos, radius + 1, 1)
            pygame.draw.circle(overlay, (255, 255, 255), pos, radius + 3, 3)

            self._draw_planet_labels(overlay, font, entity_id, planet, pos)

        # Close button.
        pygame.draw.rect(overlay, (150, 0, 0), self.close_button_rect)
        close_text = font.render("Close", True, (255, 255, 255))
        overlay.blit(close_text, (self.close_button_rect.x + 10, self.close_button_rect.y + 5))

        self._draw_fleets_in_system(overlay, font)
        # Hint
        hint = font.render(
            "Click a planet to open its colony.   Esc returns to galaxy.",
            True, (200, 200, 200),
        )
        overlay.blit(hint, (24, self.logical_h - 32))

        self.screen.blit(overlay, (0, 0))

    def _draw_planet_labels(self, overlay, font, entity_id, planet, pos):
        x, y = pos
        # Labels start just below the planet's lower edge — scales with
        # SIZE_RADIUS so big planets don't overlap their captions.
        radius = SIZE_RADIUS.get(planet.size, 20)
        line_y = y + radius + 6
        # Line 1: type + size shorthand, with richness/gravity glyphs.
        # Glyphs are MOO2-style shorthand so the system view stays scannable.
        rich_glyph = {"Ultra Poor": "--", "Poor": "-", "Abundant": "",
                      "Rich": "+", "Ultra Rich": "++"}.get(
            getattr(planet, "richness", "Abundant"), "")
        grav_glyph = {"Low": "↓", "Heavy": "↑"}.get(
            getattr(planet, "gravity", "Normal"), "")
        special = getattr(planet, "special", [])
        special_glyph = "★" if special else ""
        suffix = f" {rich_glyph}{grav_glyph}{special_glyph}".rstrip()
        type_label = font.render(
            f"{planet.planet_type[:3]} {planet.size[:1]}{suffix}",
            True, (255, 255, 255),
        )
        overlay.blit(type_label, (x - 15, line_y))
        line_y += 14

        # Line 2: pop + F/W/S.
        population = self.component_mgr.get_component(entity_id, Population)
        if population is not None:
            # MOO2 convention: each pop unit = 1 million inhabitants.
            pop_label = font.render(
                f"{population.current}M/{population.max}M  {population.farmers}/{population.workers}/{population.scientists}",
                True, (180, 220, 255),
            )
            overlay.blit(pop_label, (x - 30, line_y))
            line_y += 14

        # Line 3: brief project status.
        build_state = self.component_mgr.get_component(entity_id, BuildState)
        if build_state is not None:
            if build_state.current_project:
                proj = PROJECTS.get(build_state.current_project, {})
                text = f"{proj.get('name', build_state.current_project)} {build_state.progress}/{proj.get('cost', '?')}"
                if build_state.queue:
                    text += f" +{len(build_state.queue)}"
                color = (220, 200, 120)
            elif build_state.completed:
                text = f"Built: {len(build_state.completed)}"
                color = (160, 200, 160)
            else:
                text = "(idle)"
                color = (160, 160, 160)
            overlay.blit(font.render(text, True, color), (x - 35, line_y))

    def _draw_fleets_in_system(self, overlay, font):
        cm = self.component_mgr
        by_empire: dict[int, list[int]] = {}
        for ship_entity, at in cm.get_all(ShipAt):
            if at.star_entity != self.star_id:
                continue
            owner = cm.get_component(ship_entity, ShipOwner)
            if owner is None:
                continue
            by_empire.setdefault(owner.empire_id, []).append(ship_entity)
        if not by_empire:
            return

        empire_info = {emp.id: (emp.name, emp.color) for _e, emp in cm.get_all(Empire)}

        x, y = 24, 60
        overlay.blit(font.render("Fleets in system:", True, (220, 220, 220)), (x, y))
        y += 22
        for empire_id, ships in sorted(by_empire.items()):
            name, color_name = empire_info.get(empire_id, (f"Empire {empire_id}", "blue"))
            rgb = empire_color(color_name)

            chevron = [(x, y + 2), (x, y + 18), (x + 14, y + 10)]
            pygame.draw.polygon(overlay, rgb, chevron)
            pygame.draw.polygon(overlay, (240, 240, 240), chevron, 1)

            total = len(ships)
            header = font.render(f"{name}: {total} ship{'s' if total != 1 else ''}", True, (240, 240, 240))
            overlay.blit(header, (x + 22, y))
            y += 20

            by_class: dict[str, int] = {}
            for ship_entity in ships:
                ship = cm.get_component(ship_entity, Ship)
                if ship is None:
                    continue
                by_class[ship.ship_class] = by_class.get(ship.ship_class, 0) + 1
            pieces = [f"{cls.capitalize()} x{n}" for cls, n in sorted(by_class.items())]
            if pieces:
                detail = font.render("  " + ", ".join(pieces), True, (180, 200, 220))
                overlay.blit(detail, (x + 22, y))
                y += 22

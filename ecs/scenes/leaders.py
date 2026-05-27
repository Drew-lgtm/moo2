"""Leaders screen — hire heroes and assign them.

Left: your retained leaders (each with an Assign button that cycles
through valid targets, and a Dismiss button) above the hiring pool of
randomly-appearing candidates. Right: a log of recent leader events.

Colony leaders boost the colony they govern; ship leaders boost the
warship they captain. Assignments and hires persist immediately. Esc /
Close returns to the galaxy view.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire, Owner, Planet, Orbiting, Name, Ship, ShipOwner
from ecs.leaders import MAX_LEADERS_PER_EMPIRE, WARSHIP_CLASSES
from ecs.db import get_connection, update_empire_economy


BG_COLOR = (10, 12, 24, 235)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
ROW_BG = (24, 28, 42)
POOL_BG = (20, 30, 28)
BTN_BG = (50, 56, 84)
BTN_BORDER = (150, 160, 200)
GOOD_COLOR = (150, 220, 160)
BAD_COLOR = (240, 130, 130)
COLONY_TINT = (150, 200, 240)
SHIP_TINT = (240, 180, 140)


class LeadersScene(Scene):
    ROW_H = 40

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 15, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 13, bold=True)

        self.banner = ""
        self.banner_color = HINT_COLOR
        self._hits: list[tuple[str, object, pygame.Rect]] = []
        self._close_rect = pygame.Rect(0, 0, 0, 0)

    def on_enter(self):
        self._close_rect = pygame.Rect(self.game.screen_width - 100, 16, 80, 32)

    # ------------------------------------------------------------------ helpers

    def _player(self):
        return self.game.player_empire()

    def _colony_targets(self):
        """[(planet_id, label)] for the player's colonies."""
        cm = self.game.component_mgr
        player = self._player()
        out = []
        for eid, owner in cm.get_all(Owner):
            if player is None or owner.empire_id != player.id:
                continue
            planet = cm.get_component(eid, Planet)
            if planet is None:
                continue
            star_name = "?"
            orbit = cm.get_component(eid, Orbiting)
            if orbit is not None:
                nm = cm.get_component(orbit.star_entity, Name)
                if nm is not None:
                    star_name = nm.value
            out.append((planet.id, f"{star_name} {planet.planet_type}"))
        return out

    def _ship_targets(self):
        """[(ship_id, label)] for the player's warships."""
        cm = self.game.component_mgr
        player = self._player()
        out = []
        for ship_entity, owner in cm.get_all(ShipOwner):
            if player is None or owner.empire_id != player.id:
                continue
            ship = cm.get_component(ship_entity, Ship)
            if ship is None or ship.ship_class not in WARSHIP_CLASSES:
                continue
            out.append((ship.id, f"{ship.ship_class.replace('_', ' ').title()} #{ship.id}"))
        return out

    def _assignment_label(self, leader):
        if leader.category == "colony":
            if leader.assigned_planet_id is None:
                return "Unassigned"
            for pid, label in self._colony_targets():
                if pid == leader.assigned_planet_id:
                    return label
            return "Unassigned"
        else:
            if leader.assigned_ship_id is None:
                return "Unassigned"
            for sid, label in self._ship_targets():
                if sid == leader.assigned_ship_id:
                    return label
            return "Unassigned"

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.scenes.replace("galaxy")
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if self._close_rect.collidepoint(event.pos):
            self.game.scenes.replace("galaxy")
            return
        for action, payload, rect in self._hits:
            if rect.collidepoint(event.pos):
                self._do(action, payload)
                return

    def _do(self, action, leader_id):
        mgr = self.game.leaders
        player = self._player()
        if mgr is None or player is None:
            return
        leader = mgr.leaders.get(leader_id)
        if leader is None:
            return
        if action == "hire":
            if mgr.count_for(player.id) >= MAX_LEADERS_PER_EMPIRE:
                self.banner, self.banner_color = "Leader roster is full.", BAD_COLOR
            elif player.bc < leader.hire_cost:
                self.banner, self.banner_color = "Not enough BC to hire.", BAD_COLOR
            elif mgr.hire(leader_id, player.id):
                player.bc -= leader.hire_cost
                with get_connection() as conn:
                    update_empire_economy(conn, player.id, player.bc, player.research_points)
                    conn.commit()
                mgr.save()
                self.banner, self.banner_color = f"Hired {leader.name}.", GOOD_COLOR
        elif action == "assign":
            self._cycle_assignment(leader)
            mgr.save()
        elif action == "dismiss":
            mgr.dismiss(leader_id)
            mgr.save()
            self.banner, self.banner_color = f"Dismissed {leader.name}.", HINT_COLOR

    def _cycle_assignment(self, leader):
        mgr = self.game.leaders
        if leader.category == "colony":
            options = [None] + [pid for pid, _l in self._colony_targets()]
            cur = leader.assigned_planet_id
            nxt = options[(options.index(cur) + 1) % len(options)] if cur in options else (options[1] if len(options) > 1 else None)
            mgr.assign_colony(leader.id, nxt)
        else:
            options = [None] + [sid for sid, _l in self._ship_targets()]
            cur = leader.assigned_ship_id
            nxt = options[(options.index(cur) + 1) % len(options)] if cur in options else (options[1] if len(options) > 1 else None)
            mgr.assign_ship(leader.id, nxt)

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._hits = []

        screen.blit(self.title_font.render("Leaders", True, TITLE_COLOR), (20, 12))

        mgr = self.game.leaders
        player = self._player()
        if mgr is None or player is None:
            screen.blit(self.header_font.render("No player empire.", True, HINT_COLOR), (20, 60))
            self._draw_close(screen)
            return

        roster = mgr.for_empire(player.id)
        status = (f"BC: {player.bc}    Leaders: {len(roster)}/{MAX_LEADERS_PER_EMPIRE}"
                  f"    Salary: {mgr.salary_total(player.id)}/turn")
        screen.blit(self.header_font.render(status, True, TEXT_COLOR), (20, 48))
        if self.banner:
            screen.blit(self.body_font.render(self.banner, True, self.banner_color), (20, 74))

        left_w = int(sw * 0.66)
        y = 104
        screen.blit(self.header_font.render("Your Leaders", True, TITLE_COLOR), (20, y))
        y += 28
        if not roster:
            screen.blit(self.small_font.render("None hired yet.", True, HINT_COLOR), (24, y))
            y += 24
        for leader in roster:
            y = self._draw_roster_row(screen, leader, y, left_w)

        y += 12
        screen.blit(self.header_font.render("For Hire", True, TITLE_COLOR), (20, y))
        y += 28
        pool = mgr.pool()
        if not pool:
            screen.blit(self.small_font.render("No candidates available — check back later.",
                                               True, HINT_COLOR), (24, y))
        for leader in pool:
            y = self._draw_pool_row(screen, leader, y, left_w, player)
            if y > sh - 80:
                break

        self._draw_log(screen, mgr, left_w + 20, sw - 20)
        self._draw_close(screen)
        hint = self.small_font.render(
            "Hire heroes, then Assign cycles their post.   Esc returns to galaxy.",
            True, HINT_COLOR)
        screen.blit(hint, (20, sh - hint.get_height() - 12))

    def _draw_roster_row(self, screen, leader, y, right_edge):
        rect = pygame.Rect(20, y, right_edge - 40, self.ROW_H - 6)
        pygame.draw.rect(screen, ROW_BG, rect)
        tint = COLONY_TINT if leader.category == "colony" else SHIP_TINT
        pygame.draw.rect(screen, tint, pygame.Rect(rect.x + 4, rect.y + 4, 6, rect.height - 8))
        info = f"{leader.name} — {leader.skill_name} Lv.{leader.level} ({leader.effect_text()})"
        screen.blit(self.body_font.render(info, True, TEXT_COLOR), (rect.x + 16, rect.y + 3))
        assign_lbl = self._assignment_label(leader)
        screen.blit(self.small_font.render(f"Post: {assign_lbl}", True, tint), (rect.x + 16, rect.y + 19))

        # Buttons on the right of the row.
        bx = rect.right - 170
        assign_rect = pygame.Rect(bx, rect.y + 5, 100, rect.height - 10)
        self._button(screen, assign_rect, "Assign →")
        self._hits.append(("assign", leader.id, assign_rect))
        dismiss_rect = pygame.Rect(bx + 108, rect.y + 5, 56, rect.height - 10)
        self._button(screen, dismiss_rect, "Fire", border=BAD_COLOR)
        self._hits.append(("dismiss", leader.id, dismiss_rect))
        return y + self.ROW_H

    def _draw_pool_row(self, screen, leader, y, right_edge, player):
        rect = pygame.Rect(20, y, right_edge - 40, self.ROW_H - 6)
        pygame.draw.rect(screen, POOL_BG, rect)
        tint = COLONY_TINT if leader.category == "colony" else SHIP_TINT
        kind = "Colony" if leader.category == "colony" else "Ship"
        info = (f"{leader.name} — {kind} · {leader.skill_name} Lv.{leader.level} "
                f"({leader.effect_text()})  ·  {leader.salary}/turn")
        screen.blit(self.body_font.render(info, True, TEXT_COLOR), (rect.x + 12, rect.y + 8))
        hire_rect = pygame.Rect(rect.right - 150, rect.y + 5, 140, rect.height - 10)
        afford = player.bc >= leader.hire_cost
        self._button(screen, hire_rect, f"Hire ({leader.hire_cost})",
                     enabled=afford)
        self._hits.append(("hire", leader.id, hire_rect))
        return y + self.ROW_H

    def _button(self, screen, rect, label, enabled=True, border=BTN_BORDER):
        fill = BTN_BG if enabled else (38, 40, 52)
        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, border, rect, 1)
        color = TEXT_COLOR if enabled else (130, 130, 150)
        surf = self.small_font.render(label, True, color)
        screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_log(self, screen, mgr, x0, x1):
        screen.blit(self.header_font.render("Court News", True, TITLE_COLOR), (x0, 104))
        y = 132
        width = x1 - x0
        for line in reversed(mgr.log[-14:]):
            for chunk in self._wrap(line, width):
                screen.blit(self.small_font.render(chunk, True, TEXT_COLOR), (x0, y))
                y += 18
            y += 4
            if y > self.game.screen_height - 60:
                break
        if not mgr.log:
            screen.blit(self.small_font.render("Quiet at court.", True, HINT_COLOR), (x0, y))

    def _wrap(self, text, width):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if self.small_font.size(test)[0] <= width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [text]

    def _draw_close(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

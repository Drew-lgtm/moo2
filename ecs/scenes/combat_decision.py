"""Combat Options screen — MOO2-style decision before each engagement.

Whenever the player has ships at a star where combat is about to
resolve, the strategic ``combat_tick`` queues the engagement here
instead of auto-resolving. This scene shows both sides and offers
three buttons:

- **Attack** — open the tactical hex scene and play the battle.
- **Auto-resolve** — let the strategic resolver decide. Results are
  added to ``pending_combat_reports`` so the combat-report scene
  shows them after all engagement decisions are made.
- **Retreat** — skip the engagement this turn. Stage 1: ships stay
  in place (no losses, no movement). Stage 2 will move the player's
  ships to a friendly star or apply a retreat penalty.

Multiple engagements queue: after one decision the next engagement
loads automatically until the queue is empty, then control returns
to the galaxy.
"""
from __future__ import annotations

import random
import pygame

from ecs.scene import Scene
from ecs.components import Empire
from ecs.palette import empire_color
from ecs.turn_log import log as turn_log, CAT_COMBAT


BG_COLOR = (8, 10, 22, 245)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (170, 180, 210)
PANEL_BG = (18, 22, 38)
PANEL_BORDER = (90, 100, 140)
SIDE_BG_PLAYER = (24, 38, 64)
SIDE_BG_ENEMY = (60, 28, 28)

BTN_ATTACK = (90, 60, 60)
BTN_ATTACK_HOVER = (130, 80, 80)
BTN_AUTO = (60, 80, 60)
BTN_AUTO_HOVER = (90, 120, 90)
BTN_RETREAT = (60, 60, 90)
BTN_RETREAT_HOVER = (90, 90, 130)
BTN_BORDER = (200, 210, 240)


class CombatDecisionScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 30, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 18, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 15, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 13, bold=True)

        self._buttons: list[tuple[str, pygame.Rect]] = []
        self._rng = random.Random()

    # --------------------------------------------------------------- lifecycle

    def on_enter(self):
        queue = getattr(self.game, "pending_engagements", None) or []
        if not queue:
            self.game.scenes.replace("galaxy")

    # --------------------------------------------------------------- helpers

    def _current(self):
        queue = getattr(self.game, "pending_engagements", None) or []
        return queue[0] if queue else None

    def _empire(self, eid):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.id == eid:
                return emp
        return None

    def _empire_color(self, eid):
        emp = self._empire(eid)
        return empire_color(emp.color) if emp else (200, 200, 200)

    def _empire_name(self, eid):
        emp = self._empire(eid)
        return emp.name if emp else f"Empire {eid}"

    def _side_summary(self, battle, empire_id) -> dict:
        """Roll up ship counts by class, total attack, total hull for
        one side of the engagement."""
        ships = battle.ships_for(empire_id)
        by_class: dict[str, int] = {}
        attack = hull = 0
        for s in ships:
            by_class[s.ship_class] = by_class.get(s.ship_class, 0) + 1
            attack += s.attack
            hull += s.hull
        return {
            "count": len(ships),
            "by_class": by_class,
            "attack": attack,
            "hull": hull,
        }

    # --------------------------------------------------------------- input

    def handle_event(self, event):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        for action, rect in self._buttons:
            if rect.collidepoint(event.pos):
                self._do(action)
                return

    def _do(self, action: str):
        battle = self._current()
        if battle is None:
            self.game.scenes.replace("galaxy")
            return
        if action == "attack":
            # Tactical scene reads the same queue. It pops on exit.
            self.game.scenes.replace("tactical")
            return
        if action == "auto":
            self._auto_resolve(battle)
            self._advance()
            return
        if action == "retreat":
            self._retreat(battle)
            self._advance()
            return

    def _auto_resolve(self, battle):
        """Strategic resolver: each side deals its summed attack across
        the other side's ships in random order, repeated until one side
        is wiped or both run out of damage to dish out. Mirrors the
        tactical Auto-resolve button so the maths match."""
        from ecs.tactical import DAMAGE_MIN_MULT, DAMAGE_MAX_MULT
        rng = self._rng
        live_by_eid = {eid: list(battle.ships_for(eid))
                       for eid in battle.empires_present()}
        attack_by_eid_before = {eid: sum(s.attack for s in ships)
                                for eid, ships in live_by_eid.items()}
        for _ in range(20):
            empires = [eid for eid, ships in live_by_eid.items() if ships]
            if len(empires) <= 1:
                break
            attack_by_eid = {eid: sum(s.attack for s in ships)
                             for eid, ships in live_by_eid.items()}
            for eid in empires:
                others = [other for other in empires if other != eid]
                if not others:
                    continue
                dmg = int(attack_by_eid[eid] * rng.uniform(DAMAGE_MIN_MULT, DAMAGE_MAX_MULT))
                while dmg > 0:
                    targets = [t for o in others for t in live_by_eid[o]]
                    if not targets:
                        break
                    target = rng.choice(targets)
                    bite = min(dmg, target.hull)
                    target.hull -= bite
                    dmg -= bite
                    if target.hull <= 0:
                        target.destroyed = True
                        live_by_eid[target.empire_id].remove(target)
        survivors = [eid for eid, ships in live_by_eid.items() if ships]
        battle.finished = True
        battle.winner_id = survivors[0] if len(survivors) == 1 else None

        # Apply destruction to the strategic layer.
        from ecs.combat import _destroy_ship
        from ecs.db import get_connection, delete_ship
        from ecs.components import Ship
        cm = self.game.component_mgr
        doomed = battle.destroyed_entity_ids()
        if doomed:
            with get_connection() as conn:
                for ship_entity in doomed:
                    ship = cm.get_component(ship_entity, Ship)
                    if ship is not None:
                        delete_ship(conn, ship.id)
                conn.commit()
            for ship_entity in doomed:
                _destroy_ship(self.game, ship_entity)

        # Add a combat-report row so the player sees the outcome after
        # all engagements are decided.
        sides = []
        for eid in battle.empires_present() | {s.empire_id for s in battle.ships}:
            # ships_before counts: from the original snapshot in
            # battle.ships (includes destroyed ones).
            by_class_total: dict[str, int] = {}
            total = 0
            for s in battle.ships:
                if s.empire_id != eid:
                    continue
                by_class_total[s.ship_class] = by_class_total.get(s.ship_class, 0) + 1
                total += 1
            lost = sum(1 for s in battle.ships
                       if s.empire_id == eid and s.destroyed)
            sides.append({
                "empire_id": eid,
                "attack": attack_by_eid_before.get(eid, 0),
                "defense": 0,
                "ships_before": by_class_total,
                "total_before": total,
                "lost": lost,
                "remaining": total - lost,
            })
        report = {
            "turn": battle.turn,
            "star_entity": battle.star_entity,
            "sides": sides,
            "losses_by_empire": {s["empire_id"]: s["lost"] for s in sides if s["lost"]},
            "attack_by_empire": {s["empire_id"]: s["attack"] for s in sides},
            "observed": False,
        }
        existing = getattr(self.game, "pending_combat_reports", None) or []
        self.game.pending_combat_reports = list(existing) + [report]
        # Brief turn log line.
        turn_log(
            self.game, CAT_COMBAT,
            f"Auto-resolved battle at {battle.star_name}",
        )

    def _retreat(self, battle):
        """Stage 1 retreat: skip the engagement this turn. Ships stay
        in place; the player has effectively decided not to fight now.
        A future stage will move the player's ships out of the system."""
        turn_log(
            self.game, CAT_COMBAT,
            f"Withdrew from engagement at {battle.star_name}",
        )

    def _advance(self):
        """Pop the current engagement and route — to the next decision
        if more remain, otherwise back to the galaxy."""
        queue = getattr(self.game, "pending_engagements", None) or []
        if queue:
            queue.pop(0)
        if queue:
            self.game.scenes.replace("combat_decision")  # re-enters with next
        else:
            self.game.pending_engagements = None
            self.game.scenes.replace("galaxy")

    # --------------------------------------------------------------- draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._buttons = []

        battle = self._current()
        if battle is None:
            screen.blit(
                self.body_font.render(
                    "No engagement to resolve.", True, HINT_COLOR,
                ),
                (sw // 2 - 80, sh // 2),
            )
            return

        # Title.
        title = f"Combat at {battle.star_name}"
        ts = self.title_font.render(title, True, TITLE_COLOR)
        screen.blit(ts, ts.get_rect(center=(sw // 2, 60)))
        sub = self.body_font.render(
            f"Turn {battle.turn}", True, HINT_COLOR,
        )
        screen.blit(sub, sub.get_rect(center=(sw // 2, 92)))

        # Queue indicator if there's more than one pending.
        queue = getattr(self.game, "pending_engagements", None) or []
        if len(queue) > 1:
            label = self.small_font.render(
                f"{len(queue) - 1} more engagement"
                f"{'s' if len(queue) - 1 != 1 else ''} after this",
                True, HINT_COLOR,
            )
            screen.blit(label, label.get_rect(center=(sw // 2, 112)))

        # Two-column sides layout: player on left, opposing empires
        # stacked on the right. Each column is a panel with composition.
        player_id = battle.player_id
        player_sum = self._side_summary(battle, player_id)
        other_ids = [eid for eid in battle.empires_present() if eid != player_id]

        col_w = 380
        col_h = 360
        col_y = 150
        player_x = sw // 2 - col_w - 40
        enemy_x = sw // 2 + 40
        self._draw_side_panel(
            screen, player_id, player_sum,
            (player_x, col_y, col_w, col_h),
            SIDE_BG_PLAYER, "Your forces",
        )
        # Other empires share the right column. If only one, fill the
        # whole panel; otherwise split.
        if len(other_ids) == 1:
            other_id = other_ids[0]
            self._draw_side_panel(
                screen, other_id,
                self._side_summary(battle, other_id),
                (enemy_x, col_y, col_w, col_h),
                SIDE_BG_ENEMY,
                f"{self._empire_name(other_id)}",
            )
        else:
            sub_h = (col_h - 12) // max(1, len(other_ids))
            yy = col_y
            for other_id in other_ids:
                self._draw_side_panel(
                    screen, other_id,
                    self._side_summary(battle, other_id),
                    (enemy_x, yy, col_w, sub_h),
                    SIDE_BG_ENEMY,
                    f"{self._empire_name(other_id)}",
                )
                yy += sub_h + 12

        # Buttons centred near the bottom.
        btn_y = 560
        btn_w = 240
        btn_h = 56
        gap = 30
        total_w = btn_w * 3 + gap * 2
        bx = sw // 2 - total_w // 2
        for action, label, fill, hover in (
            ("attack",  "Attack",  BTN_ATTACK,  BTN_ATTACK_HOVER),
            ("auto",    "Auto",    BTN_AUTO,    BTN_AUTO_HOVER),
            ("retreat", "Retreat", BTN_RETREAT, BTN_RETREAT_HOVER),
        ):
            rect = pygame.Rect(bx, btn_y, btn_w, btn_h)
            self._buttons.append((action, rect))
            hovered = rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, hover if hovered else fill, rect)
            pygame.draw.rect(screen, BTN_BORDER, rect, 2)
            ls = self.header_font.render(label, True, TEXT_COLOR)
            screen.blit(ls, ls.get_rect(center=rect.center))
            bx += btn_w + gap

        # Hint line.
        hint = self.small_font.render(
            "Attack: open tactical hex.   "
            "Auto: let the strategic resolver decide.   "
            "Retreat: skip this engagement.",
            True, HINT_COLOR,
        )
        screen.blit(hint, hint.get_rect(center=(sw // 2, btn_y + btn_h + 22)))

    def _draw_side_panel(self, screen, empire_id, summary, rect_tuple,
                         bg_color, title_override):
        x, y, w, h = rect_tuple
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(screen, bg_color, rect)
        pygame.draw.rect(screen, PANEL_BORDER, rect, 2)

        # Empire colour strip.
        color = self._empire_color(empire_id)
        pygame.draw.rect(screen, color, (x + 8, y + 8, 10, h - 16))

        # Title (already says "Your forces" or "<Empire name>").
        ts = self.header_font.render(title_override, True, TITLE_COLOR)
        screen.blit(ts, (x + 28, y + 10))

        # Race line for opposing empires (drops the redundant "Your
        # forces" race label).
        emp = self._empire(empire_id)
        if emp is not None and title_override != "Your forces":
            rs = self.body_font.render(emp.race_type, True, HINT_COLOR)
            screen.blit(rs, (x + 28, y + 34))

        # Composition.
        yy = y + 70
        screen.blit(
            self.body_font.render(
                f"Total: {summary['count']} ship"
                f"{'s' if summary['count'] != 1 else ''}",
                True, TEXT_COLOR,
            ),
            (x + 28, yy),
        )
        yy += 22
        for cls, n in sorted(summary["by_class"].items()):
            line = f"  {n} × {cls.replace('_', ' ').title()}"
            screen.blit(self.body_font.render(line, True, TEXT_COLOR),
                         (x + 28, yy))
            yy += 20
        yy += 8
        screen.blit(
            self.body_font.render(
                f"Combined attack: {summary['attack']}",
                True, TEXT_COLOR,
            ),
            (x + 28, yy),
        )
        yy += 20
        screen.blit(
            self.body_font.render(
                f"Combined hull:   {summary['hull']}",
                True, TEXT_COLOR,
            ),
            (x + 28, yy),
        )

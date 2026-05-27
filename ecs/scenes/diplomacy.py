"""Diplomacy screen.

Left column: every other empire as a selectable row (color, name, race,
attitude level, war flag). Right column: the selected empire's standing
plus action buttons — propose treaties, declare war, sue for peace,
cancel treaties (5-turn notice), gift BC, demand tribute.

Player actions resolve immediately against the AI's attitude
(diplomacy.would_accept_*). A one-line result banner reports the
outcome. Esc / Close returns to the galaxy view.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire, TechState
from ecs.palette import empire_color
from ecs.diplomacy import (
    TREATIES, TREATY_NAMES, NON_AGGRESSION, TRADE, RESEARCH, ALLIANCE,
    DEFENSIVE_PACT, OPEN_BORDERS, attitude_level,
    would_accept_treaty, would_accept_peace, empire_strength,
    would_accept_tech_trade,
)
from ecs.techs import TECHS
from ecs.db import get_connection, update_empire_economy, insert_empire_tech


BG_COLOR = (10, 12, 24, 235)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
ROW_BG = (24, 28, 42)
ROW_SEL = (50, 56, 84)
BTN_BG = (50, 56, 84)
BTN_BORDER = (150, 160, 200)
WAR_COLOR = (240, 120, 120)

GIFT_AMOUNT = 50
TRIBUTE_AMOUNT = 50

# Attitude level → display color.
LEVEL_COLOR = {
    "Hostile":  (240, 110, 110),
    "Wary":     (235, 170, 110),
    "Neutral":  (220, 220, 220),
    "Cordial":  (170, 220, 160),
    "Friendly": (130, 220, 140),
}


class DiplomacyScene(Scene):
    ROW_H = 48
    LEFT_W_FRAC = 0.42

    # Treaties the player can propose, in display order.
    PROPOSABLE = [NON_AGGRESSION, TRADE, RESEARCH, OPEN_BORDERS, DEFENSIVE_PACT, ALLIANCE]

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 15, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 13, bold=True)

        self.selected_empire_id: int | None = None
        self.banner: str = ""
        self.banner_color = HINT_COLOR

        self._close_rect = pygame.Rect(0, 0, 0, 0)
        self._row_hits: list[tuple[int, pygame.Rect]] = []
        self._action_hits: list[tuple[str, str, pygame.Rect]] = []  # (action, arg, rect)

    # ------------------------------------------------------------------ lifecycle

    def on_enter(self):
        sw = self.game.screen_width
        self._close_rect = pygame.Rect(sw - 100, 16, 80, 32)
        self.banner = ""
        # Default-select the first other empire.
        others = self._other_empires()
        if others and self.selected_empire_id not in [e.id for e in others]:
            self.selected_empire_id = others[0].id

    # ------------------------------------------------------------------ helpers

    def _player(self):
        return self.game.player_empire()

    def _other_empires(self) -> list:
        player = self._player()
        pid = player.id if player else None
        return [e for _eid, e in self.game.component_mgr.get_all(Empire) if e.id != pid]

    def _empire_by_id(self, eid):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.id == eid:
                return emp
        return None

    def _all_ids(self) -> list[int]:
        return [e.id for _eid, e in self.game.component_mgr.get_all(Empire)]

    def _turn(self) -> int:
        g = self.game.galaxy
        return g.turn if g else 0

    def _set_banner(self, text, ok=True):
        self.banner = text
        self.banner_color = (150, 220, 150) if ok else (230, 150, 150)

    # ------------------------------------------------------------------ actions

    def _do_action(self, action: str, arg: str):
        diplo = self.game.diplomacy
        player = self._player()
        if diplo is None or player is None or self.selected_empire_id is None:
            return
        target = self.selected_empire_id
        turn = self._turn()
        all_ids = self._all_ids()
        tname = self._empire_by_id(target)
        tlabel = tname.name if tname else f"Empire {target}"

        if action == "propose":
            if would_accept_treaty(diplo, target, player.id, arg):
                diplo.add_treaty(player.id, target, arg)
                self._set_banner(f"{tlabel} accepted the {TREATY_NAMES[arg]}.", True)
            else:
                diplo.adjust_attitude(player.id, target, -2)  # pestering annoys
                self._set_banner(f"{tlabel} rejected the {TREATY_NAMES[arg]}.", False)
        elif action == "cancel":
            diplo.cancel_treaty(player.id, target, arg, turn)
            self._set_banner(
                f"{TREATY_NAMES[arg]} with {tlabel} will end in 5 turns.", True)
        elif action == "war":
            diplo.declare_war(player.id, target, turn, all_ids)
            self._set_banner(f"You declared WAR on {tlabel}.", False)
        elif action == "peace":
            if would_accept_peace(diplo, target, player.id):
                diplo.make_peace(player.id, target, turn)
                self._set_banner(f"{tlabel} agreed to peace.", True)
            else:
                self._set_banner(f"{tlabel} refuses to make peace.", False)
        elif action == "gift":
            if player.bc >= GIFT_AMOUNT:
                player.bc -= GIFT_AMOUNT
                tgt = self._empire_by_id(target)
                if tgt is not None:
                    tgt.bc += GIFT_AMOUNT
                diplo.adjust_attitude(player.id, target, 8)
                self._persist_bc(player, tgt)
                self._set_banner(f"Gifted {GIFT_AMOUNT} BC to {tlabel}. (+attitude)", True)
            else:
                self._set_banner("Not enough BC to gift.", False)
        elif action == "techtrade":
            self._do_tech_trade(player, target, tlabel)
        elif action == "demand":
            # The AI pays if it's notably weaker AND not too hostile;
            # otherwise it refuses and resents the demand.
            cm = self.game.component_mgr
            mine = empire_strength(cm, player.id)
            theirs = empire_strength(cm, target)
            tgt = self._empire_by_id(target)
            if theirs < mine * 0.7 and diplo.attitude(player.id, target) > -50 and tgt and tgt.bc >= TRIBUTE_AMOUNT:
                tgt.bc -= TRIBUTE_AMOUNT
                player.bc += TRIBUTE_AMOUNT
                diplo.adjust_attitude(player.id, target, -10)  # they resent it
                self._persist_bc(player, tgt)
                self._set_banner(f"{tlabel} paid {TRIBUTE_AMOUNT} BC tribute. (-attitude)", True)
            else:
                diplo.adjust_attitude(player.id, target, -8)
                self._set_banner(f"{tlabel} refused your demand.", False)

        diplo.save()

    def _tech_state(self, empire_id):
        for _e, t in self.game.component_mgr.get_all(TechState):
            if t.empire_id == empire_id:
                return t
        return None

    def _do_tech_trade(self, player, target, tlabel):
        """Auto-matched fair swap: each side offers its highest-cost
        tech the other lacks. The AI accepts based on attitude +
        fairness (would_accept_tech_trade)."""
        diplo = self.game.diplomacy
        p_tech = self._tech_state(player.id)
        t_tech = self._tech_state(target)
        if p_tech is None or t_tech is None:
            self._set_banner("No tech to trade.", False)
            return
        p_set, t_set = set(p_tech.unlocked), set(t_tech.unlocked)

        def _best(offerer_set, lacker_set):
            cands = [tid for tid in offerer_set if tid not in lacker_set and tid in TECHS]
            if not cands:
                return None
            return max(cands, key=lambda tid: TECHS[tid]["cost"])

        give = _best(p_set, t_set)   # player gives this to target
        get = _best(t_set, p_set)    # player gets this from target
        if give is None or get is None:
            self._set_banner(f"No mutually useful techs to trade with {tlabel}.", False)
            return

        give_cost = TECHS[give]["cost"]
        get_cost = TECHS[get]["cost"]
        if would_accept_tech_trade(diplo, target, player.id, give_cost, get_cost):
            p_tech.unlocked.append(get)
            t_tech.unlocked.append(give)
            with get_connection() as conn:
                insert_empire_tech(conn, player.id, get)
                insert_empire_tech(conn, target, give)
                conn.commit()
            diplo.adjust_attitude(player.id, target, 5)
            self._set_banner(
                f"Traded {TECHS[give]['name']} for {TECHS[get]['name']} with {tlabel}.", True)
        else:
            self._set_banner(
                f"{tlabel} won't trade {TECHS[get]['name']} for {TECHS[give]['name']}.", False)

    def _persist_bc(self, *empires):
        with get_connection() as conn:
            for emp in empires:
                if emp is not None:
                    update_empire_economy(conn, emp.id, emp.bc, emp.research_points)
            conn.commit()

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
        for eid, rect in self._row_hits:
            if rect.collidepoint(event.pos):
                self.selected_empire_id = eid
                self.banner = ""
                return
        for action, arg, rect in self._action_hits:
            if rect.collidepoint(event.pos):
                self._do_action(action, arg)
                return

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))

        screen.blit(self.title_font.render("Diplomacy", True, TITLE_COLOR), (24, 16))

        diplo = self.game.diplomacy
        player = self._player()
        if diplo is None or player is None:
            screen.blit(self.header_font.render("No diplomacy state.", True, HINT_COLOR), (24, 60))
            self._draw_close(screen)
            return

        bc_label = self.body_font.render(f"Treasury: {player.bc} BC", True, TEXT_COLOR)
        screen.blit(bc_label, (sw - 320, 22))

        self._draw_empire_list(screen)
        self._draw_detail(screen)
        self._draw_close(screen)

        if self.banner:
            surf = self.body_font.render(self.banner, True, self.banner_color)
            screen.blit(surf, (24, sh - surf.get_height() - 14))

    def _draw_empire_list(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        diplo = self.game.diplomacy
        player = self._player()
        x, y = 24, 60
        w = int(sw * self.LEFT_W_FRAC) - 36
        self._row_hits = []
        for emp in self._other_empires():
            rect = pygame.Rect(x, y, w, self.ROW_H)
            selected = emp.id == self.selected_empire_id
            pygame.draw.rect(screen, ROW_SEL if selected else ROW_BG, rect)
            pygame.draw.rect(screen, BTN_BORDER if selected else (70, 78, 110), rect, 1)
            # Color bar + name.
            pygame.draw.rect(screen, empire_color(emp.color), pygame.Rect(rect.x + 6, rect.y + 8, 8, rect.height - 16))
            screen.blit(self.body_font.render(emp.name, True, TEXT_COLOR), (rect.x + 22, rect.y + 6))
            # Attitude / war state.
            if diplo.at_war(player.id, emp.id):
                state = self.small_font.render("AT WAR", True, WAR_COLOR)
            else:
                lvl = attitude_level(diplo.attitude(player.id, emp.id))
                state = self.small_font.render(
                    f"{lvl} ({diplo.attitude(player.id, emp.id):+d})", True,
                    LEVEL_COLOR.get(lvl, TEXT_COLOR),
                )
            screen.blit(state, (rect.x + 22, rect.y + 26))
            # Treaty count on the right.
            tcount = len(diplo.treaties(player.id, emp.id))
            if tcount:
                tlab = self.small_font.render(f"{tcount} treaty", True, (150, 200, 240))
                screen.blit(tlab, tlab.get_rect(topright=(rect.right - 8, rect.y + 6)))
            self._row_hits.append((emp.id, rect))
            y += self.ROW_H + 6

    def _draw_detail(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        diplo = self.game.diplomacy
        player = self._player()
        self._action_hits = []
        if self.selected_empire_id is None:
            return
        emp = self._empire_by_id(self.selected_empire_id)
        if emp is None:
            return

        x = int(sw * self.LEFT_W_FRAC) + 12
        y = 60
        panel_w = sw - x - 24
        pygame.draw.rect(screen, (16, 18, 30), pygame.Rect(x, y, panel_w, sh - y - 60))
        pygame.draw.rect(screen, BTN_BORDER, pygame.Rect(x, y, panel_w, sh - y - 60), 1)

        ix = x + 14
        iy = y + 12
        # Header: name + race + attitude.
        screen.blit(self.header_font.render(f"{emp.name}  ({emp.race_type})", True, TITLE_COLOR), (ix, iy))
        iy += 26
        at_war = diplo.at_war(player.id, emp.id)
        if at_war:
            screen.blit(self.body_font.render("Status: AT WAR", True, WAR_COLOR), (ix, iy))
        else:
            lvl = attitude_level(diplo.attitude(player.id, emp.id))
            screen.blit(self.body_font.render(
                f"Attitude: {lvl} ({diplo.attitude(player.id, emp.id):+d})", True,
                LEVEL_COLOR.get(lvl, TEXT_COLOR)), (ix, iy))
        iy += 24

        # Active treaties.
        treaties = diplo.treaties(player.id, emp.id)
        if treaties:
            screen.blit(self.small_font.render(
                "Treaties: " + ", ".join(TREATY_NAMES[t] for t in sorted(treaties)),
                True, (150, 200, 240)), (ix, iy))
        else:
            screen.blit(self.small_font.render("Treaties: none", True, HINT_COLOR), (ix, iy))
        iy += 28

        # --- Action buttons -------------------------------------------
        btn_h = 30
        col_w = (panel_w - 28 - 10) // 2

        def button(label, action, arg, col, row, color=BTN_BG):
            bx = ix + col * (col_w + 10)
            by = iy + row * (btn_h + 8)
            rect = pygame.Rect(bx, by, col_w, btn_h)
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, BTN_BORDER, rect, 1)
            screen.blit(self.small_font.render(label, True, TEXT_COLOR),
                        self.small_font.render(label, True, TEXT_COLOR).get_rect(center=rect.center))
            self._action_hits.append((action, arg, rect))

        row = 0
        if at_war:
            button("Sue for Peace", "peace", "", 0, row)
            button(f"Gift {GIFT_AMOUNT} BC", "gift", "", 1, row)
            row += 1
        else:
            # Propose each treaty we don't already have.
            col = 0
            for treaty in self.PROPOSABLE:
                if treaty in treaties:
                    continue
                button(f"Propose {TREATY_NAMES[treaty]}", "propose", treaty, col, row)
                col += 1
                if col == 2:
                    col = 0
                    row += 1
            if col == 1:
                row += 1
            # Cancel existing treaties.
            for treaty in sorted(treaties):
                button(f"Cancel {TREATY_NAMES[treaty]}", "cancel", treaty, 0, row, color=(70, 50, 50))
                row += 1
            # Transactions + war.
            button(f"Gift {GIFT_AMOUNT} BC", "gift", "", 0, row)
            button(f"Demand Tribute", "demand", "", 1, row)
            row += 1
            button("Tech Exchange", "techtrade", "", 0, row)
            button("Declare War", "war", "", 1, row, color=(110, 40, 40))
            row += 1

    def _draw_close(self, screen):
        pygame.draw.rect(screen, (150, 0, 0), self._close_rect)
        pygame.draw.rect(screen, (240, 240, 240), self._close_rect, 1)
        label = self.body_font.render("Close", True, (240, 240, 240))
        screen.blit(label, label.get_rect(center=self._close_rect.center))

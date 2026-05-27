"""Galactic Council screen.

Shown automatically when the council convenes (every COUNCIL_INTERVAL
turns). Two phases:

- **Vote** — the player picks which empire to back (any living empire)
  or abstains. Skipped when one empire already dominates (>=2/3 of the
  galaxy population) since the outcome is a foregone conclusion.
- **Result** — the vote tally and outcome:
    - Player elected  → Victory; button returns to the main menu.
    - An AI elected   → Accept (defeat → main menu) or Defy (war with the
      emperor + supporters, resume the game).
    - No winner       → Continue back to the galaxy.

Reads ``game.pending_council`` (the session dict from council.convene)
and clears it on exit so it only shows once per session.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire
from ecs.palette import empire_color
from ecs.council import VICTORY_FRACTION, finalize, defy_emperor


BG_COLOR = (8, 10, 22, 245)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
WIN_COLOR = (140, 230, 150)
LOSE_COLOR = (240, 130, 130)
BTN_BG = (50, 56, 84)
BTN_BORDER = (160, 170, 210)


class CouncilScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 34, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 22, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 14, bold=True)
        self.result: dict | None = None
        self.phase: str = "result"   # "vote" | "result"
        self._buttons: list[tuple[str, object, pygame.Rect]] = []

    def on_enter(self):
        self.result = getattr(self.game, "pending_council", None)
        r = self.result
        # Decide phase: a real ballot only happens when there's a vote to
        # cast (>=2 candidates, no dominance auto-win, a player to vote).
        if (r and r.get("candidates") and r.get("auto_winner") is None
                and r.get("player_id") is not None and not r.get("finalized")):
            self.phase = "vote"
        else:
            # No meaningful vote — resolve immediately (dominance, no
            # player, or too few empires) so the result screen has data.
            if r and not r.get("finalized"):
                finalize(r, None)
            self.phase = "result"

    def on_exit(self):
        self.game.pending_council = None

    # ------------------------------------------------------------------ helpers

    def _empire(self, eid):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.id == eid:
                return emp
        return None

    def _name(self, eid):
        emp = self._empire(eid)
        return emp.name if emp else f"Empire {eid}"

    def _color(self, eid):
        emp = self._empire(eid)
        return empire_color(emp.color) if emp else (200, 200, 200)

    def _player_id(self):
        p = self.game.player_empire()
        return p.id if p else None

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for action, payload, rect in self._buttons:
                if rect.collidepoint(event.pos):
                    self._do(action, payload)
                    return
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.phase == "vote":
                self._cast_vote(None)  # Esc abstains
            else:
                self.game.scenes.replace("galaxy")

    def _cast_vote(self, choice):
        finalize(self.result or {}, choice)
        self.phase = "result"

    def _do(self, action: str, payload):
        if action == "vote":
            self._cast_vote(payload)
        elif action == "continue":
            self.game.scenes.replace("galaxy")
        elif action == "defy":
            defy_emperor(self.game, self.result or {})
            self.game.scenes.replace("galaxy")
        elif action in ("victory", "defeat"):
            winner_id = (self.result or {}).get("winner")
            self.game.pending_endgame = {
                "result": "victory" if action == "victory" else "defeat",
                "mode": "Diplomatic",
                "winner_id": winner_id,
            }
            self.game.scenes.replace("game_over")

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._buttons = []

        cx = sw // 2
        title = self.title_font.render("Galactic Council", True, TITLE_COLOR)
        screen.blit(title, title.get_rect(center=(cx, 50)))

        result = self.result
        if not result or not result.get("candidates"):
            msg = self.body_font.render(
                "Too few empires remain to convene a council.", True, HINT_COLOR)
            screen.blit(msg, msg.get_rect(center=(cx, 160)))
            self._add_button(screen, "Continue", "continue", None, cx, 240)
            return

        if self.phase == "vote":
            self._draw_vote(screen, cx)
        else:
            self._draw_result(screen, cx)

    # -- voting phase ---------------------------------------------------

    def _draw_vote(self, screen, cx):
        result = self.result
        pops = result.get("pops", {})
        total = max(1, result.get("total", 0))

        prompt = self.header_font.render(
            "Cast your vote for Galactic Emperor:", True, TEXT_COLOR)
        screen.blit(prompt, (cx - 300, 100))

        y = 140
        row_h = 44
        for cand in result["candidates"]:
            share = pops.get(cand, 0) / total
            is_self = cand == result.get("player_id")
            label = f"{self._name(cand)}  ({pops.get(cand, 0)} pop · {share*100:.0f}%)"
            if is_self:
                label += "   — yourself"
            rect = pygame.Rect(cx - 300, y, 600, row_h - 8)
            pygame.draw.rect(screen, BTN_BG, rect)
            pygame.draw.rect(screen, self._color(cand), rect, 2)
            # color swatch
            pygame.draw.rect(screen, self._color(cand),
                             pygame.Rect(rect.x + 6, rect.y + 6, 18, rect.height - 12))
            surf = self.body_font.render(label, True, TEXT_COLOR)
            screen.blit(surf, (rect.x + 34, rect.y + (rect.height - surf.get_height()) // 2))
            self._buttons.append(("vote", cand, rect))
            y += row_h

        # Abstain option.
        y += 6
        self._add_button(screen, "Abstain", "vote", None, cx, y, w=200)
        hint = self.small_font.render(
            f"A candidate needs {int(VICTORY_FRACTION*100)}% of the total vote to be elected.",
            True, HINT_COLOR)
        screen.blit(hint, (cx - 300, y + 56))

    # -- result phase ---------------------------------------------------

    def _draw_result(self, screen, cx):
        result = self.result
        total = max(1, result.get("total", 0))
        votes = result.get("votes", {})

        if result.get("auto_winner") is not None:
            note = self.small_font.render(
                "One empire commands an overwhelming majority — no vote was needed.",
                True, HINT_COLOR)
            screen.blit(note, (cx - 300, 96))

        # Show candidates that received votes, highest first (cap to 6).
        ranked = sorted(result.get("candidates", []),
                        key=lambda c: votes.get(c, 0), reverse=True)
        ranked = [c for c in ranked if votes.get(c, 0) > 0][:6]

        y = 120
        for cand in ranked:
            v = votes.get(cand, 0)
            pct = v / total
            label = self.header_font.render(
                f"{self._name(cand)} — {v} votes ({pct*100:.0f}%)", True, TEXT_COLOR)
            screen.blit(label, (cx - 300, y))
            y += 26
            bar_bg = pygame.Rect(cx - 300, y, 600, 22)
            pygame.draw.rect(screen, (30, 34, 50), bar_bg)
            pygame.draw.rect(screen, self._color(cand),
                             pygame.Rect(cx - 300, y, int(600 * pct), 22))
            pygame.draw.rect(screen, BTN_BORDER, bar_bg, 1)
            y += 34

        screen.blit(self.small_font.render(
            f"A candidate needs {int(VICTORY_FRACTION*100)}% of the total vote to be elected Emperor.",
            True, HINT_COLOR), (cx - 300, y))
        y += 40

        winner = result.get("winner")
        player_id = self._player_id()

        if winner is None:
            screen.blit(self.header_font.render(
                "No Emperor was elected this session.", True, TEXT_COLOR), (cx - 300, y))
            self._add_button(screen, "Continue", "continue", None, cx, y + 50)
        elif winner == player_id:
            screen.blit(self.header_font.render(
                "You have been elected Galactic Emperor!", True, WIN_COLOR), (cx - 300, y))
            screen.blit(self.body_font.render(
                "Diplomatic Victory.", True, WIN_COLOR), (cx - 300, y + 30))
            self._add_button(screen, "Glorious!", "victory", None, cx, y + 70)
        else:
            screen.blit(self.header_font.render(
                f"{self._name(winner)} has been elected Galactic Emperor.", True, LOSE_COLOR),
                (cx - 300, y))
            screen.blit(self.body_font.render(
                "Accept their rule, or defy the council and fight on?", True, TEXT_COLOR),
                (cx - 300, y + 30))
            self._add_button(screen, "Accept Defeat", "defeat", None, cx - 110, y + 80)
            self._add_button(screen, "Defy!", "defy", None, cx + 110, y + 80)

    def _add_button(self, screen, label, action, payload, cx, cy, w=190, h=40):
        rect = pygame.Rect(cx - w // 2, cy, w, h)
        pygame.draw.rect(screen, BTN_BG, rect)
        pygame.draw.rect(screen, BTN_BORDER, rect, 1)
        surf = self.body_font.render(label, True, TEXT_COLOR)
        screen.blit(surf, surf.get_rect(center=rect.center))
        self._buttons.append((action, payload, rect))

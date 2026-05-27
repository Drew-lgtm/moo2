"""Save / Load slot browser.

A single scene that runs in two modes (``game.save_screen_mode``):

- "load": pick an occupied slot to load it (plus an Autosave row).
- "save": pick any slot to write the current game there.

Each row shows what's in the slot — empire, race, turn, colony and ship
counts, and the save timestamp — so you can tell saves apart at a
glance. ``game.save_screen_return`` names the scene to go back to
(main menu or pause).
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.save_manager import (
    NUM_SLOTS, slot_info, save_to_slot, load_from_slot,
)


BG_COLOR = (10, 12, 24, 245)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
EMPTY_COLOR = (120, 124, 140)
ROW_BG = (24, 28, 42)
ROW_HOVER = (44, 50, 76)
ROW_EMPTY = (18, 20, 30)
BTN_BG = (50, 56, 84)
BTN_BORDER = (160, 170, 210)


class SaveSlotScene(Scene):
    ROW_H = 64

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 28, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 18, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 14, bold=True)

        self.mode = "load"
        self.return_scene = "main_menu"
        self.banner = ""
        # (slot_number, info_or_None, rect)
        self._rows: list[tuple] = []
        self._back_rect = pygame.Rect(0, 0, 0, 0)

    def on_enter(self):
        self.mode = getattr(self.game, "save_screen_mode", "load")
        self.return_scene = getattr(self.game, "save_screen_return", "main_menu")
        self.banner = ""

    # ------------------------------------------------------------------ data

    def _slots(self):
        """List of (slot_number, info). In load mode, append Autosave."""
        rows = [(i, slot_info(i)) for i in range(1, NUM_SLOTS + 1)]
        if self.mode == "load":
            rows.append(("auto", slot_info("auto")))
        return rows

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.scenes.replace(self.return_scene)
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if self._back_rect.collidepoint(event.pos):
            self.game.scenes.replace(self.return_scene)
            return
        for slot_number, info, rect in self._rows:
            if not rect.collidepoint(event.pos):
                continue
            if self.mode == "save":
                # Autosave isn't a manual save target; numbered slots only.
                save_to_slot(slot_number)
                self.banner = f"Saved to slot {slot_number}."
            else:
                if info is None or info.get("corrupt"):
                    self.banner = "That slot is empty or unreadable."
                    return
                if load_from_slot(slot_number):
                    self.game.load_game()
                    self.game.scenes.replace("galaxy")
            return

    # ------------------------------------------------------------------ draw

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._rows = []

        title = "Save Game" if self.mode == "save" else "Load Game"
        screen.blit(self.title_font.render(title, True, TITLE_COLOR), (40, 24))
        hint = ("Click a slot to save the current game."
                if self.mode == "save"
                else "Click an occupied slot to load it.")
        screen.blit(self.small_font.render(hint, True, HINT_COLOR), (40, 60))

        x, y = 40, 96
        w = min(720, sw - 80)
        mouse = pygame.mouse.get_pos()
        for slot_number, info in self._slots():
            rect = pygame.Rect(x, y, w, self.ROW_H)
            occupied = info is not None
            clickable = self.mode == "save" or occupied
            hovered = clickable and rect.collidepoint(mouse)
            bg = ROW_HOVER if hovered else (ROW_BG if occupied else ROW_EMPTY)
            pygame.draw.rect(screen, bg, rect)
            pygame.draw.rect(screen, (70, 78, 110) if clickable else (50, 54, 70), rect, 1)

            slot_label = "Autosave" if slot_number == "auto" else f"Slot {slot_number}"
            screen.blit(self.header_font.render(slot_label, True, TITLE_COLOR), (rect.x + 14, rect.y + 8))

            if not occupied:
                screen.blit(self.body_font.render("— Empty —", True, EMPTY_COLOR), (rect.x + 14, rect.y + 34))
            elif info.get("corrupt"):
                screen.blit(self.body_font.render("(unreadable save)", True, (220, 130, 130)), (rect.x + 14, rect.y + 34))
            else:
                line1 = f"{info['empire']}  ·  {info['race']}"
                screen.blit(self.body_font.render(line1, True, TEXT_COLOR), (rect.x + 130, rect.y + 8))
                line2 = (f"Turn {info['turn']}   ·   {info['colonies']} colonies"
                         f"   ·   {info.get('ships', 0)} ships")
                screen.blit(self.small_font.render(line2, True, (200, 210, 230)), (rect.x + 130, rect.y + 34))
                stamp = self.small_font.render(info["saved_at"], True, HINT_COLOR)
                screen.blit(stamp, stamp.get_rect(topright=(rect.right - 14, rect.y + 10)))
                if self.mode == "save":
                    ow = self.small_font.render("click to overwrite", True, (220, 180, 120))
                    screen.blit(ow, ow.get_rect(topright=(rect.right - 14, rect.y + 34)))

            self._rows.append((slot_number, info, rect))
            y += self.ROW_H + 8

        # Back button.
        self._back_rect = pygame.Rect(40, sh - 64, 160, 40)
        pygame.draw.rect(screen, BTN_BG, self._back_rect)
        pygame.draw.rect(screen, BTN_BORDER, self._back_rect, 1)
        back = self.body_font.render("Back", True, TEXT_COLOR)
        screen.blit(back, back.get_rect(center=self._back_rect.center))

        if self.banner:
            b = self.body_font.render(self.banner, True, (150, 220, 150))
            screen.blit(b, (220, sh - 56))

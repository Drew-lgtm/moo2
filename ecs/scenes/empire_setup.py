"""Pre-game empire customization screen.

Reached from the main menu's "New Game" entry. Lets the player pick an
empire name, color, and race. Hitting Start passes an EmpirePreset to
Game.start_new_game(), which forwards it to _assign_empires so the
player's choices land on the first generated empire and AI empires
get the remaining colors / random races.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.empire_preset import EmpirePreset
from ecs.palette import EMPIRE_COLOR_RGB, empire_color
from ecs.difficulty import DIFFICULTIES, DEFAULT_DIFFICULTY
from assets.loader import load_image, find_race_portrait, list_race_names


TITLE_COLOR = (255, 230, 120)
LABEL_COLOR = (220, 220, 220)
TEXT_COLOR = (240, 240, 240)
FIELD_BG = (40, 40, 60)
FIELD_BORDER = (180, 180, 200)
BUTTON_BG = (60, 60, 90)
BUTTON_BORDER = (180, 180, 220)
SELECTED_RING = (255, 230, 120)


class EmpireSetupScene(Scene):
    PORTRAIT_SIZE = (64, 64)
    SWATCH_SIZE = (48, 48)
    RACE_COLS = 6
    NAME_MAX = 24

    NUM_EMPIRES_MIN = 2
    NUM_EMPIRES_MAX = 8
    NUM_EMPIRES_DEFAULT = 4
    PICKER_BTN = (32, 32)
    DIFFICULTY_BTN_SIZE = (110, 32)
    DIFFICULTY_BTN_GAP = 8

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 28, bold=True)
        self.label_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 14)
        self.button_font = pygame.font.SysFont("Arial", 18, bold=True)

        self.colors: list[str] = list(EMPIRE_COLOR_RGB.keys())
        self.races: list[str] = list_race_names()

        self.name: str = "My Empire"
        self.selected_color: str = self.colors[0]
        self.selected_race: str = "Humans" if "Humans" in self.races else self.races[0]
        self.num_empires: int = self.NUM_EMPIRES_DEFAULT
        self.difficulty: str = DEFAULT_DIFFICULTY

        self._color_rects: list[tuple[str, pygame.Rect]] = []
        self._race_rects: list[tuple[str, pygame.Rect, pygame.Surface | None]] = []
        self._name_rect = pygame.Rect(0, 0, 0, 0)
        self._start_rect = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, 0, 0)
        self._minus_rect = pygame.Rect(0, 0, 0, 0)
        self._plus_rect = pygame.Rect(0, 0, 0, 0)
        self._count_text_pos = (0, 0)
        self._count_box_rect = pygame.Rect(0, 0, 0, 0)
        self._name_label_pos = (0, 0)
        self._color_label_pos = (0, 0)
        self._race_label_pos = (0, 0)
        self._empires_label_pos = (0, 0)
        self._difficulty_label_pos = (0, 0)
        self._difficulty_rects: list[tuple[str, pygame.Rect]] = []

        self._caret_timer = 0.0
        self._caret_visible = True

    def on_enter(self):
        self._compute_layout()
        for race in self.races:
            path = find_race_portrait(race)
            if path:
                load_image(path, size=self.PORTRAIT_SIZE)
        # Hold-to-repeat for typing names.
        pygame.key.set_repeat(400, 50)

    def on_exit(self):
        pygame.key.set_repeat(0)

    def _compute_layout(self):
        sw, sh = self.game.screen_width, self.game.screen_height
        x = 40
        y = 64
        self._name_label_pos = (x, y)
        y += 24
        self._name_rect = pygame.Rect(x, y, 360, 32)
        y += 56

        self._color_label_pos = (x, y)
        y += 24
        self._color_rects.clear()
        cx = x
        for color_name in self.colors:
            rect = pygame.Rect(cx, y, *self.SWATCH_SIZE)
            self._color_rects.append((color_name, rect))
            cx += self.SWATCH_SIZE[0] + 12
        y += self.SWATCH_SIZE[1] + 24

        # Empire count picker: [-] [count] [+]
        self._empires_label_pos = (x, y)
        y += 24
        btn_w, btn_h = self.PICKER_BTN
        gap = 8
        count_w = 56
        self._minus_rect = pygame.Rect(x, y, btn_w, btn_h)
        self._count_box_rect = pygame.Rect(x + btn_w + gap, y, count_w, btn_h)
        self._plus_rect = pygame.Rect(x + btn_w + gap + count_w + gap, y, btn_w, btn_h)
        self._count_text_pos = self._count_box_rect
        y += btn_h + 20

        # Difficulty picker: row of 4 toggle buttons.
        self._difficulty_label_pos = (x, y)
        y += 24
        diff_w, diff_h = self.DIFFICULTY_BTN_SIZE
        self._difficulty_rects = []
        cx = x
        for diff in DIFFICULTIES:
            self._difficulty_rects.append((diff, pygame.Rect(cx, y, diff_w, diff_h)))
            cx += diff_w + self.DIFFICULTY_BTN_GAP
        y += diff_h + 20

        self._race_label_pos = (x, y)
        y += 24
        self._race_rects.clear()
        cell_w = self.PORTRAIT_SIZE[0] + 16
        cell_h = self.PORTRAIT_SIZE[1] + 24
        for i, race in enumerate(self.races):
            col, row = i % self.RACE_COLS, i // self.RACE_COLS
            rx = x + col * cell_w
            ry = y + row * cell_h
            path = find_race_portrait(race)
            surface = load_image(path, size=self.PORTRAIT_SIZE) if path else None
            self._race_rects.append((race, pygame.Rect(rx, ry, *self.PORTRAIT_SIZE), surface))

        btn_w, btn_h = 140, 44
        margin = 40
        self._start_rect = pygame.Rect(sw - margin - btn_w, sh - margin - btn_h, btn_w, btn_h)
        self._back_rect = pygame.Rect(margin, sh - margin - btn_h, btn_w, btn_h)

    def update(self, dt):
        self._caret_timer += dt
        if self._caret_timer >= 0.5:
            self._caret_timer = 0.0
            self._caret_visible = not self._caret_visible

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._back()
                return
            if event.key == pygame.K_RETURN:
                self._start()
                return
            if event.key == pygame.K_BACKSPACE:
                self.name = self.name[:-1]
                return
            if event.unicode and event.unicode.isprintable() and len(self.name) < self.NAME_MAX:
                self.name += event.unicode
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if self._start_rect.collidepoint(pos):
                self._start()
                return
            if self._back_rect.collidepoint(pos):
                self._back()
                return
            if self._minus_rect.collidepoint(pos):
                self.num_empires = max(self.NUM_EMPIRES_MIN, self.num_empires - 1)
                return
            if self._plus_rect.collidepoint(pos):
                self.num_empires = min(self.NUM_EMPIRES_MAX, self.num_empires + 1)
                return
            for diff, rect in self._difficulty_rects:
                if rect.collidepoint(pos):
                    self.difficulty = diff
                    return
            for color_name, rect in self._color_rects:
                if rect.collidepoint(pos):
                    self.selected_color = color_name
                    return
            for race_name, rect, _surface in self._race_rects:
                if rect.collidepoint(pos):
                    self.selected_race = race_name
                    return

    def _start(self):
        preset = EmpirePreset(
            name=self.name.strip() or "Empire",
            color=self.selected_color,
            race=self.selected_race,
        )
        self.game.start_new_game(
            player_empire=preset,
            num_empires=self.num_empires,
            difficulty=self.difficulty,
        )
        self.game.scenes.replace("galaxy")

    def _back(self):
        self.game.scenes.replace("main_menu")

    def draw(self, screen):
        screen.blit(self.title_font.render("Customize Empire", True, TITLE_COLOR), (40, 16))

        self._draw_name_field(screen)
        self._draw_color_row(screen)
        self._draw_empire_count(screen)
        self._draw_difficulty_row(screen)
        self._draw_race_grid(screen)
        self._draw_button(screen, self._back_rect, "Back")
        self._draw_button(screen, self._start_rect, "Start")

    def _draw_difficulty_row(self, screen):
        screen.blit(self.label_font.render("Difficulty", True, LABEL_COLOR), self._difficulty_label_pos)
        for diff, rect in self._difficulty_rects:
            selected = diff == self.difficulty
            bg = BUTTON_BG
            border = SELECTED_RING if selected else BUTTON_BORDER
            pygame.draw.rect(screen, bg, rect)
            pygame.draw.rect(screen, border, rect, width=3 if selected else 1)
            label = self.body_font.render(diff.capitalize(), True, TEXT_COLOR)
            screen.blit(label, label.get_rect(center=rect.center))

    def _draw_name_field(self, screen):
        screen.blit(self.label_font.render("Empire Name", True, LABEL_COLOR), self._name_label_pos)
        pygame.draw.rect(screen, FIELD_BG, self._name_rect)
        pygame.draw.rect(screen, FIELD_BORDER, self._name_rect, width=1)
        name_surf = self.body_font.render(self.name, True, TEXT_COLOR)
        text_y = self._name_rect.y + (self._name_rect.height - name_surf.get_height()) // 2
        screen.blit(name_surf, (self._name_rect.x + 8, text_y))
        if self._caret_visible:
            caret_x = self._name_rect.x + 8 + name_surf.get_width() + 1
            pygame.draw.line(
                screen, TEXT_COLOR,
                (caret_x, self._name_rect.y + 6),
                (caret_x, self._name_rect.bottom - 6),
                2,
            )

    def _draw_empire_count(self, screen):
        screen.blit(self.label_font.render("Number of Empires", True, LABEL_COLOR), self._empires_label_pos)

        # Minus button (disabled style if at min).
        minus_active = self.num_empires > self.NUM_EMPIRES_MIN
        self._draw_picker_button(screen, self._minus_rect, "−", active=minus_active)

        # Count box.
        pygame.draw.rect(screen, FIELD_BG, self._count_box_rect)
        pygame.draw.rect(screen, FIELD_BORDER, self._count_box_rect, width=1)
        count_surf = self.button_font.render(str(self.num_empires), True, TEXT_COLOR)
        screen.blit(count_surf, count_surf.get_rect(center=self._count_box_rect.center))

        # Plus button.
        plus_active = self.num_empires < self.NUM_EMPIRES_MAX
        self._draw_picker_button(screen, self._plus_rect, "+", active=plus_active)

    def _draw_picker_button(self, screen, rect, glyph, active):
        bg = BUTTON_BG if active else (40, 40, 50)
        border = BUTTON_BORDER if active else (90, 90, 110)
        fg = TEXT_COLOR if active else (120, 120, 140)
        pygame.draw.rect(screen, bg, rect)
        pygame.draw.rect(screen, border, rect, width=1)
        label = self.button_font.render(glyph, True, fg)
        screen.blit(label, label.get_rect(center=rect.center))

    def _draw_color_row(self, screen):
        screen.blit(self.label_font.render("Color", True, LABEL_COLOR), self._color_label_pos)
        for color_name, rect in self._color_rects:
            pygame.draw.rect(screen, empire_color(color_name), rect)
            if color_name == self.selected_color:
                pygame.draw.rect(screen, SELECTED_RING, rect, width=3)

    def _draw_race_grid(self, screen):
        screen.blit(self.label_font.render("Race", True, LABEL_COLOR), self._race_label_pos)
        for race_name, rect, surface in self._race_rects:
            if surface is not None:
                screen.blit(surface, rect)
            else:
                pygame.draw.rect(screen, FIELD_BG, rect)
            if race_name == self.selected_race:
                pygame.draw.rect(screen, SELECTED_RING, rect.inflate(6, 6), width=3)
            label = self.body_font.render(race_name, True, LABEL_COLOR)
            screen.blit(label, (rect.x + (rect.width - label.get_width()) // 2, rect.bottom + 4))

    def _draw_button(self, screen, rect, text):
        pygame.draw.rect(screen, BUTTON_BG, rect)
        pygame.draw.rect(screen, BUTTON_BORDER, rect, width=1)
        label = self.button_font.render(text, True, TEXT_COLOR)
        screen.blit(label, label.get_rect(center=rect.center))

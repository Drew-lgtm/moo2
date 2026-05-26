"""Pre-game empire customization screen.

Reached from the main menu's "New Game" entry. Lets the player pick an
empire name, color, race (preset or Custom point-buy), and difficulty.
Hitting Start passes an EmpirePreset to Game.start_new_game(), which
forwards it to _assign_empires so the player's choices land on the
first generated empire and AI empires get the remaining colors /
random races.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.empire_preset import EmpirePreset
from ecs.palette import EMPIRE_COLOR_RGB, empire_color
from ecs.difficulty import DIFFICULTIES, DEFAULT_DIFFICULTY
from ecs.galaxy_age import AGES, DEFAULT_AGE
from ecs.races import (
    RACES, RACE_ORDER, TRAITS, TRAIT_ORDER,
    CUSTOM_RACE_NAME, CUSTOM_POINTS_BUDGET,
    trait_cost_total,
)
from assets.loader import load_image, find_race_portrait


TITLE_COLOR = (255, 230, 120)
LABEL_COLOR = (220, 220, 220)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (180, 180, 180)
FIELD_BG = (40, 40, 60)
FIELD_BORDER = (180, 180, 200)
BUTTON_BG = (60, 60, 90)
BUTTON_BORDER = (180, 180, 220)
SELECTED_RING = (255, 230, 120)
POS_COST_COLOR = (240, 200, 120)
NEG_COST_COLOR = (140, 220, 140)
OVER_BUDGET_COLOR = (240, 100, 100)


class EmpireSetupScene(Scene):
    PORTRAIT_SIZE = (52, 52)
    SWATCH_SIZE = (40, 40)
    RACE_COLS = 6
    NAME_MAX = 24

    NUM_EMPIRES_MIN = 2
    NUM_EMPIRES_MAX = 8
    NUM_EMPIRES_DEFAULT = 4
    PICKER_BTN = (28, 28)
    DIFFICULTY_BTN_SIZE = (100, 28)
    DIFFICULTY_BTN_GAP = 8
    AGE_BTN_SIZE = (100, 28)
    AGE_BTN_GAP = 8

    # Right-side trait picker panel.
    TRAIT_PANEL_X = 560
    TRAIT_PANEL_WIDTH = 600
    TRAIT_ROW_HEIGHT = 26
    TRAIT_BTN = (22, 22)
    TRAIT_MAX_STACK = 3  # each trait can be picked up to 3 times

    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 28, bold=True)
        self.label_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 14, bold=True)
        self.button_font = pygame.font.SysFont("Arial", 18, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 12, bold=True)

        self.colors: list[str] = list(EMPIRE_COLOR_RGB.keys())
        # Curated catalog + a Custom slot at the end.
        self.races: list[str] = list(RACE_ORDER) + [CUSTOM_RACE_NAME]

        self.name: str = "My Empire"
        self.selected_color: str = self.colors[0]
        self.selected_race: str = "Humans"
        self.num_empires: int = self.NUM_EMPIRES_DEFAULT
        self.difficulty: str = DEFAULT_DIFFICULTY
        self.galaxy_age: str = DEFAULT_AGE
        # Per-trait pick counts for the Custom race builder.
        self.custom_picks: dict[str, int] = {k: 0 for k in TRAIT_ORDER}

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
        self._age_label_pos = (0, 0)
        self._age_rects: list[tuple[str, pygame.Rect]] = []
        # Trait picker layout.
        self._trait_rows: list[tuple[str, pygame.Rect, pygame.Rect, pygame.Rect]] = []
        self._trait_panel_rect = pygame.Rect(0, 0, 0, 0)
        self._budget_label_pos = (0, 0)
        self._reset_traits_rect = pygame.Rect(0, 0, 0, 0)

        self._caret_timer = 0.0
        self._caret_visible = True

    def on_enter(self):
        self._compute_layout()
        for race in RACE_ORDER:
            path = find_race_portrait(race)
            if path:
                load_image(path, size=self.PORTRAIT_SIZE)
        # Hold-to-repeat for typing names.
        pygame.key.set_repeat(400, 50)

    def on_exit(self):
        pygame.key.set_repeat(0)

    def _compute_layout(self):
        """Pack everything into the top half of the screen so Start/Back
        stay visible even on shorter Windows desktops with title-bar +
        taskbar eating into the visible area."""
        sw, sh = self.game.screen_width, self.game.screen_height
        x = 40
        y = 56

        # Name field.
        self._name_label_pos = (x, y)
        y += 20
        self._name_rect = pygame.Rect(x, y, 360, 28)
        y += 28 + 16

        # Color row.
        self._color_label_pos = (x, y)
        y += 20
        self._color_rects.clear()
        cx = x
        for color_name in self.colors:
            rect = pygame.Rect(cx, y, *self.SWATCH_SIZE)
            self._color_rects.append((color_name, rect))
            cx += self.SWATCH_SIZE[0] + 10
        y += self.SWATCH_SIZE[1] + 16

        # Empire count picker: [-] N [+]
        self._empires_label_pos = (x, y)
        y += 20
        btn_w, btn_h = self.PICKER_BTN
        gap = 6
        count_w = 48
        self._minus_rect = pygame.Rect(x, y, btn_w, btn_h)
        self._count_box_rect = pygame.Rect(x + btn_w + gap, y, count_w, btn_h)
        self._plus_rect = pygame.Rect(x + btn_w + gap + count_w + gap, y, btn_w, btn_h)
        self._count_text_pos = self._count_box_rect
        y += btn_h + 14

        # Difficulty picker row.
        self._difficulty_label_pos = (x, y)
        y += 20
        diff_w, diff_h = self.DIFFICULTY_BTN_SIZE
        self._difficulty_rects = []
        cx = x
        for diff in DIFFICULTIES:
            self._difficulty_rects.append((diff, pygame.Rect(cx, y, diff_w, diff_h)))
            cx += diff_w + self.DIFFICULTY_BTN_GAP
        y += diff_h + 16

        # Galaxy age picker row.
        self._age_label_pos = (x, y)
        y += 20
        age_w, age_h = self.AGE_BTN_SIZE
        self._age_rects = []
        cx = x
        for age in AGES:
            self._age_rects.append((age, pygame.Rect(cx, y, age_w, age_h)))
            cx += age_w + self.AGE_BTN_GAP
        y += age_h + 16

        # Race grid.
        self._race_label_pos = (x, y)
        y += 20
        self._race_rects.clear()
        cell_w = self.PORTRAIT_SIZE[0] + 14
        cell_h = self.PORTRAIT_SIZE[1] + 22
        for i, race in enumerate(self.races):
            col, row = i % self.RACE_COLS, i // self.RACE_COLS
            rx = x + col * cell_w
            ry = y + row * cell_h
            path = find_race_portrait(race)
            surface = load_image(path, size=self.PORTRAIT_SIZE) if path else None
            self._race_rects.append((race, pygame.Rect(rx, ry, *self.PORTRAIT_SIZE), surface))
        rows = max(1, (len(self.races) + self.RACE_COLS - 1) // self.RACE_COLS)
        race_bottom = y + rows * cell_h

        # Trait picker panel on the right side. Always laid out, only
        # interactive + rendered when "Custom" race is selected.
        panel_x = self.TRAIT_PANEL_X
        panel_y = 56
        panel_w = min(self.TRAIT_PANEL_WIDTH, sw - panel_x - 20)
        panel_h = sh - panel_y - 80
        self._trait_panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        self._budget_label_pos = (panel_x + 8, panel_y + 8)
        # Reset button anchored top-right of panel.
        reset_w, reset_h = 72, 22
        self._reset_traits_rect = pygame.Rect(
            panel_x + panel_w - reset_w - 8, panel_y + 8, reset_w, reset_h
        )

        # Trait rows.
        self._trait_rows = []
        row_y = panel_y + 40
        btn_w, btn_h = self.TRAIT_BTN
        for key in TRAIT_ORDER:
            row_rect = pygame.Rect(panel_x + 8, row_y, panel_w - 16, self.TRAIT_ROW_HEIGHT)
            # [-] on the right edge then count box then [+].
            plus_rect = pygame.Rect(
                row_rect.right - btn_w - 4,
                row_y + (self.TRAIT_ROW_HEIGHT - btn_h) // 2,
                btn_w, btn_h,
            )
            minus_rect = pygame.Rect(
                plus_rect.x - 32 - btn_w,
                row_y + (self.TRAIT_ROW_HEIGHT - btn_h) // 2,
                btn_w, btn_h,
            )
            self._trait_rows.append((key, row_rect, minus_rect, plus_rect))
            row_y += self.TRAIT_ROW_HEIGHT

        # Start / Back buttons live just below the race grid (not anchored
        # to screen bottom) so they're always visible.
        btn_w, btn_h = 140, 40
        buttons_y = race_bottom + 24
        # Don't push them past the bottom margin if somehow there's content.
        buttons_y = min(buttons_y, sh - btn_h - 20)
        self._start_rect = pygame.Rect(sw - 40 - btn_w, buttons_y, btn_w, btn_h)
        self._back_rect = pygame.Rect(40, buttons_y, btn_w, btn_h)

    def update(self, dt):
        self._caret_timer += dt
        if self._caret_timer >= 0.5:
            self._caret_timer = 0.0
            self._caret_visible = not self._caret_visible

    def _is_custom(self) -> bool:
        return self.selected_race == CUSTOM_RACE_NAME

    def _custom_traits_list(self) -> list[str]:
        out = []
        for key in TRAIT_ORDER:
            out.extend([key] * self.custom_picks.get(key, 0))
        return out

    def _budget_spent(self) -> int:
        return trait_cost_total(self._custom_traits_list())

    def _budget_remaining(self) -> int:
        return CUSTOM_POINTS_BUDGET - self._budget_spent()

    def _can_buy(self, key: str) -> bool:
        if self.custom_picks.get(key, 0) >= self.TRAIT_MAX_STACK:
            return False
        return self._budget_remaining() - TRAITS[key]["cost"] >= 0

    def _can_sell(self, key: str) -> bool:
        # A negative-cost trait gives points back when picked, so "selling"
        # it (decrementing) costs points and may not be affordable.
        if self.custom_picks.get(key, 0) <= 0:
            return False
        return self._budget_remaining() + TRAITS[key]["cost"] >= 0

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
            for age, rect in self._age_rects:
                if rect.collidepoint(pos):
                    self.galaxy_age = age
                    return
            for color_name, rect in self._color_rects:
                if rect.collidepoint(pos):
                    self.selected_color = color_name
                    return
            for race_name, rect, _surface in self._race_rects:
                if rect.collidepoint(pos):
                    self.selected_race = race_name
                    return
            # Trait picker (Custom only).
            if self._is_custom():
                if self._reset_traits_rect.collidepoint(pos):
                    self.custom_picks = {k: 0 for k in TRAIT_ORDER}
                    return
                for key, _row, minus_r, plus_r in self._trait_rows:
                    if plus_r.collidepoint(pos) and self._can_buy(key):
                        self.custom_picks[key] = self.custom_picks.get(key, 0) + 1
                        return
                    if minus_r.collidepoint(pos) and self._can_sell(key):
                        self.custom_picks[key] -= 1
                        return

    def _start(self):
        if self._is_custom():
            # Don't let the player ship an over-budget custom race.
            if self._budget_remaining() < 0:
                return
            custom = self._custom_traits_list()
        else:
            custom = []
        preset = EmpirePreset(
            name=self.name.strip() or "Empire",
            color=self.selected_color,
            race=self.selected_race,
            custom_traits=custom,
        )
        self.game.start_new_game(
            player_empire=preset,
            num_empires=self.num_empires,
            difficulty=self.difficulty,
            galaxy_age=self.galaxy_age,
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
        self._draw_age_row(screen)
        self._draw_race_grid(screen)
        self._draw_trait_panel(screen)
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

    def _draw_age_row(self, screen):
        # Header includes a tiny hint so the player knows what changes.
        screen.blit(
            self.label_font.render("Galaxy Age", True, LABEL_COLOR),
            self._age_label_pos,
        )
        hint = {
            "young": "(mineral-rich)",
            "average": "(balanced)",
            "old": "(farming-rich)",
        }.get(self.galaxy_age, "")
        if hint:
            hint_surf = self.small_font.render(hint, True, HINT_COLOR)
            screen.blit(
                hint_surf,
                (self._age_label_pos[0] + 110, self._age_label_pos[1] + 4),
            )
        for age, rect in self._age_rects:
            selected = age == self.galaxy_age
            bg = BUTTON_BG
            border = SELECTED_RING if selected else BUTTON_BORDER
            pygame.draw.rect(screen, bg, rect)
            pygame.draw.rect(screen, border, rect, width=3 if selected else 1)
            label = self.body_font.render(age.capitalize(), True, TEXT_COLOR)
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

    def _draw_button(self, screen, rect, text):
        pygame.draw.rect(screen, BUTTON_BG, rect)
        pygame.draw.rect(screen, BUTTON_BORDER, rect, width=1)
        label = self.button_font.render(text, True, TEXT_COLOR)
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
                # Custom (or any race without portrait): solid box with "?" glyph.
                pygame.draw.rect(screen, FIELD_BG, rect)
                pygame.draw.rect(screen, FIELD_BORDER, rect, width=1)
                glyph = self.title_font.render("?", True, LABEL_COLOR)
                screen.blit(glyph, glyph.get_rect(center=rect.center))
            if race_name == self.selected_race:
                pygame.draw.rect(screen, SELECTED_RING, rect.inflate(6, 6), width=3)
            label = self.body_font.render(race_name, True, LABEL_COLOR)
            screen.blit(label, (rect.x + (rect.width - label.get_width()) // 2, rect.bottom + 4))

    def _draw_trait_panel(self, screen):
        rect = self._trait_panel_rect
        # Background panel + border so it reads as a distinct region.
        pygame.draw.rect(screen, (20, 22, 36), rect)
        pygame.draw.rect(screen, FIELD_BORDER, rect, width=1)

        if self._is_custom():
            self._draw_trait_picker(screen)
        else:
            # Show the selected preset's bundled traits for reference.
            self._draw_preset_traits(screen)

    def _draw_preset_traits(self, screen):
        rect = self._trait_panel_rect
        race = RACES.get(self.selected_race)
        if race is None:
            return
        header = self.label_font.render(f"{race['name']} traits", True, LABEL_COLOR)
        screen.blit(header, (rect.x + 8, rect.y + 8))
        desc = self.small_font.render(race.get("description", ""), True, HINT_COLOR)
        screen.blit(desc, (rect.x + 8, rect.y + 30))

        # Count duplicates so "Industry +1" twice shows as "x2".
        counts: dict[str, int] = {}
        for t in race["traits"]:
            counts[t] = counts.get(t, 0) + 1

        y = rect.y + 56
        for key, count in counts.items():
            meta = TRAITS.get(key)
            if meta is None:
                continue
            stack = f" ×{count}" if count > 1 else ""
            line = self.body_font.render(f"• {meta['name']}{stack}", True, TEXT_COLOR)
            screen.blit(line, (rect.x + 12, y))
            y += 22

    def _draw_trait_picker(self, screen):
        rect = self._trait_panel_rect
        spent = self._budget_spent()
        remaining = self._budget_remaining()

        budget_color = OVER_BUDGET_COLOR if remaining < 0 else LABEL_COLOR
        budget = self.label_font.render(
            f"Custom Race — Points {spent} / {CUSTOM_POINTS_BUDGET}  "
            f"(remaining {remaining})",
            True, budget_color,
        )
        screen.blit(budget, self._budget_label_pos)

        # Reset button.
        pygame.draw.rect(screen, BUTTON_BG, self._reset_traits_rect)
        pygame.draw.rect(screen, BUTTON_BORDER, self._reset_traits_rect, width=1)
        reset_label = self.small_font.render("Reset", True, TEXT_COLOR)
        screen.blit(reset_label, reset_label.get_rect(center=self._reset_traits_rect.center))

        for key, row_rect, minus_r, plus_r in self._trait_rows:
            meta = TRAITS[key]
            count = self.custom_picks.get(key, 0)
            cost = meta["cost"]
            # Trait name on the left.
            name_color = TEXT_COLOR if count > 0 else LABEL_COLOR
            label = self.body_font.render(meta["name"], True, name_color)
            screen.blit(label, (row_rect.x + 4, row_rect.y + 5))

            # Cost in a coloured chip — positive costs in orange, negative
            # (refund) in green so it's obvious which traits give points back.
            cost_color = NEG_COST_COLOR if cost < 0 else POS_COST_COLOR
            cost_label = self.small_font.render(
                f"{cost:+d}" if cost != 0 else "0",
                True, cost_color,
            )
            screen.blit(cost_label, (row_rect.x + 280, row_rect.y + 7))

            # Current pick count.
            stack_label = self.body_font.render(
                f"×{count}" if count > 0 else "—",
                True, TEXT_COLOR if count > 0 else HINT_COLOR,
            )
            stack_rect = stack_label.get_rect(
                center=((minus_r.right + plus_r.x) // 2, row_rect.centery)
            )
            screen.blit(stack_label, stack_rect)

            # Minus / plus buttons.
            self._draw_picker_button(screen, minus_r, "−", active=self._can_sell(key))
            self._draw_picker_button(screen, plus_r, "+", active=self._can_buy(key))

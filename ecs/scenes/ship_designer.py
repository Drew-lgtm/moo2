"""Manual ship designer.

Reached from the Build screen ("Design Ships"). The player authors named
blueprints: pick a hull, then fit armor / shield / weapon (with a count
and a Normal / Heavy / Point-Defense mount) / specials within the hull's
space budget. Saved designs appear in the Build screen's Ships tab and,
when built, freeze that exact loadout onto the spawned ship.

Controls are all mouse: ◄ ► cycle a slot through the empire's unlocked
options (including "None"); − + adjust weapon count; the Mount button
cycles the mount; specials toggle on click. A live budget bar turns red
when the design is over budget, which disables Save.
"""
from __future__ import annotations

import pygame

from ecs.scene import Scene
from ecs.components import Empire, TechState
from ecs.ships import SHIPS, SHIP_ORDER
from ecs.techs import TECHS
from ecs.ship_design import (
    _equip_specs, MOUNTS, MOUNT_ORDER, design_space_used, hull_space_budget,
    stats_from_ship,
)


BG_COLOR = (10, 12, 24, 240)
TITLE_COLOR = (255, 230, 120)
TEXT_COLOR = (240, 240, 240)
HINT_COLOR = (175, 185, 210)
PANEL_BG = (20, 24, 40)
PANEL_BORDER = (90, 100, 140)
BTN_BG = (48, 54, 82)
BTN_HOVER = (72, 80, 116)
BTN_BORDER = (150, 160, 205)
GOOD = (150, 220, 160)
BAD = (240, 130, 130)
FIELD_BG = (28, 32, 48)

# Hulls the designer offers — military classes (civilians don't fit
# weapons, and their auto-loadout is fine).
DESIGNABLE = [c for c in SHIP_ORDER
              if SHIPS.get(c, {}).get("ship_class_kind") == "military"]


class ShipDesignerScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        self.title_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.header_font = pygame.font.SysFont("Arial", 17, bold=True)
        self.body_font = pygame.font.SysFont("Arial", 15, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 13, bold=True)

        # Editable working design.
        self._reset_working()
        self.name_text = ""
        self.name_focused = False
        self.banner = ""
        self.banner_color = HINT_COLOR
        self._hits: list[tuple[str, object, pygame.Rect]] = []

    def _reset_working(self):
        # Default to the first real warship (frigate), not the troop
        # transport that happens to sort first among military hulls.
        self.hull_idx = DESIGNABLE.index("frigate") if "frigate" in DESIGNABLE else 0
        self.armor_tech = None
        self.shield_tech = None
        self.weapon_tech = None
        self.weapon_count = 0
        self.weapon_mount = "normal"
        self.specials: list[str] = []

    # ------------------------------------------------------------------ lifecycle

    def on_enter(self):
        self.banner = ""
        pygame.key.set_repeat(400, 50)

    def on_exit(self):
        pygame.key.set_repeat(0)

    # ------------------------------------------------------------------ helpers

    def _player(self):
        for _e, emp in self.game.component_mgr.get_all(Empire):
            if emp.is_player:
                return emp
        return None

    def _unlocked(self) -> set[str]:
        p = self._player()
        if p is None:
            return set()
        for _e, ts in self.game.component_mgr.get_all(TechState):
            if ts.empire_id == p.id:
                return set(ts.unlocked)
        return set()

    def _ship_class(self) -> str:
        return DESIGNABLE[self.hull_idx % len(DESIGNABLE)]

    def _slot_options(self, slot: str) -> list[str | None]:
        """Unlocked options for a slot, prefixed with None ('—')."""
        specs = _equip_specs(self._unlocked(), slot)
        specs.sort(key=lambda s: s["equipment"].get("size", 0))
        return [None] + [s["id"] for s in specs]

    def _cycle_slot(self, slot: str, direction: int):
        opts = self._slot_options(slot)
        attr = {"armor": "armor_tech", "shield": "shield_tech",
                "weapon": "weapon_tech"}[slot]
        cur = getattr(self, attr)
        idx = opts.index(cur) if cur in opts else 0
        new = opts[(idx + direction) % len(opts)]
        setattr(self, attr, new)
        if slot == "weapon":
            # Picking a weapon defaults the count to 1; clearing zeroes it.
            self.weapon_count = 1 if new else 0

    def _as_design_view(self):
        """A duck-typed object stats_from_ship can read."""
        from types import SimpleNamespace
        return SimpleNamespace(
            ship_class=self._ship_class(), armor_tech=self.armor_tech,
            shield_tech=self.shield_tech, weapon_tech=self.weapon_tech,
            weapon_count=self.weapon_count, weapon_mount=self.weapon_mount,
            specials=list(self.specials),
        )

    def _space_used(self) -> int:
        return design_space_used(self.armor_tech, self.shield_tech,
                                 self.weapon_tech, self.weapon_count,
                                 self.weapon_mount, self.specials)

    def _space_total(self) -> int:
        return hull_space_budget(self._ship_class(), self.specials, self._unlocked())

    def _over_budget(self) -> bool:
        return self._space_used() > self._space_total()

    # ------------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.game.scenes.replace("build")
                return
            if self.name_focused:
                if event.key == pygame.K_BACKSPACE:
                    self.name_text = self.name_text[:-1]
                elif event.key == pygame.K_RETURN:
                    self.name_focused = False
                elif event.unicode and event.unicode.isprintable() and len(self.name_text) < 28:
                    self.name_text += event.unicode
                return
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        for action, payload, rect in self._hits:
            if rect.collidepoint(event.pos):
                self._do(action, payload)
                return
        # Click outside the name field unfocuses it.
        self.name_focused = False

    def _do(self, action, payload):
        if action == "close":
            self.game.scenes.replace("build")
        elif action == "hull":
            self.hull_idx = (self.hull_idx + payload) % len(DESIGNABLE)
            self._clamp_weapon_count()
        elif action in ("armor", "shield", "weapon"):
            self._cycle_slot(action, payload)
            self._clamp_weapon_count()
        elif action == "count":
            self.weapon_count = max(0, self.weapon_count + payload)
            if self.weapon_count == 0:
                self.weapon_tech = None
        elif action == "mount":
            i = MOUNT_ORDER.index(self.weapon_mount) if self.weapon_mount in MOUNT_ORDER else 0
            self.weapon_mount = MOUNT_ORDER[(i + 1) % len(MOUNT_ORDER)]
        elif action == "special":
            if payload in self.specials:
                self.specials.remove(payload)
            else:
                self.specials.append(payload)
        elif action == "name":
            self.name_focused = True
        elif action == "save":
            self._save()
        elif action == "delete":
            mgr = self.game.ship_designs
            if mgr is not None:
                self._purge_design_from_queues(payload)
                mgr.delete(payload)
                mgr.save()
        elif action == "load":
            self._load_design(payload)

    def _clamp_weapon_count(self):
        """Trim the weapon count until the design fits (best-effort)."""
        guard = 0
        while self.weapon_tech and self.weapon_count > 0 and self._over_budget() and guard < 100:
            self.weapon_count -= 1
            guard += 1

    def _save(self):
        mgr = self.game.ship_designs
        player = self._player()
        if mgr is None or player is None:
            return
        name = self.name_text.strip() or f"{self._ship_class().title()} design"
        if self._over_budget():
            self.banner, self.banner_color = "Over budget — trim equipment.", BAD
            return
        mgr.create(player.id, name, self._ship_class(),
                   armor_tech=self.armor_tech, shield_tech=self.shield_tech,
                   weapon_tech=self.weapon_tech, weapon_count=self.weapon_count,
                   weapon_mount=self.weapon_mount, specials=list(self.specials))
        mgr.save()
        self.banner, self.banner_color = f"Saved '{name}'.", GOOD

    def _purge_design_from_queues(self, design_id):
        """Remove a design's build orders from every planet before the
        design is deleted, so no colony is left pointing at a dead
        blueprint. (The economy tick also self-heals dead orders, but
        cleaning up here avoids wasting even one turn of industry.)"""
        from ecs.components import BuildState, Planet
        from ecs.designs import design_project_id
        from ecs.db import (
            get_connection, update_planet_build, save_planet_build_queue,
        )
        pid = design_project_id(design_id)
        cm = self.game.component_mgr
        with get_connection() as conn:
            for entity_id, bs in cm.get_all(BuildState):
                planet = cm.get_component(entity_id, Planet)
                if planet is None:
                    continue
                changed = False
                if pid in bs.queue:
                    bs.queue = [q for q in bs.queue if q != pid]
                    save_planet_build_queue(conn, planet.id, list(bs.queue))
                    changed = True
                if bs.current_project == pid:
                    bs.current_project = bs.queue.pop(0) if bs.queue else None
                    bs.progress = 0
                    update_planet_build(conn, planet.id,
                                        bs.current_project, bs.progress)
                    if changed:
                        save_planet_build_queue(conn, planet.id, list(bs.queue))
            conn.commit()

    def _load_design(self, design_id):
        mgr = self.game.ship_designs
        d = mgr.get(design_id) if mgr else None
        if d is None:
            return
        if d.ship_class in DESIGNABLE:
            self.hull_idx = DESIGNABLE.index(d.ship_class)
        self.armor_tech = d.armor_tech
        self.shield_tech = d.shield_tech
        self.weapon_tech = d.weapon_tech
        self.weapon_count = d.weapon_count
        self.weapon_mount = d.weapon_mount
        self.specials = list(d.specials)
        self.name_text = d.name

    # ------------------------------------------------------------------ draw

    def _label(self, tech_id) -> str:
        if tech_id is None:
            return "—"
        return TECHS.get(tech_id, {}).get("name", tech_id)

    def draw(self, screen):
        sw, sh = self.game.screen_width, self.game.screen_height
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill(BG_COLOR)
        screen.blit(overlay, (0, 0))
        self._hits = []

        screen.blit(self.title_font.render("Ship Designer", True, TITLE_COLOR), (24, 16))

        player = self._player()
        if player is None or self.game.ship_designs is None:
            screen.blit(self.header_font.render("No active game.", True, HINT_COLOR), (24, 60))
            self._btn(screen, "close", None, "Close", pygame.Rect(sw - 100, 16, 80, 32))
            return

        self._draw_editor(screen, 24, 60, int(sw * 0.60) - 40)
        self._draw_design_list(screen, int(sw * 0.60), 60, sw - int(sw * 0.60) - 24, sh - 120)

        self._btn(screen, "close", None, "Close", pygame.Rect(sw - 100, 16, 80, 32))
        if self.banner:
            screen.blit(self.body_font.render(self.banner, True, self.banner_color),
                        (24, sh - 34))

    def _btn(self, screen, action, payload, label, rect, enabled=True):
        hovered = rect.collidepoint(pygame.mouse.get_pos())
        fill = (BTN_HOVER if hovered else BTN_BG) if enabled else (34, 36, 48)
        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, BTN_BORDER if enabled else (70, 74, 92), rect, 1)
        color = TEXT_COLOR if enabled else (120, 120, 140)
        s = self.body_font.render(label, True, color)
        screen.blit(s, s.get_rect(center=rect.center))
        if enabled:
            self._hits.append((action, payload, rect))

    def _cycle_row(self, screen, y, label, value_text, action, x, w):
        """A ◄ [value] ► picker row. Returns the row's bottom y."""
        screen.blit(self.body_font.render(label, True, HINT_COLOR), (x, y + 4))
        left = pygame.Rect(x + 130, y, 28, 26)
        val = pygame.Rect(x + 162, y, w - 130 - 28 - 28 - 4, 26)
        right = pygame.Rect(val.right + 4, y, 28, 26)
        self._btn(screen, action, -1, "◄", left)
        pygame.draw.rect(screen, FIELD_BG, val)
        pygame.draw.rect(screen, PANEL_BORDER, val, 1)
        vs = self.body_font.render(value_text, True, TEXT_COLOR)
        screen.blit(vs, vs.get_rect(midleft=(val.x + 8, val.centery)))
        self._btn(screen, action, +1, "►", right)
        return y + 34

    def _draw_editor(self, screen, x, y, w):
        panel = pygame.Rect(x, y, w, self.game.screen_height - y - 60)
        pygame.draw.rect(screen, PANEL_BG, panel)
        pygame.draw.rect(screen, PANEL_BORDER, panel, 1)
        ix = x + 14
        iw = w - 28
        cy = y + 14

        cls = self._ship_class()
        cy = self._cycle_row(screen, cy, "Hull", f"{cls.title()}", "hull", ix, iw)
        cy = self._cycle_row(screen, cy, "Armor", self._label(self.armor_tech), "armor", ix, iw)
        cy = self._cycle_row(screen, cy, "Shield", self._label(self.shield_tech), "shield", ix, iw)
        cy = self._cycle_row(screen, cy, "Weapon", self._label(self.weapon_tech), "weapon", ix, iw)

        # Weapon count + mount row.
        screen.blit(self.body_font.render("Count", True, HINT_COLOR), (ix, cy + 4))
        self._btn(screen, "count", -1, "−", pygame.Rect(ix + 130, cy, 28, 26))
        cnt = self.body_font.render(str(self.weapon_count), True, TEXT_COLOR)
        screen.blit(cnt, cnt.get_rect(center=(ix + 162 + 20, cy + 13)))
        self._btn(screen, "count", +1, "+", pygame.Rect(ix + 202, cy, 28, 26))
        mount_name = MOUNTS.get(self.weapon_mount, MOUNTS["normal"])["name"]
        self._btn(screen, "mount", None, f"Mount: {mount_name}",
                  pygame.Rect(ix + 240, cy, iw - 240, 26))
        cy += 40

        # Specials as toggle chips.
        screen.blit(self.body_font.render("Specials", True, HINT_COLOR), (ix, cy))
        cy += 24
        specials = _equip_specs(self._unlocked(), "special")
        specials.sort(key=lambda s: s["equipment"].get("size", 0))
        if not specials:
            screen.blit(self.small_font.render("(none researched)", True, HINT_COLOR), (ix + 8, cy))
            cy += 22
        for sp in specials:
            on = sp["id"] in self.specials
            row = pygame.Rect(ix, cy, iw, 24)
            pygame.draw.rect(screen, (30, 40, 54) if on else FIELD_BG, row)
            pygame.draw.rect(screen, GOOD if on else PANEL_BORDER, row, 1)
            mark = "☑" if on else "☐"
            size = sp["equipment"].get("size", 1)
            screen.blit(self.small_font.render(
                f"{mark} {TECHS.get(sp['id'],{}).get('name', sp['id'])}  (size {size})",
                True, TEXT_COLOR), (row.x + 8, row.y + 4))
            self._hits.append(("special", sp["id"], row))
            cy += 28

        # Budget bar + stats.
        cy += 6
        used, total = self._space_used(), self._space_total()
        over = used > total
        bar = pygame.Rect(ix, cy, iw, 18)
        pygame.draw.rect(screen, (30, 34, 50), bar)
        frac = min(1.0, used / total) if total else 0
        fill_c = BAD if over else GOOD
        pygame.draw.rect(screen, fill_c, pygame.Rect(bar.x, bar.y, int(bar.width * frac), bar.height))
        pygame.draw.rect(screen, PANEL_BORDER, bar, 1)
        screen.blit(self.small_font.render(f"Space {used}/{total}", True, TEXT_COLOR),
                    (bar.x + 8, bar.y + 2))
        cy += 26

        st = stats_from_ship(self._as_design_view())
        base_hull = SHIPS.get(cls, {}).get("hull", 0)
        stat_line = (f"Attack {st['attack']}   Hull {base_hull + st['hull']}   "
                     f"Shield {st['shield_capacity']}   Def {st['defense']}")
        screen.blit(self.body_font.render(stat_line, True, TITLE_COLOR), (ix, cy))
        cy += 30

        # Name field + Save.
        name_rect = pygame.Rect(ix, cy, iw - 120, 30)
        pygame.draw.rect(screen, (40, 46, 70) if self.name_focused else FIELD_BG, name_rect)
        pygame.draw.rect(screen, TITLE_COLOR if self.name_focused else PANEL_BORDER, name_rect,
                         2 if self.name_focused else 1)
        nm = self.name_text or "Design name..."
        nc = TEXT_COLOR if self.name_text else HINT_COLOR
        screen.blit(self.body_font.render(nm, True, nc),
                    (name_rect.x + 8, name_rect.y + 6))
        self._hits.append(("name", None, name_rect))
        self._btn(screen, "save", None, "Save", pygame.Rect(name_rect.right + 8, cy, 104, 30),
                  enabled=not over)

    def _draw_design_list(self, screen, x, y, w, h):
        panel = pygame.Rect(x, y, w, h)
        pygame.draw.rect(screen, PANEL_BG, panel)
        pygame.draw.rect(screen, PANEL_BORDER, panel, 1)
        screen.blit(self.header_font.render("Saved Designs", True, TITLE_COLOR),
                    (x + 12, y + 10))
        player = self._player()
        mgr = self.game.ship_designs
        designs = mgr.for_empire(player.id) if (mgr and player) else []
        cy = y + 40
        if not designs:
            screen.blit(self.small_font.render("None yet — build one on the left.",
                                               True, HINT_COLOR), (x + 12, cy))
            return
        for d in designs:
            row = pygame.Rect(x + 10, cy, w - 20, 42)
            pygame.draw.rect(screen, (26, 30, 46), row)
            pygame.draw.rect(screen, PANEL_BORDER, row, 1)
            screen.blit(self.body_font.render(d.name[:24], True, TEXT_COLOR),
                        (row.x + 8, row.y + 4))
            screen.blit(self.small_font.render(
                f"{d.ship_class.title()} · atk {d.stats()['attack']}",
                True, HINT_COLOR), (row.x + 8, row.y + 22))
            # Edit (load) + Delete buttons.
            del_btn = pygame.Rect(row.right - 54, row.y + 8, 46, 26)
            self._btn(screen, "delete", d.id, "Del", del_btn)
            load_btn = pygame.Rect(del_btn.x - 54, row.y + 8, 46, 26)
            self._btn(screen, "load", d.id, "Edit", load_btn)
            cy += 48
            if cy > y + h - 48:
                break

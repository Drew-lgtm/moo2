"""In-game help overlay (F1).

A condensed, scrollable version of MANUAL.md — enough to explain the
core loop, the controls, and the systems whose effects aren't visible on
screen (morale, upkeep, missiles vs point-defense, veterancy, guardians,
victory paths). Opens over whatever screen you were on and returns
there, so it can be checked mid-decision without losing your place.

Keep the text here in sync with MANUAL.md when rules change.
"""
from __future__ import annotations

import pygame

from ecs.scenes.panels import PanelScene, TITLE_COLOR, TEXT_COLOR, HINT_COLOR
from ecs.ui_scale import s


SECTION_COLOR = (255, 230, 120)
KEY_COLOR = (150, 210, 255)

# (heading, [line, ...]). A line starting with "* " renders as a bullet;
# "KEY: rest" renders the key in a highlight colour.
HELP_SECTIONS: list[tuple[str, list[str]]] = [
    ("The turn", [
        "Each turn: set workers, queue builds, pick research, move fleets,",
        "then press End Turn. Everything resolves at once.",
        "T: end turn        Esc: back / pause",
    ]),
    ("Screens", [
        "G: galaxy map          C: colonies list",
        "P: planets list        R: research tree",
        "D: diplomacy           E: espionage",
        "L: leaders             I: info, government, techs",
        "Right-click almost anything for a tooltip.",
    ]),
    ("Economy", [
        "* Farmers make food. Food is empire-wide — a negative balance",
        "  halts growth and starves the colony with the worst local deficit.",
        "* Workers make industry: it builds what's queued, or becomes BC",
        "  if nothing is.",
        "* Scientists make research.",
        "* Trade Goods / Housing are permanent modes: turn all industry",
        "  into money, or into population growth.",
        "* Ships cost upkeep every turn. Scrap obsolete hulls (fleet",
        "  panel) for 25% back and to stop paying for them.",
    ]),
    ("Morale and government", [
        "Morale (colony screen) scales industry, research and trade from",
        "0.75x to 1.25x. Food is never affected.",
        "It comes from your government plus conquest status — a freshly",
        "conquered world is restive until it assimilates.",
        "* Dictatorship — neutral baseline.",
        "* Democracy (Governance) — +20% research, +10% BC, but",
        "  conquered worlds resent you.",
        "* Imperium (Galactic Unification) — higher morale everywhere.",
    ]),
    ("Research", [
        "Click a tech to research it; click another to queue it. The",
        "queue starts automatically when the current tech finishes.",
        "Click the tech you're researching to cancel it.",
        "Picking one tech in a tier LOCKS OUT its alternatives for good",
        "(spies can still steal them). Choose deliberately.",
    ]),
    ("Combat: beams, missiles, point-defense", [
        "* Beams always hit — reliable.",
        "* Missiles and carrier fighters hit harder per slot, but enemy",
        "  point-defense shoots them down before they land.",
        "* Point-defense comes from the PD mount and Anti-Missile",
        "  Rockets, and is pooled across your fleet each round — a few",
        "  escorts screen everyone.",
        "So: facing missiles, build PD. Facing no PD, bring missiles.",
    ]),
    ("Ships", [
        "Designs are frozen when built — new tech doesn't upgrade old",
        "hulls. Use Refit at a colony to bring parked ships up to date.",
        "Mounts: Normal / Heavy (2x damage, 2x space) / Point-Defense.",
        "Ships that survive battles rank up Green > Regular > Veteran >",
        "Elite > Ultra-Elite, gaining attack and hull. Protect veterans.",
    ]),
    ("Expanding, and what stops you", [
        "Colony Ship settles a planet; Outpost Ship claims an empty",
        "system. Terraforming upgrades a planet's biome permanently.",
        "* Space monsters guard the richest systems — you cannot settle",
        "  or outpost there until the guardian is dead. Killing it pays",
        "  a bounty and opens the system.",
        "* Fleets can't move beyond your fuel range.",
    ]),
    ("War", [
        "* Invasion — Troop Transports capture a colony.",
        "* Bombardment — warships in orbit kill population and buildings.",
        "* Blockade — just parking warships over an enemy colony cuts",
        "  its trade income. No shots required.",
        "* Warp Dissipator (tech) — enemy fleets can't flee a system your",
        "  warships hold.",
        "Antaran raiders strike the galaxy's largest colony from turn 40 on —",
        "not necessarily yours.",
    ]),
    ("Winning", [
        "* Conquest — be the last empire with colonies.",
        "* Diplomatic — win a Galactic Council vote (every 25 turns,",
        "  needs two-thirds).",
        "* Antaran — research and build the Dimensional Portal, mass a",
        "  fleet there, and destroy Antares. Hardest, and scores best.",
        "The AI can take the Antaran path too — if a rival builds a",
        "portal, you are on a clock.",
    ]),
]


class HelpScene(PanelScene):
    title = "Help  —  F1 to close"

    LINE_H = s(20)
    SECTION_GAP = s(14)

    def handle_event(self, event):
        # Esc and F1 both return to wherever the player opened help from,
        # instead of PanelScene's default hop to the galaxy view.
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,
                                                          pygame.K_F1):
            self.game.close_help()
            return
        super().handle_event(event)

    def draw_content(self, screen, rect, font) -> int:
        top = rect.y - self.scroll_offset
        y = top
        for heading, lines in HELP_SECTIONS:
            screen.blit(font.render(heading, True, SECTION_COLOR), (rect.x, y))
            y += self.LINE_H + 4
            for line in lines:
                text, color, indent = line, TEXT_COLOR, 0
                if line.startswith("* "):
                    text, indent = "• " + line[2:], 10
                elif line.startswith("  "):
                    indent = 20
                    text = line.strip()
                # "X: rest" — highlight a leading key or short label.
                if ":" in text and text.index(":") <= 22 and not text.startswith("•"):
                    key, _, rest = text.partition(":")
                    ks = font.render(key + ":", True, KEY_COLOR)
                    screen.blit(ks, (rect.x + indent, y))
                    screen.blit(font.render(rest, True, color),
                                (rect.x + indent + ks.get_width(), y))
                else:
                    screen.blit(font.render(text, True, color),
                                (rect.x + indent, y))
                y += self.LINE_H
            y += self.SECTION_GAP
        screen.blit(font.render("Full manual: MANUAL.md in the game folder",
                                True, HINT_COLOR), (rect.x, y))
        y += self.LINE_H
        return y - top

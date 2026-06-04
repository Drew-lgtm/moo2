"""Espionage: spies, sabotage, tech theft, counter-intelligence.

Each empire trains a pool of spies (paid for in BC). Every spy is either
defending the home empire (counter-intelligence, the default) or on an
offensive mission against a rival:

- **Steal Tech** — copies a random tech the target knows and you don't.
- **Sabotage**   — destroys a building on a random target colony, or
  drains the target's treasury when there's nothing to wreck.

Each turn ``espionage_tick`` resolves every offensive spy individually:

    attacker = BASE_SPY + spy_offense(tech) + roll
    defender = BASE_SECURITY + spy_defense(tech) + defenders + roll
    success  = attacker > defender

A failed spy may be **caught**. If identified, the target's attitude
toward the aggressor drops (a diplomatic incident). Tech shapes this:

- **Stealth Suit** (attacker) — a caught spy is rarely identified.
- **Mind Scan**   (defender)  — caught spies are *always* unmasked and
  internal security is higher, defeating stealth.

State hangs off ``game.espionage`` and persists via the ``spies`` and
``spy_missions`` tables.
"""
from __future__ import annotations

import random

from ecs.db import (
    get_connection, insert_empire_tech, update_empire_economy,
    delete_planet_building,
)
from ecs.components import (
    Empire, Owner, Population, BuildState, TechState,
)
from ecs.techs import (
    empire_spy_offense, empire_spy_defense, empire_has_stealth, empire_has_mind_scan,
)
from ecs.races import trait_count, traits_for_empire


MISSIONS = ["steal", "sabotage"]
MISSION_NAMES = {"steal": "Steal Tech", "sabotage": "Sabotage", "defense": "Defense"}

# Cost in BC to train one spy.
SPY_COST = 100

# Resolution tuning.
BASE_SPY_SKILL = 2
BASE_SECURITY = 2
CAUGHT_CHANCE = 0.40          # chance a failed spy is caught
MIND_SCAN_CAUGHT_BONUS = 0.35  # extra catch chance when defender has Mind Scan
INCIDENT_ATTITUDE_HIT = -15   # target's attitude toward an identified aggressor
SABOTAGE_BC_DRAIN = 40        # BC stolen when there's no building to wreck


class Espionage:
    def __init__(self):
        # empire_id -> trained spy count
        self.spies: dict[int, int] = {}
        # (attacker_id, target_id) -> {"steal": int, "sabotage": int}
        self.missions: dict[tuple[int, int], dict[str, int]] = {}
        # rolling log of notable events (player-facing)
        self.log: list[str] = []

    # -- queries --------------------------------------------------------

    def spy_count(self, empire_id: int) -> int:
        return self.spies.get(empire_id, 0)

    def _mission_slot(self, attacker: int, target: int) -> dict[str, int]:
        key = (attacker, target)
        if key not in self.missions:
            self.missions[key] = {"steal": 0, "sabotage": 0}
        return self.missions[key]

    def mission_count(self, attacker: int, target: int, mission: str) -> int:
        return self._mission_slot(attacker, target).get(mission, 0)

    def assigned_offensive(self, empire_id: int) -> int:
        total = 0
        for (atk, _tgt), slot in self.missions.items():
            if atk == empire_id:
                total += slot.get("steal", 0) + slot.get("sabotage", 0)
        return total

    def defense_count(self, empire_id: int) -> int:
        """Spies not on an offensive mission defend the home empire."""
        return max(0, self.spy_count(empire_id) - self.assigned_offensive(empire_id))

    def unassigned(self, empire_id: int) -> int:
        """Alias for defense_count — spies free to be reassigned."""
        return self.defense_count(empire_id)

    # -- mutations ------------------------------------------------------

    def train_spy(self, empire_id: int, n: int = 1):
        self.spies[empire_id] = self.spies.get(empire_id, 0) + n

    def adjust_mission(self, attacker: int, target: int, mission: str, delta: int):
        """Move ``delta`` spies onto/off a mission, clamped so total
        offensive spies never exceed the trained pool."""
        if mission not in MISSIONS or attacker == target:
            return
        slot = self._mission_slot(attacker, target)
        cur = slot.get(mission, 0)
        if delta > 0:
            delta = min(delta, self.defense_count(attacker))  # only free spies
        new = max(0, cur + delta)
        slot[mission] = new

    def lose_spy(self, attacker: int, target: int, mission: str):
        """A caught spy is removed from the pool and its mission slot."""
        slot = self._mission_slot(attacker, target)
        if slot.get(mission, 0) > 0:
            slot[mission] -= 1
        self.spies[attacker] = max(0, self.spies.get(attacker, 0) - 1)

    def _log(self, msg: str):
        self.log.append(msg)
        if len(self.log) > 60:
            self.log = self.log[-60:]

    # -- persistence ----------------------------------------------------

    def save(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM spies")
            conn.execute("DELETE FROM spy_missions")
            for eid, count in self.spies.items():
                if count > 0:
                    conn.execute(
                        "INSERT INTO spies (empire_id, count) VALUES (?, ?)",
                        (eid, count),
                    )
            for (atk, tgt), slot in self.missions.items():
                for mission, n in slot.items():
                    if n > 0:
                        conn.execute(
                            "INSERT INTO spy_missions (attacker, target, mission, count) "
                            "VALUES (?, ?, ?, ?)",
                            (atk, tgt, mission, n),
                        )
            conn.commit()

    def load(self):
        self.spies.clear()
        self.missions.clear()
        with get_connection() as conn:
            for row in conn.execute("SELECT * FROM spies"):
                self.spies[row["empire_id"]] = row["count"]
            for row in conn.execute("SELECT * FROM spy_missions"):
                slot = self._mission_slot(row["attacker"], row["target"])
                slot[row["mission"]] = row["count"]


# ---- per-turn resolution ----------------------------------------------

def _unlocked_by_empire(cm) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for _eid, tech in cm.get_all(TechState):
        out[tech.empire_id] = set(tech.unlocked)
    return out


def _tech_state_for(cm, empire_id: int) -> TechState | None:
    for _eid, tech in cm.get_all(TechState):
        if tech.empire_id == empire_id:
            return tech
    return None


def _empire_for(cm, empire_id: int) -> Empire | None:
    for _eid, emp in cm.get_all(Empire):
        if emp.id == empire_id:
            return emp
    return None


def _empire_colonies(cm, empire_id: int) -> list[int]:
    return [eid for eid, owner in cm.get_all(Owner) if owner.empire_id == empire_id]


def espionage_tick(game, new_turn: int):
    """Turn callback: resolve every offensive spy, then persist."""
    esp = getattr(game, "espionage", None)
    if esp is None:
        return
    cm = game.component_mgr
    diplo = getattr(game, "diplomacy", None)
    rng = random
    unlocked = _unlocked_by_empire(cm)
    player = game.player_empire()
    player_id = player.id if player else None

    def name(eid):
        emp = _empire_for(cm, eid)
        return emp.name if emp else f"Empire {eid}"

    # Snapshot the missions so lose_spy mutations during iteration are safe.
    work: list[tuple[int, int, str]] = []
    for (atk, tgt), slot in esp.missions.items():
        for mission in MISSIONS:
            work.extend([(atk, tgt, mission)] * slot.get(mission, 0))

    if not work:
        return

    with get_connection() as conn:
        for atk, tgt, mission in work:
            atk_set = unlocked.get(atk, set())
            tgt_set = unlocked.get(tgt, set())
            # Attacker race traits — Spymasters get a flat bonus per
            # pick (Darloks at +2 from two stacks).
            attacker_traits = traits_for_empire(cm, atk)
            atk_trait_bonus = trait_count(attacker_traits, "spymaster")
            atk_skill = (BASE_SPY_SKILL + empire_spy_offense(atk_set)
                         + atk_trait_bonus + rng.randint(0, 4))
            defenders = esp.defense_count(tgt)
            # Defender race traits — Hive Mind (+2 per stack), Mind
            # Link (+1 per stack, telepathic awareness), Spymaster
            # (+1 per stack).
            target_traits = traits_for_empire(cm, tgt)
            def_trait_bonus = (
                trait_count(target_traits, "hive_mind") * 2
                + trait_count(target_traits, "mind_link")
                + trait_count(target_traits, "spymaster")
            )
            tgt_security = (BASE_SECURITY + empire_spy_defense(tgt_set)
                            + defenders + def_trait_bonus + rng.randint(0, 4))

            if atk_skill > tgt_security:
                _resolve_success(game, conn, cm, esp, atk, tgt, mission,
                                 atk_set, tgt_set, name, player_id, rng)
            else:
                _resolve_failure(game, esp, diplo, atk, tgt, mission,
                                 atk_set, tgt_set, name, player_id, rng, new_turn)

        conn.commit()

    if diplo is not None:
        diplo.save()
    esp.save()


def _resolve_success(game, conn, cm, esp, atk, tgt, mission,
                     atk_set, tgt_set, name, player_id, rng):
    mine = (atk == player_id)
    theirs = (tgt == player_id)
    if mission == "steal":
        stealable = list(tgt_set - atk_set)
        if not stealable:
            return
        tech_id = rng.choice(stealable)
        atk_set.add(tech_id)
        ts = _tech_state_for(cm, atk)
        if ts is not None and tech_id not in ts.unlocked:
            ts.unlocked.append(tech_id)
        # If the attacker had locked this out earlier (chose differently
        # at the same tier), stealing reverses that.
        if ts is not None and tech_id in ts.locked_out:
            ts.locked_out.remove(tech_id)
            conn.execute(
                "DELETE FROM empire_locked_techs WHERE empire_id = ? AND tech_id = ?",
                (atk, tech_id),
            )
        insert_empire_tech(conn, atk, tech_id)
        from ecs.techs import TECHS
        tname = TECHS.get(tech_id, {}).get("name", tech_id)
        if mine:
            esp._log(f"Your spy stole {tname} from {name(tgt)}!")
        elif theirs:
            esp._log(f"{name(atk)} stole {tname} from you!")
        else:
            esp._log(f"{name(atk)} stole {tname} from {name(tgt)}.")
    else:  # sabotage
        building = _pick_building_to_wreck(cm, tgt, rng)
        if building is not None:
            entity_id, planet, proj_id = building
            bs = cm.get_component(entity_id, BuildState)
            if bs is not None and proj_id in bs.completed:
                bs.completed.remove(proj_id)
            delete_planet_building(conn, planet.id, proj_id)
            from ecs.projects import PROJECTS
            pname = PROJECTS.get(proj_id, {}).get("name", proj_id)
            if mine:
                esp._log(f"Your saboteur destroyed {pname} on a {name(tgt)} colony!")
            elif theirs:
                esp._log(f"Sabotage destroyed {pname} on one of your colonies!")
            else:
                esp._log(f"{name(atk)} sabotaged {pname} on a {name(tgt)} colony.")
        else:
            emp = _empire_for(cm, tgt)
            if emp is not None and emp.bc > 0:
                drain = min(SABOTAGE_BC_DRAIN, emp.bc)
                emp.bc -= drain
                update_empire_economy(conn, emp.id, emp.bc, emp.research_points)
                if mine:
                    esp._log(f"Your saboteur drained {drain} BC from {name(tgt)}!")
                elif theirs:
                    esp._log(f"Sabotage drained {drain} BC from your treasury!")


def _resolve_failure(game, esp, diplo, atk, tgt, mission,
                     atk_set, tgt_set, name, player_id, rng, turn):
    caught_chance = CAUGHT_CHANCE
    target_mind_scan = empire_has_mind_scan(tgt_set)
    if target_mind_scan:
        caught_chance += MIND_SCAN_CAUGHT_BONUS
    if rng.random() >= caught_chance:
        return  # mission failed but the spy slipped away

    # Caught. Identification depends on stealth vs mind scan.
    esp.lose_spy(atk, tgt, mission)
    identified = target_mind_scan or not empire_has_stealth(atk_set)

    mine = (atk == player_id)
    theirs = (tgt == player_id)
    if identified:
        if diplo is not None:
            diplo.adjust_attitude(tgt, atk, INCIDENT_ATTITUDE_HIT)
        if mine:
            esp._log(f"Your spy was caught and exposed by {name(tgt)}! Relations worsen.")
        elif theirs:
            esp._log(f"You caught and exposed a spy from {name(atk)}!")
        else:
            esp._log(f"{name(tgt)} caught a spy from {name(atk)}.")
    else:
        if mine:
            esp._log(f"Your spy was caught by {name(tgt)} but escaped unidentified.")
        elif theirs:
            esp._log(f"You caught a spy on your soil — but couldn't trace its master.")


def _pick_building_to_wreck(cm, target_id: int, rng):
    """A random (entity, Planet, project_id) for a destructible building
    on one of the target's colonies, or None if it has nothing built."""
    options: list[tuple[int, object, str]] = []
    for entity_id, owner in cm.get_all(Owner):
        if owner.empire_id != target_id:
            continue
        bs = cm.get_component(entity_id, BuildState)
        from ecs.components import Planet
        planet = cm.get_component(entity_id, Planet)
        if bs is None or planet is None:
            continue
        for proj_id in bs.completed:
            options.append((entity_id, planet, proj_id))
    if not options:
        return None
    return rng.choice(options)

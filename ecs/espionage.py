"""Espionage: spies, sabotage, tech theft, counter-intelligence.

Each empire trains a pool of spies (paid for in BC). Every spy is either
defending the home empire (counter-intelligence, the default) or on an
offensive mission against a rival:

- **Steal Tech**     — copies a random tech the target knows and you don't.
- **Sabotage**       — destroys a building on a random target colony, or
  drains the target's treasury when there's nothing to wreck.
- **Assassinate**    — kills one of the target's hired leaders. Their
  colony / ship bonus vanishes immediately.
- **Incite Revolt**  — destabilises a target colony: resets its
  assimilation progress to 0 and seeds a guerrilla insurgency.
- **Frame Empire**   — like Sabotage, but the diplomatic hit + log
  blame fall on a random third empire. Needs at least three alive.

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
    delete_planet_building, update_planet_conquest,
)
from ecs.components import (
    Empire, Owner, Population, BuildState, TechState, Planet,
)
from ecs.techs import (
    empire_spy_offense, empire_spy_defense, empire_has_stealth, empire_has_mind_scan,
)
from ecs.races import trait_count, traits_for_empire


MISSIONS = ["steal", "sabotage", "assassinate", "incite", "frame"]
MISSION_NAMES = {
    "steal":       "Steal Tech",
    "sabotage":    "Sabotage",
    "assassinate": "Assassinate",
    "incite":      "Incite Revolt",
    "frame":       "Frame Empire",
    "defense":     "Defense",
}

# Cost in BC to train one spy.
SPY_COST = 100

# Resolution tuning.
BASE_SPY_SKILL = 2
BASE_SECURITY = 2
CAUGHT_CHANCE = 0.40          # chance a failed spy is caught
ASSASSINATE_CAUGHT_BONUS = 0.10  # wet work is louder — extra catch risk
MIND_SCAN_CAUGHT_BONUS = 0.35  # extra catch chance when defender has Mind Scan
INCIDENT_ATTITUDE_HIT = -15   # target's attitude toward an identified aggressor
SABOTAGE_BC_DRAIN = 40        # BC stolen when there's no building to wreck

# Incite Revolt tuning.
INCITE_GUERRILLA_MIN = 3      # guerrilla turns added on success
INCITE_GUERRILLA_MAX = 5
INCITE_FRAME_BC_DRAIN = 30    # fallback BC drain when no viable colony


class Espionage:
    def __init__(self):
        # empire_id -> trained spy count
        self.spies: dict[int, int] = {}
        # (attacker_id, target_id) -> {mission: int} — REALIZED active
        # counts (spies actually on the job right now).
        self.missions: dict[tuple[int, int], dict[str, int]] = {}
        # Mirror of ``missions`` but for DESIRED counts. The +/- stepper
        # writes here; lost spies do NOT decrement desired, so freshly
        # trained replacements automatically re-fill the slot.
        self.desired: dict[tuple[int, int], dict[str, int]] = {}
        # empire_id -> N. Each turn, if spy_count < N, one spy is
        # auto-trained (if BC affords). 0 = off (manual training only).
        self.auto_train_target: dict[int, int] = {}
        # rolling log of notable events (player-facing)
        self.log: list[str] = []

    # -- queries --------------------------------------------------------

    def spy_count(self, empire_id: int) -> int:
        return self.spies.get(empire_id, 0)

    @staticmethod
    def _ensure_keys(slot: dict[str, int]) -> dict[str, int]:
        for m in MISSIONS:
            slot.setdefault(m, 0)
        return slot

    def _mission_slot(self, attacker: int, target: int) -> dict[str, int]:
        """Realized (active) mission slot — spies actually working."""
        key = (attacker, target)
        if key not in self.missions:
            self.missions[key] = {m: 0 for m in MISSIONS}
        return self._ensure_keys(self.missions[key])

    def _desired_slot(self, attacker: int, target: int) -> dict[str, int]:
        """Desired mission slot — what the player wants. Sticky across
        spy deaths so freshly trained replacements can refill."""
        key = (attacker, target)
        if key not in self.desired:
            # Inherit from any pre-existing active slot so old saves /
            # tests that only set ``missions`` still see consistent
            # desired counts. Subsequent +/- via adjust_mission writes
            # directly here.
            seed = dict(self._mission_slot(attacker, target))
            self.desired[key] = seed
        return self._ensure_keys(self.desired[key])

    def mission_count(self, attacker: int, target: int, mission: str) -> int:
        """The DESIRED count for the slot — this is what the player
        controls and what the UI displays. The realized (active) count
        may be lower temporarily after a spy dies."""
        return self._desired_slot(attacker, target).get(mission, 0)

    def active_count(self, attacker: int, target: int, mission: str) -> int:
        """Spies actually working this slot right now."""
        return self._mission_slot(attacker, target).get(mission, 0)

    def assigned_offensive(self, empire_id: int) -> int:
        """Active spies committed to offensive work. Defense pool =
        spy_count - this. Trimmed counts (post spy-death) are reflected
        here; desired-but-unfilled gaps are NOT counted."""
        total = 0
        for (atk, _tgt), slot in self.missions.items():
            if atk == empire_id:
                total += sum(slot.values())
        return total

    def defense_count(self, empire_id: int) -> int:
        """Spies not on an offensive mission defend the home empire."""
        return max(0, self.spy_count(empire_id) - self.assigned_offensive(empire_id))

    def unassigned(self, empire_id: int) -> int:
        """Alias for defense_count — spies free to be reassigned."""
        return self.defense_count(empire_id)

    def auto_train_target_for(self, empire_id: int) -> int:
        return self.auto_train_target.get(empire_id, 0)

    # -- mutations ------------------------------------------------------

    def train_spy(self, empire_id: int, n: int = 1):
        self.spies[empire_id] = self.spies.get(empire_id, 0) + n
        # New recruit might fill a gap left by a fallen colleague.
        self._reconcile(empire_id)

    def adjust_mission(self, attacker: int, target: int, mission: str, delta: int):
        """Move ``delta`` spies onto/off a mission. Writes to ``desired``
        and then reconciles to active. Increases beyond the trained pool
        are allowed in desired (sticky goal — auto-trained spies will
        fill it later), but the active count is clamped to free spies."""
        if mission not in MISSIONS or attacker == target:
            return
        d_slot = self._desired_slot(attacker, target)
        cur = d_slot.get(mission, 0)
        new = max(0, cur + delta)
        # Cap manual increases at trained spy count to avoid runaway
        # phantom goals — desired beyond spy_count is meaningless without
        # auto-train to back it up.
        if delta > 0:
            cap = self.spy_count(attacker)
            new = min(new, max(cur, cap))
        d_slot[mission] = new
        self._reconcile(attacker)

    def set_auto_train_target(self, empire_id: int, target: int):
        target = max(0, int(target))
        if target == 0:
            self.auto_train_target.pop(empire_id, None)
        else:
            self.auto_train_target[empire_id] = target

    def lose_spy(self, attacker: int, target: int, mission: str):
        """A caught spy is removed from the pool and from the ACTIVE
        slot. Desired stays put — a replacement spy will re-fill it."""
        slot = self._mission_slot(attacker, target)
        if slot.get(mission, 0) > 0:
            slot[mission] -= 1
        self.spies[attacker] = max(0, self.spies.get(attacker, 0) - 1)

    def _reconcile(self, empire_id: int):
        """Make active counts match desired, constrained by trained
        spies. Trims any active counts that exceed desired (player just
        decreased a stepper), then fills gaps in deterministic order
        (lowest target id first, MISSIONS order). Free spies left over
        stay on defense duty."""
        # 1. Trim active where it exceeds desired.
        for (a, t), a_slot in self.missions.items():
            if a != empire_id:
                continue
            d_slot = self._desired_slot(a, t)
            for m in MISSIONS:
                cap = d_slot.get(m, 0)
                if a_slot.get(m, 0) > cap:
                    a_slot[m] = cap
        # 2. Fill gaps with whatever free spies we have.
        free = self.defense_count(empire_id)
        if free <= 0:
            return
        gaps: list[tuple[int, int, str, int]] = []
        for (a, t), d_slot in self.desired.items():
            if a != empire_id:
                continue
            a_slot = self._mission_slot(a, t)
            for m in MISSIONS:
                want = d_slot.get(m, 0)
                have = a_slot.get(m, 0)
                if have < want:
                    gaps.append((t, MISSIONS.index(m), m, want - have))
        gaps.sort()
        for t, _idx, m, gap in gaps:
            n = min(gap, free)
            if n <= 0:
                break
            self._mission_slot(empire_id, t)[m] += n
            free -= n

    def _log(self, msg: str):
        self.log.append(msg)
        if len(self.log) > 60:
            self.log = self.log[-60:]

    # -- persistence ----------------------------------------------------

    def save(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM spies")
            conn.execute("DELETE FROM spy_missions")
            conn.execute("DELETE FROM spy_missions_desired")
            conn.execute("DELETE FROM espionage_settings")
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
            for (atk, tgt), slot in self.desired.items():
                for mission, n in slot.items():
                    if n > 0:
                        conn.execute(
                            "INSERT INTO spy_missions_desired (attacker, target, mission, count) "
                            "VALUES (?, ?, ?, ?)",
                            (atk, tgt, mission, n),
                        )
            for eid, target in self.auto_train_target.items():
                if target > 0:
                    conn.execute(
                        "INSERT INTO espionage_settings (empire_id, auto_train_target) "
                        "VALUES (?, ?)",
                        (eid, target),
                    )
            conn.commit()

    def load(self):
        self.spies.clear()
        self.missions.clear()
        self.desired.clear()
        self.auto_train_target.clear()
        with get_connection() as conn:
            for row in conn.execute("SELECT * FROM spies"):
                self.spies[row["empire_id"]] = row["count"]
            for row in conn.execute("SELECT * FROM spy_missions"):
                slot = self._mission_slot(row["attacker"], row["target"])
                slot[row["mission"]] = row["count"]
            for row in conn.execute("SELECT * FROM spy_missions_desired"):
                slot = self._desired_slot(row["attacker"], row["target"])
                slot[row["mission"]] = row["count"]
            for row in conn.execute("SELECT * FROM espionage_settings"):
                if row["auto_train_target"] > 0:
                    self.auto_train_target[row["empire_id"]] = row["auto_train_target"]
        # Pre-existing saves had only ``spy_missions`` (active count) —
        # seed desired from active so the sticky behaviour kicks in on
        # the next death without losing prior assignments.
        for key, slot in self.missions.items():
            self.desired.setdefault(key, dict(slot))


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


def _auto_train_pass(game, esp, cm):
    """Train one spy per empire per turn while ``auto_train_target`` is
    > current count AND the empire can afford ``SPY_COST``. Caps at +1
    per turn so an empire with deep treasure can't sprint up to a fleet
    of spies in a single tick — same cadence as the AI's training
    heuristic. Player only — AI handles its own training in ``_ai_espionage``."""
    writes: list[tuple[int, int, int]] = []
    for _eid, emp in cm.get_all(Empire):
        # Skip AI; AI training lives in ai.py and the player doesn't get
        # a free spy on top of its own logic.
        if not emp.is_player:
            continue
        target = esp.auto_train_target_for(emp.id)
        if target <= 0:
            continue
        if esp.spy_count(emp.id) >= target:
            continue
        if emp.bc < SPY_COST:
            continue
        emp.bc -= SPY_COST
        esp.train_spy(emp.id)
        writes.append((emp.id, emp.bc, emp.research_points))
        esp._log(f"Auto-trained a new spy ({SPY_COST} BC).")
    if writes:
        with get_connection() as conn:
            for eid, bc, rp in writes:
                update_empire_economy(conn, eid, bc, rp)
            conn.commit()


def espionage_tick(game, new_turn: int):
    """Turn callback: auto-train, resolve every offensive spy, then
    reconcile and persist."""
    esp = getattr(game, "espionage", None)
    if esp is None:
        return
    cm = game.component_mgr
    diplo = getattr(game, "diplomacy", None)
    rng = random
    unlocked = _unlocked_by_empire(cm)
    player = game.player_empire()
    player_id = player.id if player else None

    # Auto-train pass: one spy per empire per turn while under target +
    # affordable. Mirrors the cadence of the AI's own training cap so
    # an auto-trained player can't sprint past 1 spy/turn either.
    _auto_train_pass(game, esp, cm)

    def name(eid):
        emp = _empire_for(cm, eid)
        return emp.name if emp else f"Empire {eid}"

    # Snapshot the missions so lose_spy mutations during iteration are safe.
    # All currently-living empire ids, so Frame missions know who can be blamed.
    living_ids = [e.id for _x, e in cm.get_all(Empire)]
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
                                 atk_set, tgt_set, name, player_id, rng,
                                 living_ids, diplo)
            else:
                _resolve_failure(game, esp, diplo, atk, tgt, mission,
                                 atk_set, tgt_set, name, player_id, rng, new_turn)

        conn.commit()

    if diplo is not None:
        diplo.save()
    esp.save()


def _resolve_success(game, conn, cm, esp, atk, tgt, mission,
                     atk_set, tgt_set, name, player_id, rng,
                     living_ids=None, diplo=None):
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
    elif mission == "sabotage":
        _do_sabotage(conn, cm, esp, atk, tgt, name, mine, theirs, rng,
                     blame=None)
    elif mission == "frame":
        # Pick a random third empire to blame. With no viable scapegoat
        # the op silently fizzles — credits already spent on training.
        third_pool = [eid for eid in (living_ids or [])
                      if eid not in (atk, tgt)]
        if not third_pool:
            return
        blame = rng.choice(third_pool)
        _do_sabotage(conn, cm, esp, atk, tgt, name, mine, theirs, rng,
                     blame=blame)
        # The target empire's attitude toward the patsy drops as if the
        # patsy had been identified spying — diplomatic incident by proxy.
        if diplo is not None:
            diplo.adjust_attitude(tgt, blame, INCIDENT_ATTITUDE_HIT)
    elif mission == "assassinate":
        _do_assassinate(game, esp, atk, tgt, name, mine, theirs, rng)
    elif mission == "incite":
        _do_incite(conn, cm, esp, atk, tgt, name, mine, theirs, rng)


def _resolve_failure(game, esp, diplo, atk, tgt, mission,
                     atk_set, tgt_set, name, player_id, rng, turn):
    caught_chance = CAUGHT_CHANCE
    target_mind_scan = empire_has_mind_scan(tgt_set)
    if target_mind_scan:
        caught_chance += MIND_SCAN_CAUGHT_BONUS
    if mission == "assassinate":
        caught_chance += ASSASSINATE_CAUGHT_BONUS
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


def _do_sabotage(conn, cm, esp, atk, tgt, name, mine, theirs, rng, blame=None):
    """Shared sabotage resolution. ``blame`` is the empire id to surface
    in the log instead of the real attacker (Frame Empire). The blamed
    empire's diplomatic hit is handled by the caller."""
    perpetrator_label = name(blame) if blame is not None else name(atk)
    framed = blame is not None
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
            if framed:
                esp._log(f"Your saboteur destroyed {pname} on a {name(tgt)} "
                         f"colony — {name(blame)} takes the blame!")
            else:
                esp._log(f"Your saboteur destroyed {pname} on a {name(tgt)} colony!")
        elif theirs:
            esp._log(f"{perpetrator_label} sabotaged {pname} on one of your colonies!")
        else:
            esp._log(f"{perpetrator_label} sabotaged {pname} on a {name(tgt)} colony.")
        return
    emp = _empire_for(cm, tgt)
    if emp is None or emp.bc <= 0:
        return
    drain = min(SABOTAGE_BC_DRAIN, emp.bc)
    emp.bc -= drain
    update_empire_economy(conn, emp.id, emp.bc, emp.research_points)
    if mine:
        if framed:
            esp._log(f"Your saboteur drained {drain} BC from {name(tgt)} — "
                     f"{name(blame)} takes the blame!")
        else:
            esp._log(f"Your saboteur drained {drain} BC from {name(tgt)}!")
    elif theirs:
        esp._log(f"{perpetrator_label} drained {drain} BC from your treasury!")


def _do_assassinate(game, esp, atk, tgt, name, mine, theirs, rng):
    """Kill one of ``tgt``'s hired leaders at random."""
    leaders_mgr = getattr(game, "leaders", None)
    if leaders_mgr is None:
        return
    pool = leaders_mgr.for_empire(tgt)
    if not pool:
        # No leader to kill — silent failure. Spy is not refunded.
        if mine:
            esp._log(f"Your assassin found no leader to target in {name(tgt)}.")
        return
    victim = rng.choice(pool)
    leaders_mgr.dismiss(victim.id)
    leaders_mgr.save()
    if mine:
        esp._log(f"Your assassin killed {victim.name} ({name(tgt)} leader)!")
    elif theirs:
        esp._log(f"{name(atk)}'s assassin killed your leader {victim.name}!")
    else:
        esp._log(f"{name(atk)} had {victim.name} ({name(tgt)} leader) assassinated.")


def _do_incite(conn, cm, esp, atk, tgt, name, mine, theirs, rng):
    """Pick one of ``tgt``'s colonies and seed guerrilla unrest. Reset
    assimilation_progress so any non-native captive population effectively
    starts over."""
    candidates: list[tuple[int, object]] = []
    for entity_id, owner in cm.get_all(Owner):
        if owner.empire_id != tgt:
            continue
        planet = cm.get_component(entity_id, Planet)
        if planet is None:
            continue
        pop = cm.get_component(entity_id, Population)
        if pop is None or pop.current < 2:
            # Need at least 2M pop to support a uprising worth the name.
            continue
        candidates.append((entity_id, planet))
    if not candidates:
        # No viable colony — fall back to a BC drain so the spy still
        # earns its keep. Mirrors the sabotage fallback.
        emp = _empire_for(cm, tgt)
        if emp is None or emp.bc <= 0:
            return
        drain = min(INCITE_FRAME_BC_DRAIN, emp.bc)
        emp.bc -= drain
        update_empire_economy(conn, emp.id, emp.bc, emp.research_points)
        if mine:
            esp._log(f"Your agitators stirred unrest costing {name(tgt)} "
                     f"{drain} BC in damages.")
        elif theirs:
            esp._log(f"Unrest cost your treasury {drain} BC in damages.")
        return
    _entity, planet = rng.choice(candidates)
    extra = rng.randint(INCITE_GUERRILLA_MIN, INCITE_GUERRILLA_MAX)
    planet.guerrilla_turns = max(planet.guerrilla_turns, extra)
    planet.assimilation_progress = 0
    update_planet_conquest(conn, planet.id, planet.original_race,
                           planet.assimilation_progress, planet.guerrilla_turns)
    if mine:
        esp._log(f"Your agents incited a revolt on a {name(tgt)} colony "
                 f"— {extra} turns of guerrilla unrest.")
    elif theirs:
        esp._log(f"{name(atk)} stirred a revolt on one of your colonies "
                 f"— guerrillas for {extra} turns.")
    else:
        esp._log(f"{name(atk)} incited unrest on a {name(tgt)} colony.")


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

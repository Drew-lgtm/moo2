# Backlog

Captured ideas that aren't being worked on now but should be picked up
later. Each entry sketches the goal, the scope, and where the work
would live in the codebase. Strike-through items as they ship.

---

## Quality of life

### ~~Right-click tooltips~~ (foundation landed; remaining surfaces below)

Central tooltip widget (`ecs/tooltip.py`) + format helpers
(`ecs/tooltips.py`) + `Game._handle_tooltip` dispatch landed. Scenes
implement `tooltip_at(pos) -> list[str] | None`; the run-loop calls
that on right-click and draws the widget on top of everything else.
LMB or Esc hides it.

**Covered surfaces:**

- Tech cards in the Research scene (name, field, tier, cost, prereqs,
  effects, tier alternatives, unlocked/locked-out status).
- Bottom UI bar buttons (one-line purpose).
- Galaxy stars (name, planet count, owners; fog-of-war note on
  unexplored stars).
- System-view planets (type · size · richness · gravity, population,
  building queue, features, ownership).
- Build-screen project rows (cost, category, effects, required tech;
  ship rows surface the live auto-loadout).
- All panel scenes (Colonies / Planets / Info / etc.) get bar
  passthrough so the bottom buttons stay inspectable everywhere.

**Still to wire (same pattern — `tooltip_at` returning helper
output):**

- Ship icons in the System View cluster (already have
  `tooltips.ship_tooltip`; need to add hit-rects to the SystemView
  ship-drawing pass).
- Diplomacy treaty / declare-war buttons — explain the treaty effect
  and the AI acceptance threshold.
- Leader cards in the Leaders scene — skill effect, salary, current
  post (helper not yet written; cribbing from
  `Leader.effect_text` is straightforward).
- Espionage rows / mission steppers — explain Steal Tech vs Sabotage,
  what catching a spy costs.
- Colony-screen buildings list — show project effect on right-click.
- Pause / Main menu options — small affordance.

None of these blockers — they're just the next wave of the same
template.

---

## Possible next pillars

- **Random events** (space monsters guarding stars, derelicts you can
  salvage for free tech, plagues hitting a colony, pirate raids,
  supernovae, artifact ruins). High variety per unit of effort.
- **Antarans / endgame threat** — a periodic high-tech raid spawned
  from a wormhole, forcing late-game fleet readiness and breaking the
  snowball phase. Could be triggered around Hyper Drives unlock.
- **Marines + ground combat depth** — Powered Armor and Personal
  Shield stop being flavour text; each Troop Transport carries marines
  with a per-empire combat stat boosted by those techs. Makes invasion
  outcomes turn on tech, not just transport count.
- **Tactical combat UI** — MOO2's signature interactive battle mode.
  Huge scope (own scene + per-ship orders + per-round resolution
  display); only worth it if the rest of the game feels solid.
- **Custom ship design** — player-authored loadout templates that
  override the auto-fit. Adds depth for the player without breaking
  the AI's auto-design.
- **Real scoring polish** — pillars and outcome multipliers are in
  place; could add tie-breakers (longest peace, fewest losses) and a
  per-pillar high-score column to the Hall of Fame.

---

## Open stubs (~17 left after the last cleanup)

These techs are still flavour-only because each needs a new system to
hook into. Notes on what each would require:

- **Powered Armor / Personal Shield** — marines / ground combat depth
  (see pillar above).
- **Artificial Planet / Gaia Engineering** — programmatic creation /
  conversion of planet entities at runtime.
- **Atmospheric Terraforming / Irradiation Resistance / Adaptive
  Evolution** — colonization-eligibility overrides for Toxic /
  Radiated / Inferno biomes.
- **Subspace Communications / Battle Scanner extensions** — combat
  initiative or first-strike mechanic.
- **Subspace Disruptor / Warp Dissipator** — in-system retreat
  prevention.
- **Energy Absorber / Emergency Energy / Molecular Compression** —
  shield-recharge / energy-pool mechanics beyond the current shield
  HP system.
- **Federation / Galactic Currency Exchange / Galactic Unification** —
  deeper diplomatic states (federations, currency pacts, unified
  empires).
- **Planetary Barrier Shield** — a new building project type that
  contributes to planetary defense rating.
- **Bio Weapons** — planet-targeting ship weapon that damages pop /
  buildings instead of fleets.
- **Xeno Traitcraft** — mid-game race-trait re-selection screen.
- **False Flag Ops / Assassination Protocol** — new spy mission types
  (frame a rival; eliminate enemy leaders).

---

## Internal / not-doing-yet

- **techs.py → SQLite table.** Considered and rejected for now (rules
  belong in code, not DB; the codebase keeps every catalog as a
  Python dict; a SQL schema either gets rigid columns or just stores
  the same dict as JSON). If modding ever becomes a real goal, the
  right move is loading techs from a flat YAML/JSON file at startup,
  not a SQLite table.

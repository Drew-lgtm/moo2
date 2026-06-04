# Backlog

Captured ideas that aren't being worked on now but should be picked up
later. Each entry sketches the goal, the scope, and where the work
would live in the codebase. Strike-through items as they ship.

---

## Quality of life

### Right-click tooltips on everything

**Goal:** A right-click on any interactive element pops a small, short
hint describing what it is / what it does. Left-click still acts on
the element; right-click only inspects.

**Scope:**

- **Tech cards** (research scene): name, field, tier, cost, prereqs,
  effect summary ("+2 spy defense", "+3 attack per slot, size 3",
  "Battle Pods: +50% ship space"). Mention if it's currently locked
  out via a tier-choice exclusion.
- **Bottom UI buttons** (Colonies, Planets, Research, …, Espionage,
  Info, Turn): one-line purpose.
- **Stars** (galaxy view): name, owner, planet count, your sensor /
  exploration status, "Right-click to inspect" etc.
- **Planets** (system view + colony screen): type · size · richness ·
  gravity · special features, base outputs, current owner.
- **Ships in cluster** (system view): class, frozen loadout (armor /
  shield / N× weapon / specials), combat stats.
- **Diplomacy treaty buttons**: what the treaty does + AI acceptance
  thresholds (clearly tagged as a hint, not exact).
- **Leader / spy rows**: explain the per-skill effect.
- **Build screen rows**: cost in production, effects on completion,
  prereq tech.

**Implementation sketch:**

- One central tooltip widget (`ecs/scenes/tooltip.py`) that any scene
  can hand a `(rect, lines, anchor=pos)` to. Drawn last each frame so
  it sits above everything.
- Each scene records a `_tooltip_targets: list[(rect, payload)]` on
  draw; the scene's `handle_event` checks RMB-down against the list
  and fires `tooltip.show(payload, pos)` / `tooltip.hide()` on
  click-away.
- Payloads use small `tooltip.from_tech(tech_id)`, `from_planet(p)`,
  etc. helpers so the formatting stays consistent across scenes.

**Why not now:** touches every interactive scene — about 10 files —
and the formatting helpers want to land in one batch for consistency.
Big enough to deserve its own session.

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

# Master of Galaxy — Player's Manual

A 4X turn-based strategy game: **eX**plore, **eX**pand, **eX**ploit,
**eX**terminate. You start with a single homeworld — no ships — and you
win by out-growing, out-thinking, or out-shooting everyone else. Your
first job is to build something that can leave the system.

```bash
python main.py
```

---

## The core loop

Every turn you do some mix of five things, then press **End Turn**:

1. **Assign workers** on each colony (farmers / workers / scientists).
2. **Queue buildings and ships** on colonies that are idle.
3. **Pick research** (and queue what comes after it).
4. **Move fleets** — scout, settle, raid, defend.
5. **Talk or fight** — diplomacy, espionage, invasion.

When you end the turn, everything resolves at once: AI empires act,
colonies grow and produce, fleets arrive, battles happen, events fire.

---

## Screens and shortcuts

| Key | Screen | What it's for |
|-----|--------|---------------|
| `G` | Galaxy | The star map. Move fleets, open systems. |
| `C` | Colonies | Every colony's output at a glance. |
| `P` | Planets | Every known planet, including uncolonised ones. |
| `R` | Research | The tech tree; pick and queue research. |
| `D` | Diplomacy | Treaties, war and peace. |
| `E` | Espionage | Spies: steal tech, sabotage, incite revolt. |
| `L` | Leaders | Hire and assign officers. |
| `I` | Info | Empire stats, **government**, research + tech list. |
| `T` | — | End turn. |
| `F1` | Help | Quick reference, over whatever screen you're on. |
| `Esc` | — | Back / pause menu. |

**Right-click almost anything** for a tooltip explaining it. Panels
scroll with the mouse wheel, `PgUp`/`PgDn`, `Home`/`End`.

---

## Your economy

Each colony's population splits into three jobs:

- **Farmers** make food. Food feeds your *whole empire* — a negative
  balance halts growth, and a colony that can't feed itself locally
  starves (the worst local deficit goes first).
- **Workers** make industry, which builds whatever the colony is
  constructing. With nothing queued, industry becomes **BC** (money).
- **Scientists** make research.

A planet's biome, size, richness and gravity all change these outputs.
Buildings add flat bonuses on top.

### Build modes

Instead of a building, a colony can be set to a permanent **mode**:

- **Trade Goods** — turn all industry into BC.
- **Housing** — turn all industry into population growth.

### Money out

- **Ship upkeep**: your fleet costs BC every turn (a fraction of its
  build cost). A big idle navy is a real drain — **scrap** obsolete
  hulls from the fleet panel to recover 25% and stop paying for them.
- If upkeep exceeds income your treasury drains to zero (you never go
  into debt, you just stop banking money).

---

## Colony morale

Every colony has a **morale** level (0–100) shown on its colony screen.
It scales industry, research and trade between **0.75×** and **1.25×** —
food is never affected.

Morale comes from your **government** plus conquest status. A world you
just conquered is restive until it assimilates.

## Government

Set on the **Info** screen. Three types, unlocked by research:

| Government | Needs | Effect |
|---|---|---|
| **Dictatorship** | — (default) | Neutral baseline. |
| **Democracy** | Governance | +20% research, +10% BC, happier home worlds — but conquered worlds resent you badly. |
| **Imperium** | Galactic Unification | Higher morale everywhere, and a firm grip on conquered worlds. |

Democracy is the builder's choice; Imperium is the conqueror's.

---

## Research

Pick a target on the **Research** or **Info** screen. Click another tech
to **queue** it — when the current one finishes, the next valid entry
starts automatically. Click the tech you're researching to cancel it and
promote the queue.

**Tier choices matter.** Picking one tech in a tier locks out its
alternatives for good (you can still steal them with spies). Choose
deliberately.

---

## Ships and combat

### Designing ships

The **Design Ships** button on the build screen opens the designer. A
hull has a space budget; you spend it on armour, shields, a weapon, and
specials. Weapons come in three **mounts**:

- **Normal** — baseline.
- **Heavy** — double damage for double space.
- **Point-Defense** — half damage, but the guns shoot down incoming
  missiles and fighters.

Designs are **frozen at build time** — researching better tech doesn't
upgrade existing ships. Use **Refit** at a colony to rebuild parked ships
for a fraction of the build cost: each is brought up to your newest saved
design for its hull class, or to your best available tech if you haven't
designed one.

### Beams vs missiles vs point-defense

This is the central combat trade-off:

- **Beam weapons** (lasers, phasors, plasma) always hit. Reliable.
- **Missiles** (nuclear → pulson → merculite → proton torpedo) and
  **carrier fighters** hit harder per slot — but **point-defense shoots
  them down** before they land.
- **Point-defense** comes from the PD mount and from *Anti-Missile
  Rockets*. It's pooled across your fleet each round, so a couple of PD
  escorts protect everyone.

If an enemy leans on missiles, build point-defense and their damage
evaporates. If they have no PD, missiles hit far harder than beams.

### Veterancy

Ships that survive battles earn experience and rank up:
**Green → Regular → Veteran → Elite → Ultra-Elite**. Each rank adds
attack and hull. A long-lived fleet is worth more than its tonnage —
protect your veterans. The fleet tooltip and combat report show ranks.

### Fighting

When your fleet meets a hostile one you choose: **Attack** (play it out
on the hex grid), **Auto-resolve**, or **Retreat**. Both battle paths use
the same damage rules, so auto-resolving isn't a shortcut to better odds.

Afterwards, the **combat report** shows each side's beam vs missile fire,
how much point-defense shot down, and the veteran ranks that fought.

---

## Expanding

- **Colony Ship** → settles a habitable planet at its star.
- **Outpost Ship** → claims an empty system without settling it.
- **Terraforming** upgrades a planet's biome (e.g. Tundra → Terran), and
  **Gaia Transformation** goes further. This raises the population cap
  permanently.

### What blocks you

- **Space monsters** guard the richest systems. You cannot colonise or
  outpost a guarded system until the guardian is destroyed. Killing one
  pays a bounty (BC + research) and opens the system.
- **Fuel range** — you can't send fleets beyond your supply reach.

---

## War

- **Invasion** — Troop Transports land marines to capture a colony.
- **Bombardment** — warships in orbit kill population and wreck
  buildings from space; enough of it destroys the colony outright.
- **Blockade** — simply parking warships over an enemy colony cuts its
  trade income. Cheap, and it doesn't need a single shot fired.
- **Warp Dissipator** (tech) — enemy fleets can't jump out of a system
  your warships hold. They fight or die.

Attacking someone you have a treaty with is a betrayal, and everyone
notices.

---

## Threats

- **Antaran raiders** appear from turn 40 and return periodically,
  striking the galaxy's largest colony with apex warships — often yours,
  but they'll hit a rival's capital just as happily. Planetary defenses
  and a home fleet matter.
- **Space monsters** sit still and guard, but they're brutal if you
  attack under-strength.

---

## How to win

| Path | How |
|---|---|
| **Conquest** | Be the last empire with colonies. |
| **Diplomatic** | Win a Galactic Council vote (convenes every 25 turns; needs two-thirds of votes). |
| **Antaran** | Research the **Dimensional Portal**, build it on a colony, mass a fleet there, and destroy Antares. The hardest path — and it scores highest. |

Beware: the AI can take the Antaran path too. If a rival builds a portal
and masses a fleet, you're on a clock.

Your final score is broken into six pillars (population, colonies, tech,
buildings, economy, military) and multiplied by your victory type and how
fast you won. It's recorded in the Hall of Fame.

---

## Tips

- An idle colony already turns its industry into BC, so you lose nothing
  by leaving one unqueued — but setting **Trade Goods** makes that choice
  explicit, so a stray click can't quietly start a building you didn't
  want. Use **Housing** instead when you'd rather grow than earn.
- Watch the **food balance** in the top bar; starvation is silent and
  expensive.
- Scrap obsolete ships instead of paying upkeep on them forever.
- Check the **Last Turn** log on the galaxy screen — promotions,
  blockades, terraforming and treasury warnings all appear there.
- Right-click things you don't recognise.

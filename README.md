# Master of Galaxy (MOO2-Inspired Python Game)

## 🎮 Project Overview
**Genre:** 4X Turn-Based Strategy
**Tech Stack:** Python, Pygame, ECS, SQLite
**Architecture:** Hybrid ECS + Database
**Inspiration:** Master of Orion 2 (MOO2)

---

## Quick Start

```
pip install -r requirements.txt
python main.py
```

Save files (`saves/slot*.db`) and the active `galaxy.db` are created on
demand and are gitignored.

---

## ✅ Features Completed

### Core engine
- ECS framework: `EntityManager`, `ComponentManager`, components in `ecs/components.py`.
- Scene framework (`ecs/scene.py`, `ecs/scenes/`): main menu, empire setup, galaxy, system view, pause, plus five panel scenes (Colonies, Planets, Leaders, Races, Info).
- `Game` class (`ecs/game.py`) owns world state, the scene manager, the bottom UI bar, and the per-turn callback list.
- Hybrid ECS + SQLite: components live in memory, `galaxy.db` is the source of truth; PRAGMA-based migrations upgrade older DBs in place.

### Galaxy generation
- Procedural star placement with overlap avoidance; weighted star classes (O–M).
- Per-star planets with type and size, weighted distributions.
- Reserved star names from the MOO2 universe.
- Reproducible: the RNG seed is persisted per game so saves roll out identically.

### Empires
- 2–8 empires per game.
- Each empire: name, color, race, home star, tech level, BC, research points, AI personality, `is_player` flag.
- Persisted in the `empires` table; player flag survives reloads.
- AI empires cycle through four personalities (see *AI* below).

### Save / Load
- 9 slots in `saves/slot*.db`; pause menu Save / Load Game prompts for a slot (digits 1–9).
- Esc cancels a pending slot pick; saves are atomic copies of the active DB.

### Population & food
- Each colonized planet has a `Population(current, max, growth_progress, farmers, workers, scientists)` component.
- Pop grows on a logistic curve (`r * pop * (max-pop) / max`); fractional growth accumulates between turns.
- Food balance per empire halts growth and starves the largest colony when negative.
- New pop auto-defaults to farmers when the empire surplus is tight, else workers.

### Worker economy
- **Farmers → food**, **workers → industry**, **scientists → research** per planet.
- Per-pop output varies by planet type (e.g. Gaia 3 food/farmer, Inferno 2 industry/worker).
- Idle planets convert industry to BC; planets building a project divert industry to progress.
- System View has per-class +/− worker pickers for player planets; writes through to DB immediately.

### Buildings & per-planet build queue
- 6 buildings in `ecs/projects.py`: Factory, Granary, Research Lab, Hydroponics, Marketplace, Capital.
- Effect keys: `bc`, `research`, `max_pop`, `growth_rate`, `food`, `industry`.
- Queue per planet (`BuildState.queue`); MOO2-style progress overflow carries between items on completion.
- Tech-gated entries grey out with `"Locked: <Tech>"` until research unlocks them.

### Tech tree
- 5 techs in `ecs/techs.py`: Computer Science, Agriculture, Trade, Industrial Engineering, Governance (prereqs).
- `TechState` per empire (`current_target`, `progress`, `unlocked`); research from production_tick routes to the active target.
- On completion, tech moves to `unlocked` and gates new project entries.
- Info panel's "Research" section lets the player pick targets; AI uses its personality's research priority.

### Ships & fleets
- 5 ship classes in `ecs/ships.py`: Frigate, Carrier, Cruiser, Battleship, Dreadnought, each with cost / speed / attack / hull.
- Ship build projects (`ship_<class>`) live alongside buildings in `PROJECTS`; queueing them spawns a `Ship` entity at completion instead of marking the project completed.
- Ship state: `Ship`, `ShipOwner`, `ShipAt`, `ShipInTransit` (with `total_turns` for animation).
- Right-click a star with player ships → top-right picker shows per-class `[-] N/Max [+]`.
- Right-click another star → dispatches the chosen counts; each ship's transit time = `ceil(parsecs / speed)`.
- In-transit dots animate along the route at `progress = 1 - remaining/total`.
- Galaxy view shows per-star fleet badges colored by owning empire.

### Combat
- `ecs/combat.py` runs at end of turn after fleet movement.
- N-way model: each side eats sum of every other side's attack power; cheapest-hull ships die first.
- Destroyed ships are removed from ECS + DB; engagements recorded in `game.last_combats`.

### AI + Difficulty
- `ai_tick` runs first each turn: rebalance workers → queue building → pick research → dispatch ships (aggressive personalities only).
- 4 personalities in `ecs/personalities.py`:
  - **Balanced** (75% workers, full building roster, ships after buildings).
  - **Economic** (markets and growth, no fleet).
  - **Scientific** (60% scientists, leads with Research Lab, 1 defensive frigate).
  - **Militaristic** (90% workers, heavy ship cadence, attacks the player).
- AI empires cycle Economic → Scientific → Militaristic → Balanced.
- 4 difficulties (Easy 0.5× / Normal 1.0× / Hard 1.75× / Impossible 3.0×) scale AI BC and research output. Player output is untouched.
- Difficulty persists via `META_DIFFICULTY` in the meta table.

### UI
- Galaxy HUD (top-left): empire color bar + name + BC (running, per-turn) + Research (running, per-turn) + Food balance + Turn N.
- Bottom button bar: Colonies, Planets, Leaders, Races, Info, Turn — all wired from the `Game._bind_game_ui`.
- Five scrollable panel scenes (wheel / PgUp / PgDn / Home / End / arrows):
  - **Colonies**: empire color bar + race portrait + star + planet (with type dot) + size + pop + F/W/S + food + industry + research + BC + empire name.
  - **Planets**: every planet grouped by star, with type dot, size, habitable badge, owner color bar.
  - **Races**: portrait grid (skips 0-byte placeholder PNGs).
  - **Info**: turn / seed / star / planet / empire counts, plus a Research section listing every tech with available / researching / unlocked / locked state.
  - **Leaders**: stub.
- Empire setup: name (typeable, blinking caret) · color swatches · `−/+` empire-count picker · 4-button difficulty picker · race portrait grid · Start / Back.
- System View: planet orbits with type/size/pop labels and build status; clickable planets; per-role `F/W/S` worker pickers; two rows of project buttons (ships above, buildings below); selection ring on focused planet.

---

## Controls

| Action | Input |
|---|---|
| Open System View on a star | Left click |
| Select a fleet at a star | Right click (with player ships present) |
| Send selected fleet to a star | Right click target |
| Deselect fleet | Right click source again, or Esc |
| Adjust per-class send count | `[-]` `[+]` in the top-right picker |
| Pause / open menu | Esc |
| Save / Load | Esc → pick menu item → press digit 1-9 for slot |
| Scroll a panel | Mouse wheel, PgUp / PgDn / Home / End, ↑ / ↓ |
| Cancel a panel | Esc |
| Toggle fullscreen | F11 |

The window uses `pygame.SCALED`, so the logical resolution is always
1200×800 but the actual window is shrunk to fit your desktop. F11
toggles between the scaled window and true fullscreen at the same
logical resolution.

---

## Project Structure

```
moo2/
├── main.py                 # entry point: pygame init, Game, scene registration
├── requirements.txt
├── assets/
│   ├── loader.py           # cached image loader; placeholder for 0-byte assets
│   ├── star_name_pool.py
│   ├── backgrounds/, fonts/, races/, ships/, sounds/, stars/, ui/
├── ecs/
│   ├── game.py             # Game class + turn callback registration
│   ├── scene.py            # Scene base + SceneManager
│   ├── components.py       # ECS components (Population, Empire, Ship, ...)
│   ├── entity_manager.py
│   ├── component_manager.py
│   ├── db.py               # SQLite schema + helpers + PRAGMA migrations
│   ├── galaxy_generator.py # procedural galaxy + load_from_db
│   ├── economy.py          # pop growth, food, industry, production_tick
│   ├── projects.py         # building + ship build catalog
│   ├── techs.py            # tech tree catalog
│   ├── ships.py            # ship class catalog
│   ├── fleet.py            # fleet_tick + start_fleet_movement
│   ├── combat.py           # combat_tick
│   ├── ai.py               # ai_tick: AI heuristics
│   ├── personalities.py    # 4 AI personalities
│   ├── difficulty.py       # difficulty constants + multiplier
│   ├── empire_preset.py    # player's chosen empire identity
│   ├── palette.py          # planet + empire color tables
│   ├── ui_bar.py           # BottomUIBar with set_callback
│   ├── system_view.py      # SystemView overlay
│   ├── save_manager.py     # 9-slot save / load
│   └── scenes/
│       ├── main_menu.py
│       ├── empire_setup.py
│       ├── galaxy.py       # HUD + fleet badges + transit animation + picker
│       ├── system_view.py  # SystemView scene wrapper
│       ├── pause.py
│       └── panels.py       # 5 panel scenes
```

---

## Next Steps

### Combat polish
- On-screen combat notification (toast or panel section) — `game.last_combats` is recorded but never surfaced.
- Tactical combat phase (per-ship actions, ranged vs short, retreat option).
- Planet bombardment / blockade so undefended AI fleets at the player's home become a real threat instead of camping.

### Strategic layer
- Planet capture: when a hostile fleet sits at a star with no defenders, take the planets after N turns.
- Diplomacy: trade agreements, alliances, declarations of war.
- AI strategic diversity: per-empire jitter so two militaristic AIs don't act identically.

### Map polish
- Zoom + pan on the galaxy view (the map is currently fixed at 1200×800).
- Hyperlanes (warp lanes between stars) to constrain movement.
- Fog of war / explored vs unexplored stars.

### Economy & gameplay
- Trade Goods as a perpetual project: convert planet industry to BC at a fixed rate.
- Ship maintenance cost in BC so fleets aren't free.
- Per-empire HUD details — info panel could list other empires' BC / research / fleet so the player can scout.

### Polish
- Replace 0-byte placeholder assets in `assets/races/` (8 missing) and `assets/ships/` (all 5 missing). The loader currently shows diagonal-slash placeholders for these.
- Surface AI personality on the Info panel so the player can see who's building what.

---

## Known Limitations

- Several race and ship PNGs in `assets/` are 0-byte placeholders. The loader degrades to a slash-pattern Surface; nothing crashes.
- AI ships parked at the player's home with no defenders don't damage anything (no bombardment / capture yet).
- Combat is one-shot per turn — no tactical phase, no retreat, no targeting.
- Old saves from before each schema migration load with default zeros for new columns; start a new game after a major update for the cleanest experience.

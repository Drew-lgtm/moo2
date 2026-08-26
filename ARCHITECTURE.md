# Architecture

How the code is put together, and the conventions to follow when adding
to it. For gameplay, see [MANUAL.md](MANUAL.md).

---

## Quick start

```bash
pip install -r requirements.txt
python main.py                 # play it
python -m pytest -q            # run the suite (~1-2 min, headless)
```

**Where to start reading.** In this order, and you'll understand most of
the game in an hour:

1. `ecs/components.py` — every piece of state the game has, in one file.
2. `ecs/game.py` — the `Game` object: the turn loop and the scene wiring.
   The `turn_callbacks` list is the spine of the whole simulation.
3. `ecs/economy.py::production_tick` — the biggest system, and a good
   example of the batch-write pattern every tick follows.
4. `ecs/battle.py` — the combat maths, small and self-contained.

**Making your first change.** Say you want a new building:

1. Add an entry to `PROJECTS` in `ecs/projects.py` (cost, category,
   `effects`, optional `required_tech`).
2. If it needs a new effect key, handle it where the others are applied
   in `economy.production_tick`.
3. Add a test next to the similar ones in `tests/`.
4. `python -m pytest -q`.

Nothing else needs touching — the build UI reads `PROJECTS` directly, and
the AI picks it up through its personality's `build_priority`.

---

## The model: ECS mirroring SQLite

The game is a **hybrid ECS + database**:

- **SQLite (`galaxy.db`) is the source of truth.** It holds stars,
  planets, empires, ships, techs, treaties — everything that must
  survive a save/load.
- **The ECS is an in-memory mirror** built from the DB at load, used for
  all per-turn logic because it's far faster to query than SQL.

Every mutation therefore does two things: change the component, and
write the row. Most systems batch their writes into one transaction at
the end of a tick rather than committing per change.

```
EntityManager     — hands out integer entity ids
ComponentManager  — entity id -> component instances
components.py     — the component dataclasses (Planet, Ship, Empire, …)
db.py             — schema, migrations, and most SQL helpers
                    (a few managers run their own queries)
```

A save is literally a copy of `galaxy.db` (`save_manager.py`), so
anything not persisted is lost on load — by design for transient state
like an in-progress Antaran raid.

### Adding a persisted field

1. Add the field to the dataclass in `components.py` (with a default).
2. Add the column in `db.init_db()` **and** an `ALTER TABLE` in the
   matching `_migrate_*` helper — old saves must keep loading.
3. Add an `update_*` helper in `db.py`.
4. Read it back in `galaxy_generator.load_from_db()`, guarded with
   `try/except (IndexError, KeyError)` for saves that predate it.

`Game.load_game()` calls `init_db()` first, so migrations always run
before a save is read.

---

## The turn

`Game.advance_turn()` bumps the turn counter, then calls every function
in `self.turn_callbacks` in order. **Order is load-bearing** — this is
the sequence registered in `Game._bind_game_ui()`:

| # | Tick | Notes |
|---|------|-------|
| 1 | `ai_tick` | AI empires plan and act |
| 2 | `autobuild_tick` | fills idle player colonies if enabled |
| 3 | `pop_growth_tick` | growth, starvation |
| 4 | `production_tick` | industry, BC, research, buildings, ship spawns |
| 5 | `leaders_tick` | salaries, candidate pool |
| 6 | `fleet_tick` | ships in transit arrive |
| 7 | `antaran_tick` | **before** combat, so a new raid fights on arrival |
| 8 | `combat_tick` | resolves battles / queues the player's |
| 9 | `monster_tick` | **after** combat, to detect guardian kills |
| 10 | `exploration_tick` | fog of war |
| 11 | `espionage_tick` | spy missions |
| 12 | `assimilation_tick` | conquered populations |
| 13 | `events_tick` | random events |
| 14 | `diplomacy_tick` | treaty ageing, attitude decay |

After the callbacks, `advance_turn` checks for a council session and the
endgame, and flags idle colonies.

### The player's battles resolve *later*

`combat_tick` does **not** resolve a battle the player has *ships* in.
When the player has ships at the star and at least one empire present is
hostile to them, it builds a `TacticalBattle`, queues it in
`game.pending_engagements`, and skips auto-resolve for that star; the
GalaxyScene routes to the combat-decision scene after the turn and the
battle is played out (or auto-resolved) then. Every other engagement —
including one at a star where the player only holds a colony — resolves
inside the tick.

Anything that must happen when a battle ends therefore has to run in
**both** places: inside `combat_tick` for AI-vs-AI, and in the scene
finalisers (`scenes/tactical.py::_finalise`,
`scenes/combat_decision.py::_auto_resolve`) for the player's. Veterancy
is awarded in `combat_tick` and in both finalisers; space-monster kills
are reconciled by `monster_tick` (the tick after combat) and, so a save
can't happen in between, by both finalisers too.

---

## Combat

There is **one** damage model, in `battle.py`, used by every path:

- `Combatant` — the canonical unit snapshot.
- `apply_hit` — defense → shield → hull for a single hit.
- `resolve_auto` — the multi-round pooled resolver.

Each round, every side that has a hostile present rolls two pools:

- **beam** — direct-fire weapons plus planetary defenses; unstoppable.
- **missile** — missile-category weapons plus carrier `fighter_attack`;
  reduced by the target side's summed **point-defense**.

`combat.py` snapshots ECS ships into `Combatant`s
(`_build_combatants`) or into a hex-grid `TacticalBattle`
(`_build_tactical_battle`). Both apply the same bonuses — hull base
stats, frozen loadout, empire tech/trait bonuses, assigned ship leaders,
and veteran rank — so a fleet is equally strong whichever path runs.

`tactical.py` is the hex layer. Its `attack()` routes damage through
`battle.apply_hit`, and interception draws on a **side-pooled** per-round
budget (`TacticalBattle.intercept`) exactly like the strategic resolver.

---

## Pseudo-empires

Antaran raiders (`antaran.py`, id 9001) and space monsters
(`monsters.py`, id 9002) are **not real empires**. They have an ECS
`Empire` component so they can be named and coloured in combat, but they
own no colonies and are never written to the `empires` table.

Because they appear in `cm.get_all(Empire)`, **any loop over empires must
filter them** with `monsters.is_pseudo_empire(id)`. Forgetting this has
caused real bugs: they've turned up as diplomacy targets, espionage
scapegoats, in the empire count, and had their fleets scrapped by the
elimination check. If you add a loop over all empires, ask whether a
colony-less hostile faction belongs in it.

Their ships use **negative ids** and live only in the ECS. Monsters do
persist — a small `space_monsters` table records which are alive and how
many hulls survive — so a killed guardian stays dead.

---

## Module map

**Core**
`game.py` (the Game object, turn loop, scene wiring) · `db.py` ·
`components.py` · `entity_manager.py` / `component_manager.py` ·
`galaxy_generator.py` (world gen + load) · `save_manager.py` · `scene.py`

**Economy & colonies**
`economy.py` (the big per-turn tick) · `projects.py` (buildings) ·
`colonization.py` · `autobuild.py` · `trade.py` · `government.py`
(governments + morale) · `blockade.py` · `planet_features.py`

**Ships & combat**
`ships.py` (hulls) · `ship_design.py` (loadouts, mounts, stats) ·
`designs.py` (saved blueprints) · `refit.py` · `scrap.py` ·
`battle.py` (damage model) · `combat.py` (strategic resolver) ·
`tactical.py` (hex battles) · `veterancy.py` · `fleet.py` · `fuel.py` ·
`bombard.py` · `invasion.py`

**Tech & empires**
`techs.py` · `races.py` (traits + Evolutionary Mutation) ·
`personalities.py` · `diplomacy.py` · `espionage.py` · `leaders.py` ·
`council.py` · `endgame.py` (scoring, Hall of Fame)

**Threats & endgame**
`antaran.py` (raiders) · `monsters.py` (guardians) · `antares.py`
(Dimensional Portal victory) · `events.py`

**UI** — `scenes/` (roughly one file per screen; `panels.py` holds the
four list/info panels), `ui_bar.py`, `tooltips.py`, `palette.py`,
`turn_log.py`

---

## Conventions

- **Constants over magic numbers.** Tunables live at module top with a
  comment explaining the intent, so balance changes are deliberate.
- **Docstrings explain *why*.** The what is usually obvious from the
  code; the reason a rule exists is not.
- **Simple over abstract.** Prefer a plain function and an explicit loop
  to a framework.
- **Never break old saves.** Additive columns + `_migrate_*` helpers.

---

## Tests

```bash
python -m pytest -q            # everything (~1–2 min)
python -m pytest tests/test_battle.py -q
```

The suite uses the SDL dummy driver (`tests/conftest.py`), so it runs
headless. Tests that touch the database isolate it:

```python
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import ecs.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "x.db")
    db.init_db()
    yield
```

Two tests are deliberately heavyweight and cover composition rather than
units:

- `test_integration_turnloop.py` — boots a real game, runs the whole
  turn loop for a stretch, saves, reloads, keeps playing.
- `test_soak.py` — several full games at different sizes with mid-run
  save/load and cross-cutting invariant checks.

Tests that create a `Game` must release the display
(`pygame.display.quit()`) around it, or a later `set_mode` fails.

**Test the path the player takes.** A UI feature verified by calling its
handler directly can pass over dead code — more than one bug here was a
correctly-implemented feature that no click could reach.

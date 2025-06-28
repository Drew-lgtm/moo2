# Master of Galaxy (MOO2-Inspired Python Game)

## 🎮 Project Overview
**Genre:** 4X Turn-Based Strategy
**Tech Stack:** Python, Pygame, ECS, SQLite
**Architecture:** Hybrid ECS + Database
**Inspiration:** Master of Orion 2 (MOO2)

---

## ✅ Features Completed

### 🏗 Phase 1: Core Engine (ECS)
- Modular ECS framework with:
  - `EntityManager`, `ComponentManager`
  - Components: `Position`, `Name`, `Planet`, `Orbiting`, `StarVisual`, `Owner`, `Empire`
- Pygame rendering loop with responsive input handling

### Phase 2: Procedural Galaxy Generation
- Procedurally generated star systems:
  - Unique names and positions
  - Weighted star classes and planet types
  - Overlap avoidance for clear layout
- Clickable stars with orbiting planet view UI

### Phase 3: Hybrid ECS + SQLite Architecture
- SQLite schema: `stars`, `planets`, `empires`
- `db.py` handles:
  - Table creation
  - Star/planet/empire inserts
  - ECS load from DB
- Galaxy generator writes to DB, then loads into ECS

---

## Save/Load System
- Implemented `save_manager.py`
- 9 Save slots (`slot1.db` → `slot9.db`)
- Autosave system scaffolded (to be triggered per turn)
- Keyboard shortcut-based temporary access:
  - Keys `1–3`: Save to slots 1–3
  - Keys `4–6`: Load from slots 1–3

---

## Empires & Homeworlds
- Empires stored in DB and ECS
- For each empire:
  - Home system spaced evenly from others
  - Guaranteed **Terran, Medium** homeworld
  - Ownership assigned (`Owner` component)
  - Empire component: name, race, color, tech, home_star

---

## Next Steps

### 1. Turn System
- Track current turn number
- Trigger per-turn updates: research, production, autosave

### 2. Population & Production
- Add `Population` component
- Calculate research and production from assigned workers
- Link to tech and abundance modifiers

### 3. UI Enhancements
- Add MOO2-style top and side bars:
  - Show: BC, command points, food, freighters, research, turn #
  - Panels for: Planets, colonies, races, zoom, etc.

### 4. Empire Customization Menu
- Pre-game screen for selecting:
  - Name, color, race, starting tech, etc.

---

## Project Structure

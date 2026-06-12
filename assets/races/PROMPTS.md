# Race Portrait Generation Guide

A reference for generating consistent race portraits for *Master of Galaxy*
using Google Gemini Pro (Imagen) or any other modern image generator.

The goal: each portrait should look like it belongs in a late-1990s
space-strategy game — specifically in the painterly tradition of
**Master of Orion 2** character art — and each portrait's visible
details should make the race's traits readable at a glance. A trader
race should wear gold. A warrior race should bear scars and weapons.
A cybernetic race should show its hardware. The viewer should be able
to guess the race's role without reading a description.

---

## How to use this file

For each portrait you want to generate, paste **three sections** into
Gemini Pro's image generator (or any other tool) as a single prompt:

1. **The Universal Style Guide** (below) — sets the visual language
2. **The Race-Specific Subject Block** — describes the figure and the
   trait cues to embed
3. **The "Must NOT include" list** — woven in as exclusion phrases
   (Gemini has no separate negative-prompt field)

Generate **4-8 variants per race** and keep the one that best matches
the existing real portraits (`alkari.png`, `bulrathi.png`, `darlok.png`,
`elerian.png`, `gnolam.png`, `klackon.png`, `mrrshan.png`, `psilon.png`,
`sakkra.png`, `silicoid.png`).

**Locking style across the set:** after your first successful portrait,
upload it back into Gemini and prompt the next race with *"Generate
another portrait in this exact style, but the subject is..."*. This
keeps brushwork, palette, and lighting consistent across the whole
gallery.

---

## Output specifications

| Property        | Value                                                    |
|-----------------|----------------------------------------------------------|
| Format          | PNG                                                      |
| Resolution      | **1024 × 1024 pixels** (square)                          |
| Aspect ratio    | **1:1**                                                  |
| Colour mode     | RGB or RGBA (alpha optional)                             |
| Background      | Solid dark cosmic void — does NOT need to be transparent |
| Filename        | Lowercase race name, no spaces (e.g. `humans.png`)       |
| Save location   | `assets/races/`                                          |
| Compression     | Standard PNG — file size 200KB–2MB is fine               |

The engine downscales at load time via `pygame.transform.smoothscale`,
so generating at 1024×1024 gives clean results even when shown small.
Anything below 512×512 will look soft when scaled.

**Filename convention:** when you save, delete the existing 0-byte
placeholder PNG of the same name first (the loader skips zero-byte
files, but a stale empty file in the folder is confusing).

---

## Universal Style Guide

> Paste this verbatim at the top of every prompt.

```
Style: painterly digital portrait in the tradition of late-1990s
space-strategy game alien race art — specifically the dramatically-
lit, oil-painted character portraits of Master of Orion 2's empire
selection screen. Head-and-shoulders bust composition, three-quarter
angle, the face occupying the middle 60–70% of a square 1:1 frame.
Heavy chiaroscuro lighting: a single dramatic rim light from the
upper left, deep shadow on the opposite side, subtle bounce light
from below. Background: muted dark cosmic void with a faint nebula
or subtle empire-relevant iconography softly suggested behind the
subject. Visible painterly brushwork, slightly muted but rich
jewel-tone palette, sharp focus on the face. Square 1:1 aspect ratio.
```

---

## What to ALWAYS avoid (paste into every prompt)

> Add this paragraph after the subject description.

```
Must NOT include: any text, letters, numbers, watermarks, signatures,
captions, logos, borders, frames, UI overlays, HUDs, picture-in-
picture overlays, multiple figures, secondary characters, full body
view, distant figure, low-contrast or washed-out colours, plastic
doll-like skin, fish-eye distortion, warped anatomy, extra limbs,
deformed hands, weapons pointed at the viewer, blurry or out-of-
focus face, cartoon style, anime style, chibi proportions, 3D
render appearance, low-poly look, photograph realism, modern Earth
clothing, modern Earth firearms, modern eyeglasses.
```

---

## Trait-to-visual lookup

For each race, the prompt should weave in concrete visual cues that
match its traits. Use this as the source of truth when writing prompts
for any future race:

| Trait                       | Visual cue                                              |
|-----------------------------|---------------------------------------------------------|
| BC bonus / trader           | gold trim, coin pendants, rings, ledger, ornate clasps  |
| Research / scholar          | open book, data slate, glyphs, orbital diagram          |
| Industry / worker           | pistons, gears, soot, calloused hands, factory backdrop |
| Ship attack / gunner        | weapon, war-paint, armoured harness                     |
| Warlord / ground combat     | scars, trophies, kill-tally marks, muscled physique     |
| Fast growth / fertility     | bead-talisman strands, lineage tattoos                  |
| Food bonus / agrarian       | harvest staff, kelp/grain motifs, soil under nails      |
| Defiant / "won't bow"       | upright bearing, broken-chain motif, fierce eyes        |
| Hive Mind / Mind Link       | linked-eye motif, psionic glow, communion expression    |
| Spymaster                   | half-hooded face, two-toned eye, shifting silhouette    |
| Tolerant / hardy            | unprotected in hostile environment                      |
| Subterranean                | dim under-glow, ore veins in skin                       |
| Rich Homeworld              | extravagant ornament, gemstones, brocade                |
| Heavy gravity adapted       | dense muscle, broad chest, low compact stance           |
| Aquatic                     | gill slits, finned crest, iridescent scales             |
| Cybernetic                  | exposed neural ports, optical lens, hydraulic cabling   |

---

# Priority races (currently missing portraits)

These five races are defined in code (`ecs/races.py`) but their PNGs
are 0-byte placeholders. Generate these first.

---

## Humans

- **Filename:** `humans.png`
- **In-code traits:** `bc_bonus`, `research_bonus`
- **Lore one-liner:** "Charismatic traders."
- **Visual cues to embed:** trader (BC bonus), scholar (research bonus)

**Subject block:**

```
Subject: A charismatic Human ambassador-trader, late-30s, intelligent
composed face with a magnetic confident gaze and a faint knowing
half-smile, short practical haircut.

TRADER (bc bonus, visible): wearing a fitted dark navy diplomat's
coat with gold piping at the collar, a small gold coin medallion
prominently hanging at the chest, two visible gold signet rings on
the hand, an ornate gold-clasped scroll tucked into a sash at the
waist.

SCHOLAR (research bonus, visible): a slim glowing data-slate held
in one hand at chest height, faint holographic star-chart glyphs
softly flickering above the slate.

Background: dark cosmic void with very faint gold trade-route lines
suggested as nebular threads in the deep background.
```

**Must include:** the gold medallion, the data-slate, the diplomat's coat.

**Must NOT include:** modern earth business suits, modern eyeglasses,
ties, photographic skin, plus the universal exclusions above.

---

## Meklar

- **Filename:** `meklar.png`
- **In-code traits:** `industry_bonus`, `industry_bonus` (doubled)
- **Lore one-liner:** "Cybernetic industrial machine."
- **Visual cues to embed:** cybernetic body, heavy industry

**Subject block:**

```
Subject: A Meklar industrial cyborg, half-flesh half-machine
humanoid head, one organic pale-grey eye and one glowing amber
optical lens replacing the other.

INDUSTRY (worker bonus, doubled — make this PROMINENT): a heavy
industrial bodyshell visible at the shoulders and neck — brushed
steel armour plating with prominent riveted seams, articulated
hydraulic pistons running from jaw to collar, copper steam valves
bolted to the chest, a smudge of soot across one cheek. Exposed
segmented neural ports along one side of the skull.

Backdrop: the dark interior of a vast forge or factory floor, faint
sparks and amber-orange furnace glow softly visible in the deep
background.

Palette: cold steel grey, brass, copper, burnt orange.

Expression: cold, purposeful — the expression of a being engineered
to produce, not to feel.
```

**Must include:** visible pistons or hydraulic cabling, riveted steel plating, the optical lens eye.

**Must NOT include:** clean / consumer-electronics-style cyborg looks, sleek minimalist sci-fi aesthetic, anime cyborg style.

---

## Nommo

- **Filename:** `nommo.png`
- **In-code traits:** `research_bonus`, `bc_bonus`
- **Lore one-liner:** "Mystical merfolk."
- **Visual cues to embed:** mystic scholar, aquatic, wealth

**Subject block:**

```
Subject: A Nommo mystic-scholar merfolk humanoid, smooth iridescent
blue-green skin with overlapping pearlescent scales catching the
light, large luminous opal eyes, vertical gill-slits along the neck,
a fluttering crest of fine membranous fins running from forehead to
nape. Contemplative serene expression.

SCHOLAR (research bonus, visible): faint glowing arcane glyphs
softly orbiting the forehead, an open holographic tome of glowing
star-charts hovering at chest height.

WEALTH (bc bonus, visible): robes of deep teal silk trimmed in
heavy gold thread and mother-of-pearl, a torc of gold and pearl
at the throat, gold rings on the long webbed fingers.

Backdrop: deep underwater cathedral light, faint bioluminescent
rim lighting from above, distant suggestion of coral arches in
the shadow.
```

**Must include:** the gold torc or jewelry, the gill slits, the floating glyphs or hologram.

**Must NOT include:** a fish tail (head-and-shoulders framing only), human-style ears, cartoon mermaid styling.

---

## Raas

- **Filename:** `raas.png`
- **In-code traits:** `fast_growth`, `fast_growth`, `weak_industry`
- **Lore one-liner:** "Hardy nomads — breed twice as fast, but indifferent labourers."
- **Visual cues to embed:** fertility / lineage (doubled), unrefined craft

**Subject block:**

```
Subject: A Raas nomad elder, weathered sun-darkened skin, lean
angular face, deep-set wary dark eyes, dark braided hair bound back
with a leather cord. Expression of a survivor who has crossed
deserts.

FERTILITY / LINEAGE (fast growth, doubled — make this PROMINENT):
elaborate strands of small bone-and-bead talismans hanging across
the chest, each bead obviously representing a generation — the
strands clearly long and numerous, layered. A swirling tattoo of
branching family-lineage glyphs across one temple, flowing down
across one cheek.

UNREFINED LABOUR (weak industry, visible): clothing of layered
wrap-cloth in tan and ochre, leather and bone ornaments, deliberately
NO fine metalwork anywhere — a simple chipped knife of bone at the
belt instead of any steel weapon.

Backdrop: a faint orange dust haze, distant silhouettes of moving
tribal banners.
```

**Must include:** the many bead/talisman strands, the lineage tattoo, leather-and-bone (not steel) gear.

**Must NOT include:** sleek armour, polished metal, modern firearms, refined uniforms.

---

## Trilarian

- **Filename:** `trilarian.png`
- **In-code traits:** `food_bonus`, `ship_attack`, `defiant`
- **Lore one-liner:** "Aquatic warriors — never accept landed rule."
- **Visual cues to embed:** aquatic warrior, defiance, agrarian

**Subject block:**

```
Subject: A Trilarian aquatic warrior, sleek streamlined head shaped
for swimming, deep blue and silver mottled skin with subtle scale
texture, vertically-slit pupils in pale green eyes, swept-back finned
crest, ridged collar-spines along the shoulders. Watery caustic
light rippling subtly across the skin.

WARRIOR (ship attack, visible): an ornate coral-and-pearl-plated
armoured harness across the chest, a slim trident or boarding-
harpoon held vertical at one shoulder, several faint old war scars
across the brow ridge.

DEFIANT (will not be ruled, visible): proud upright bearing, chin
lifted, fierce unwavering gaze, a broken shackle dangling from one
wrist — clearly kept as a symbol rather than discarded.

AGRARIAN (food bonus, subtle): a small cluster of kelp-fronds and
deep-water grain woven into the harness as a harvest charm.

Backdrop: dark abyssal blue with distant pale shafts of surface
light filtering down.
```

**Must include:** the broken shackle, the trident/harpoon, the gill slits or finned crest.

**Must NOT include:** a fish tail (head-and-shoulders only), cartoon mermaid styling, cowed or submissive expression.

---

# Optional: placeholder races

These three PNG filenames exist as 0-byte placeholders but have
**no race definition** in `ecs/races.py`. They will NOT appear in
the race picker unless someone first adds them to the `RACES` dict
in `ecs/races.py`. The portraits below are starter identities — if
you decide to add these as real races, send the desired trait picks
and they can be wired into the code.

---

## Cynoid (canine warriors)

- **Filename:** `cynoid.png`
- **Suggested traits:** `warlord`, `ship_attack`, `fast_growth`
- **Lore one-liner suggestion:** "Pack-hunting hound-folk — ferocious in combat, prolific in number."

**Subject block:**

```
Subject: A Cynoid pack-warrior, hound-faced humanoid with sharp
muzzle and erect pointed ears, dark grey fur with lighter throat
mark, intelligent loyal amber eyes, baring slight fangs in a
disciplined non-aggressive expression.

WARLORD (visible): scars across one side of the muzzle, a leather-
and-brass armoured collar at the throat, kill-tally notches braided
into the fur of one shoulder.

WARRIOR (ship attack, visible): an angular brass-trimmed pauldron
on one shoulder, a sidearm holstered visibly at the chest harness.

FERTILITY (fast growth, subtle): a many-stranded woven pack-cord
across the chest, each strand a remembered pup of the line.

Backdrop: a faint deep red sky and distant silhouettes of moving
pack-mates suggested in shadow.
```

---

## Eoladi (wind-spirit traders)

- **Filename:** `eoladi.png`
- **Suggested traits:** `bc_bonus`, `tolerant`, `slow_growth`
- **Lore one-liner suggestion:** "Ageless traders of the high winds — patient, wealthy, slow to multiply."

**Subject block:**

```
Subject: A tall ageless Eoladi merchant, ethereal humanoid with
fine pale lavender skin that almost seems translucent at the
edges, long flowing silver-white hair drifting in a permanent
unfelt breeze, large calm violet eyes, an expression of deep
patience.

WEALTH (bc bonus, visible): robes of layered silver and pale-gold
silk that drift weightlessly, a triple-stranded gold chain at the
throat, an ornate gold-and-amber clasp at the shoulder.

TOLERANT / ENDURING (tolerant, slow growth, visible): the subject
shown exposed and untroubled by a faintly visible cold vacuum-
like background, faint frost crystals catching the light on the
robe — clearly unbothered by environments that would harm softer
species. The face shows the calm of someone who has watched
centuries pass.

Backdrop: distant clouds of pale gold and silver suggesting the
upper atmosphere of a gas giant or stellar wind currents.
```

---

## Imsaeis (underground engineers)

- **Filename:** `imsaeis.png`
- **Suggested traits:** `subterranean`, `industry_bonus`, `research_bonus`
- **Lore one-liner suggestion:** "Tunnel-dwelling engineer-philosophers — they reshape worlds from within."

**Subject block:**

```
Subject: A compact stocky Imsaeis engineer, broad humanoid head
with thick grey-violet skin, deep-set quartz-grey eyes adapted to
low light, a small luminous bio-light gem set into the forehead
glowing softly.

SUBTERRANEAN (visible): faint glowing bioluminescent veins running
through the skin of the neck and temples (like ore veins in stone),
the lighting on the figure dim and from below as though lit by lava
or magma glow.

INDUSTRY (visible): heavy stocky build, calloused broad hands, a
mining-engineer's leather apron with brass tool-loops across the
chest, a small etched copper amulet shaped like a pickaxe at the
throat.

RESEARCH (visible): a small open mineral-codex tucked under one
arm, a single glowing engraved gemstone resting in the palm of one
hand at chest height — clearly being studied.

Backdrop: deep cavern dimness, the suggestion of carved-stone
arches and faint orange under-glow far in the background.
```

---

# After generating

1. Save each as `assets/races/<lowercase-name>.png` (1024×1024 PNG).
2. **Delete the existing 0-byte placeholder of the same name first.**
3. Confirm the engine sees the new portraits:
   ```
   python -c "from assets.loader import list_race_names; print(list_race_names())"
   ```
   The output should include the new race names. Before this change
   the list shows ~10 races; after it should show ~15.
4. Boot the game and visit the Empire Setup screen — the race grid
   should now show the new portraits in place of the slashed grey
   placeholder squares.
5. For each placeholder-only race you actually want in the game,
   the corresponding `RACES` entry must also be added to
   `ecs/races.py`.

---

# Quick checklist

- [ ] `humans.png` generated and dropped in
- [ ] `meklar.png` generated and dropped in
- [ ] `nommo.png` generated and dropped in
- [ ] `raas.png` generated and dropped in
- [ ] `trilarian.png` generated and dropped in
- [ ] (Optional) `cynoid.png` generated + RACES entry added to code
- [ ] (Optional) `eoladi.png` generated + RACES entry added to code
- [ ] (Optional) `imsaeis.png` generated + RACES entry added to code
- [ ] (Optional) `Alkari.png` renamed to lowercase `alkari.png`
- [ ] In-game verification on the Empire Setup screen

"""Golden tests for the economy numeric core.

These pin the exact per-planet output maths so future balance changes
are deliberate, not accidental. If a value changes here, it should be
because we *meant* to rebalance — the test failure is the signal.
"""
from ecs.components import Planet, Population, BuildState
from ecs.economy import (
    compute_max_population, default_assignment, normalize_assignment,
    planet_output,
)


def _planet(ptype="Terran", size="Medium", richness="Abundant",
            gravity="Normal", special=None):
    return Planet(id=1, planet_type=ptype, size=size, colonizable=True,
                  richness=richness, gravity=gravity, special=special or [])


def _pop(current, farmers=0, workers=0, scientists=0, mx=None):
    return Population(current=current, max=mx if mx is not None else current,
                      farmers=farmers, workers=workers, scientists=scientists)


# ---- compute_max_population -------------------------------------------

def test_max_pop_medium_terran():
    assert compute_max_population("Terran", "Medium") == 12


def test_max_pop_large_gaia():
    # 16 * 1.25 = 20
    assert compute_max_population("Gaia", "Large") == 20


def test_max_pop_medium_desert():
    # 12 * 0.5 = 6
    assert compute_max_population("Desert", "Medium") == 6


def test_max_pop_tiny_radiated_rounds():
    # 4 * 0.2 = 0.8 -> round -> 1
    assert compute_max_population("Radiated", "Tiny") == 1


def test_max_pop_gas_giant_uncolonizable():
    assert compute_max_population("Gas Giant", "Huge") == 0


# ---- default_assignment -----------------------------------------------

def test_default_assignment_terran():
    # food_per_farmer=2, current=5 -> ceil(5/2)=3 farmers, 2 workers
    assert default_assignment("Terran", 5) == (3, 2, 0)


def test_default_assignment_no_food_biome():
    # Barren grows no food -> everyone works
    assert default_assignment("Barren", 5) == (0, 5, 0)


def test_default_assignment_empty():
    assert default_assignment("Terran", 0) == (0, 0, 0)


# ---- normalize_assignment ---------------------------------------------

def test_normalize_fills_workers_when_short():
    pop = _pop(6, farmers=2, workers=1, scientists=0)  # sums to 3, need 6
    normalize_assignment(pop)
    assert (pop.farmers, pop.workers, pop.scientists) == (2, 4, 0)
    assert pop.farmers + pop.workers + pop.scientists == 6


def test_normalize_trims_excess_from_workers_first():
    pop = _pop(4, farmers=2, workers=3, scientists=2)  # sums to 7, need 4
    normalize_assignment(pop)
    assert pop.farmers + pop.workers + pop.scientists == 4
    # workers trimmed first (3->0 covers the excess of 3)
    assert pop.workers == 0
    assert pop.farmers == 2
    assert pop.scientists == 2


# ---- planet_output: base -----------------------------------------------

def test_output_uncolonized_is_zero():
    assert planet_output(_planet(), None) == (0, 0, 0, 0)
    assert planet_output(_planet(), _pop(0)) == (0, 0, 0, 0)


def test_output_medium_terran_baseline():
    # farmers 3 * food 2 = 6; workers 3 * industry 1 = 3; sci 0
    p = _planet()
    pop = _pop(6, farmers=3, workers=3, scientists=0)
    assert planet_output(p, pop) == (6, 3, 0, 0)


def test_output_scientists_produce_research():
    p = _planet()
    pop = _pop(4, farmers=2, workers=0, scientists=2)
    food, industry, research, bc = planet_output(p, pop)
    assert (food, industry, research, bc) == (4, 0, 2, 0)


# ---- planet_output: richness ------------------------------------------

def test_output_rich_planet_scales_industry():
    # Rich = 1.5x worker industry. 4 workers * 1 * 1.5 = 6
    p = _planet(richness="Rich")
    pop = _pop(4, workers=4)
    _f, industry, _r, _bc = planet_output(p, pop)
    assert industry == 6


def test_output_ultra_poor_halves_industry():
    # Ultra Poor = 0.5x. 4 workers * 1 * 0.5 = 2
    p = _planet(richness="Ultra Poor")
    pop = _pop(4, workers=4)
    _f, industry, _r, _bc = planet_output(p, pop)
    assert industry == 2


def test_output_richness_does_not_touch_food_or_research():
    p = _planet(richness="Ultra Rich")
    pop = _pop(3, farmers=1, workers=1, scientists=1)
    food, _industry, research, _bc = planet_output(p, pop)
    assert food == 2      # 1 farmer * 2, unaffected by richness
    assert research == 1  # 1 scientist * 1, unaffected by richness


# ---- planet_output: gravity -------------------------------------------

def test_output_heavy_gravity_penalises_all():
    # Heavy = 0.5x on food/industry/research.
    # farmers 4*2=8 ->4 ; workers 4*1=4 (abundant 1.0) ->*0.5=2 ; sci 0
    p = _planet(gravity="Heavy")
    pop = _pop(8, farmers=4, workers=4, scientists=0)
    food, industry, research, _bc = planet_output(p, pop)
    assert (food, industry, research) == (4, 2, 0)


def test_output_low_gravity_quarter_penalty():
    # Low = 0.75x. farmers 4*2=8 -> round(6.0)=6
    p = _planet(gravity="Low")
    pop = _pop(4, farmers=4)
    food, _industry, _research, _bc = planet_output(p, pop)
    assert food == 6

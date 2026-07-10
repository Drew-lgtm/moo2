"""Pytest bootstrap for the Master of Galaxy test suite.

Ensures the repo root is importable (so ``import ecs.*`` works no matter
where pytest is invoked from) and forces the SDL dummy video driver so
any transitive pygame import never tries to open a real window on CI or
a headless run.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

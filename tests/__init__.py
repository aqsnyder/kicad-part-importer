"""Tests for kicad-part-importer.

Run from the repository root with ``python -m pytest`` or
``python -m unittest discover -s tests -v``. The test modules import their
shared fixtures as ``libtest_helpers``; put this folder on sys.path so that
works however the suite is started (including a bare ``python -m unittest``).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

#!/usr/bin/env python3
"""Compatibility wrapper for the graph viewer entrypoint."""

from __future__ import annotations

import runpy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

if __name__ == "__main__":
    runpy.run_path(str(SCRIPTS_DIR / "run_graph_web.py"), run_name="__main__")

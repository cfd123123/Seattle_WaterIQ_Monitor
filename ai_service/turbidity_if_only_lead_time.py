#!/usr/bin/env python3
"""
CLI: IF-only lead-time tier-upgrade analysis on turbidity holdout.

Example::

    .venv/bin/python turbidity_if_only_lead_time.py \\
      --report-dir reports/turbidity_state/12117500_v2 \\
      --plot
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from models.turbidity_if_only_lead_time import main

if __name__ == "__main__":
    raise SystemExit(main())

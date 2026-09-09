from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.getLogger("plexvlc").setLevel(logging.CRITICAL)

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "helper"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(HELPER) not in sys.path:
    sys.path.insert(0, str(HELPER))

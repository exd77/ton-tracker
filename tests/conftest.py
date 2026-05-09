"""Shared fixtures and import bootstrap for the tracker test suite.

Adds the repo root to sys.path so `import tracker` works whether pytest is
invoked from the repo root or from inside tests/.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Config.from_env() requires these to be present; we use placeholder values
# so importing tracker for tests doesn't blow up.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "999999:TEST")
os.environ.setdefault("TELEGRAM_CHAT_ID", "0")

"""Persistent state: seen pool addresses and graduated memepad assets."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional


class State:
    def __init__(self, path: Path):
        self.path = path
        self.seen: set[str] = set()
        # Memepad assets we've already alerted as graduated. Stored alongside
        # `seen_pool_addresses` for backwards compatibility — old state files
        # without this key keep working.
        self.graduated: set[str] = set()
        self.last_checked_at: Optional[str] = None
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self.seen = set(data.get("seen_pool_addresses", []))
        self.graduated = set(data.get("graduated_assets", []))
        self.last_checked_at = data.get("last_checked_at")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "seen_pool_addresses": sorted(self.seen),
            "graduated_assets": sorted(self.graduated),
            "last_checked_at": datetime.now(UTC).isoformat(),
        }
        self.path.write_text(json.dumps(data, indent=2))

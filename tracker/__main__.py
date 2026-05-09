"""CLI entry point: ``python -m tracker``."""
from __future__ import annotations

import argparse
import json

from .bot import Tracker
from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Telegram bot: TON new token launch tracker (DeDust + STON.fi)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one polling tick then exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build first unseen alert and print it without sending to Telegram",
    )
    args = parser.parse_args()

    cfg = Config.from_env()
    tr = Tracker(cfg)

    if args.dry_run:
        pools = tr.fetch_pools()
        unseen = [p for p in pools if p.get("address") not in tr.state.seen]
        sample = unseen[0] if unseen else (pools[-1] if pools else None)
        if not sample:
            print("No pools returned by DeDust")
            return
        text, image, reply_markup = tr.build_message(sample)
        print("IMAGE:", image or "-")
        print(text)
        if reply_markup:
            print("KEYBOARD:", json.dumps(reply_markup, indent=2))
        return

    if args.once:
        sent = tr.tick()
        print(f"sent={sent}")
        return

    tr.run_forever()


if __name__ == "__main__":
    main()

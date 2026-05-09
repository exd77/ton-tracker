"""x1000 / DeDust coin enrichment + signal-badge helpers.

These helpers pluck volume/tx/tax/verification data out of the x1000 coin
list and format them for the alert template.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .fmt import format_usd


def coin_volume_24h(coin: Optional[dict[str, Any]]) -> Optional[str]:
    """Pull a sane 24h USD volume from x1000 coin item.

    The x1000 API returns volume as either a plain scalar or a nested
    dict like {buy_periods:{h24:..}, sell_periods:{h24:..}, total_periods:{h24:..}}.
    We try total_periods.h24 first, fall back to summed buy+sell, then
    flat h24, then the scalar form.
    """
    if not coin:
        return None
    v = coin.get("volume")
    if v is None:
        return None
    if isinstance(v, dict):
        total = v.get("total_periods")
        if isinstance(total, dict) and total.get("h24") is not None:
            return format_usd(total.get("h24"))
        buy = (v.get("buy_periods") or {}).get("h24") if isinstance(v.get("buy_periods"), dict) else None
        sell = (v.get("sell_periods") or {}).get("h24") if isinstance(v.get("sell_periods"), dict) else None
        if buy is not None or sell is not None:
            try:
                s = Decimal(str(buy or 0)) + Decimal(str(sell or 0))
                return format_usd(s)
            except (InvalidOperation, ValueError, TypeError):
                pass
        if v.get("h24") is not None:
            return format_usd(v.get("h24"))
        return None
    return format_usd(v)


def coin_tx_24h(coin: Optional[dict[str, Any]]) -> Optional[str]:
    """Format `Nbuy / Nsell` from x1000 coin transactions.{buy,sell}.h24."""
    if not coin:
        return None
    tx = coin.get("transactions")
    if not isinstance(tx, dict):
        return None
    buy = (tx.get("buy") or {}).get("h24") if isinstance(tx.get("buy"), dict) else None
    sell = (tx.get("sell") or {}).get("h24") if isinstance(tx.get("sell"), dict) else None
    if buy is None and sell is None:
        return None
    try:
        b = int(buy or 0)
        s = int(sell or 0)
    except (ValueError, TypeError):
        return None
    return f"{b} buy / {s} sell"


def format_tax(coin: Optional[dict[str, Any]]) -> Optional[str]:
    """Render `buy_tax`/`sell_tax` (percent ints) with a severity icon.

    None when both fields are missing — caller omits the line entirely.
    """
    if not coin:
        return None
    bt = coin.get("buy_tax")
    st = coin.get("sell_tax")
    if bt is None and st is None:
        return None
    try:
        b = int(bt or 0)
        s = int(st or 0)
    except (ValueError, TypeError):
        return None
    worst = max(b, s)
    if worst >= 25:
        icon = " 🚨"
    elif worst >= 10:
        icon = " ⚠️"
    elif worst > 0:
        icon = ""
    else:
        icon = " ✅"
    return f"{b}% / {s}%{icon}"


_VERIFICATION_LABELS = {
    0: ("Unverified", "❓"),
    1: ("Indexed", "📋"),
    2: ("Verified", "✅"),
    3: ("Whitelisted", "🛡️"),
}


def format_verification(coin: Optional[dict[str, Any]]) -> Optional[str]:
    if not coin:
        return None
    level = coin.get("verification_level")
    if level is None:
        return None
    try:
        n = int(level)
    except (ValueError, TypeError):
        return None
    label, icon = _VERIFICATION_LABELS.get(n, (f"Level {n}", "❓"))
    return f"{icon} {label}"


def deployer_token_count(items: Optional[list[dict[str, Any]]], author: str) -> int:
    """Count how many memepad tokens in `items` were deployed by `author`.

    Used to flag serial-farmer / dump-pattern wallets in the alert.
    """
    if not author or not items:
        return 0
    a = author.strip().lower()
    if not a:
        return 0
    n = 0
    for item in items:
        extra = item.get("memecoin_extra_details") if isinstance(item, dict) else None
        if not isinstance(extra, dict):
            continue
        candidate = (extra.get("author") or "").strip().lower()
        if candidate and candidate == a:
            n += 1
    return n


def find_x1000_coin_details(
    jetton_addr: str,
    details: dict[str, Any],
    items: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    metadata = (details or {}).get("metadata") or {}
    raw_addr = metadata.get("address") or ""
    raw_hash = raw_addr.split(":", 1)[1].lower() if ":" in raw_addr else ""
    candidates = {(jetton_addr or "").lower(), raw_addr.lower(), raw_hash}
    candidates.discard("")
    if not candidates:
        return None
    for item in items or []:
        asset = str(item.get("asset", "")).lower()
        if any(c and c in asset for c in candidates):
            return item
    return None

"""Pure formatting and conversion helpers — no network, no side effects."""
from __future__ import annotations

import html
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


def ton_from_nano(value: Any) -> str:
    try:
        d = Decimal(str(value)) / Decimal("1000000000")
        return f"{d:,.4f}".rstrip("0").rstrip(".")
    except (InvalidOperation, ValueError):
        return "?"


def human_amount(raw: Any, decimals: int | str | None = 9) -> str:
    try:
        dec = int(decimals if decimals is not None else 9)
        d = Decimal(str(raw)) / (Decimal(10) ** dec)
        if d == 0:
            return "0"
        if d < Decimal("0.0001"):
            return f"{d:.8f}".rstrip("0").rstrip(".")
        return f"{d:,.4f}".rstrip("0").rstrip(".")
    except Exception:
        return str(raw)


def h(value: Any) -> str:
    return html.escape(str(value or "-"), quote=False)


def h_attr(value: Any) -> str:
    """HTML-escape for attribute values (href). Quotes get escaped."""
    return html.escape(str(value or ""), quote=True)


def nano_to_ton_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)) / Decimal("1000000000")
    except (InvalidOperation, ValueError, TypeError):
        return None


def format_ton_short(value: Optional[Decimal]) -> str:
    if value is None:
        return "?"
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return "?"
    if d >= Decimal(1000):
        return f"{d:.0f}"
    if d >= Decimal(1):
        s = f"{d:.2f}"
        if s.endswith(".00"):
            s = s[:-3]
        return s
    if d == 0:
        return "0"
    return f"{float(d):.4f}".rstrip("0").rstrip(".")


def format_usd(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, (dict | list | tuple | set)):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d == 0:
        return "$0"
    sign = "-" if d < 0 else ""
    d = abs(d)
    if d >= Decimal(1_000_000):
        return f"{sign}${d/Decimal(1_000_000):,.2f}M"
    if d >= Decimal(1_000):
        return f"{sign}${d/Decimal(1_000):,.2f}K"
    if d >= Decimal(1):
        s = f"{d:,.2f}"
        if s.endswith(".00"):
            s = s[:-3]
        return f"{sign}${s}"
    if d >= Decimal("0.01"):
        return f"{sign}${d:,.4f}"
    return f"{sign}${float(d):.6f}"


def shorten_address(address: str, prefix: int = 6, suffix: int = 4) -> str:
    if not address:
        return "-"
    addr = str(address)
    if len(addr) <= prefix + suffix + 3:
        return addr
    return f"{addr[:prefix]}...{addr[-suffix:]}"


def format_age(created_at: Any) -> str:
    if created_at is None or created_at == "":
        return "Unknown"
    try:
        if isinstance(created_at, (int | float)):
            ts = float(created_at)
        else:
            s = str(created_at).strip()
            try:
                ts = float(s)
            except ValueError:
                iso = s.replace("Z", "+00:00")
                ts = datetime.fromisoformat(iso).timestamp()
        if ts > 1e12:
            ts = ts / 1000.0
        now = datetime.now(UTC).timestamp()
        delta = max(0.0, now - ts)
    except Exception:
        return "Unknown"
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        h_v = int(delta // 3600)
        m_v = int((delta % 3600) // 60)
        return f"{h_v}h {m_v}m"
    d_v = int(delta // 86400)
    h_v = int((delta % 86400) // 3600)
    return f"{d_v}d {h_v}h"


def build_progress_bar(percent: Optional[Decimal], length: int = 10) -> str:
    length = max(4, int(length))
    if percent is None:
        return "▱" * length + " Unknown"
    try:
        p = Decimal(percent)
    except (InvalidOperation, ValueError, TypeError):
        return "▱" * length + " Unknown"
    if p < 0:
        p = Decimal(0)
    if p > 100:
        p = Decimal(100)
    filled = int((p / Decimal(100)) * Decimal(length))
    if p > 0 and filled == 0:
        filled = 1
    if filled > length:
        filled = length
    bar = "▰" * filled + "▱" * (length - filled)
    pct_str = f"{float(p):.2f}%" if p < Decimal(10) else f"{float(p):.1f}%"
    return f"{bar} {pct_str}"


def bonding_stats(extra: dict[str, Any]) -> dict[str, Any]:
    extra = extra or {}
    collected = nano_to_ton_decimal(extra.get("curve_ton_collected"))
    max_v = nano_to_ton_decimal(extra.get("curve_ton_max"))
    percent: Optional[Decimal] = None
    if collected is not None and max_v is not None and max_v > 0:
        percent = (collected / max_v) * Decimal(100)
        if percent < 0:
            percent = Decimal(0)
        if percent > Decimal(100):
            percent = Decimal(100)
    return {"collected": collected, "max": max_v, "percent": percent}

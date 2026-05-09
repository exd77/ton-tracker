"""Pool/asset helpers and STON.fi pool normalizer."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional


def asset_symbol(asset: dict[str, Any]) -> str:
    md = asset.get("metadata") or {}
    return md.get("symbol") or asset.get("symbol") or ("TON" if asset.get("type") == "native" else "JETTON")


def asset_name(asset: dict[str, Any]) -> str:
    md = asset.get("metadata") or {}
    return md.get("name") or asset.get("name") or asset_symbol(asset)


def asset_image(asset: dict[str, Any]) -> Optional[str]:
    md = asset.get("metadata") or {}
    img = md.get("image") or asset.get("image")
    if not img:
        return None
    if img.startswith("http://") or img.startswith("https://"):
        return img
    return f"https://assets.dedust.io/images/{img}"


def is_native_ton(asset: dict[str, Any]) -> bool:
    return asset.get("type") == "native" or asset_symbol(asset).upper() == "TON"


def pick_jetton(pool: dict[str, Any]) -> Optional[dict[str, Any]]:
    for asset in pool.get("assets", []):
        if asset.get("type") == "jetton" and asset.get("address"):
            return asset
    return None


def pool_has_ton(pool: dict[str, Any]) -> bool:
    return any(is_native_ton(a) for a in pool.get("assets", []))


def pool_lt(pool: dict[str, Any]) -> int:
    try:
        return int(pool.get("lt") or 0)
    except ValueError:
        return 0


# STON.fi encodes native TON as a zero-padded jetton-master address.
# https://docs.ston.fi/docs/developer-section/api-reference-v2 lists this as
# the "pTON v1" address used in router pools.
STONFI_NATIVE_TON_ADDR = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"


def normalize_stonfi_pool(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a STON.fi /v1/pools entry into the DeDust-compatible internal
    schema used by the rest of the tracker.

    Returns an empty dict when the pool is deprecated or unparseable, so
    callers can skip it cheaply.
    """
    if not isinstance(raw, dict) or raw.get("deprecated"):
        return {}
    addr = raw.get("address")
    if not addr:
        return {}
    t0 = (raw.get("token0_address") or "").strip()
    t1 = (raw.get("token1_address") or "").strip()
    r0 = raw.get("reserve0", "0")
    r1 = raw.get("reserve1", "0")

    def _asset(addr_str: str) -> dict[str, Any]:
        if not addr_str or addr_str == STONFI_NATIVE_TON_ADDR:
            return {"type": "native"}
        return {"type": "jetton", "address": addr_str, "metadata": {}}

    # lp_fee + protocol_fee are basis points (1bp = 0.01%). Combine for total.
    try:
        lp = Decimal(str(raw.get("lp_fee") or 0))
        proto = Decimal(str(raw.get("protocol_fee") or 0))
        fee_pct: Optional[Decimal] = (lp + proto) / Decimal(100)
    except (InvalidOperation, ValueError, TypeError):
        fee_pct = None
    fee_str = "?"
    if fee_pct is not None:
        s = f"{fee_pct:.2f}"
        if s.endswith("0") and "." in s:
            s = s.rstrip("0").rstrip(".")
        fee_str = s

    return {
        "address": addr,
        "type": "stonfi",
        "_source": "stonfi",
        "tradeFee": fee_str,
        "lt": 0,
        "assets": [_asset(t0), _asset(t1)],
        "reserves": [str(r0), str(r1)],
    }


def pool_source(pool: dict[str, Any]) -> str:
    """Return a stable label for the pool source ('dedust' / 'stonfi')."""
    src = pool.get("_source")
    if src:
        return str(src)
    return "stonfi" if pool.get("type") == "stonfi" else "dedust"


def pool_ton_reserve(pool: dict[str, Any]) -> Decimal:
    """Return the native-TON side reserve of a pool, in TON (not nano)."""
    reserves = pool.get("reserves", [])
    for i, asset in enumerate(pool.get("assets", [])):
        if is_native_ton(asset) and i < len(reserves):
            try:
                return Decimal(str(reserves[i])) / Decimal("1000000000")
            except (InvalidOperation, ValueError, TypeError):
                return Decimal(0)
    return Decimal(0)

"""TON DeDust + STON.fi new-launch Telegram tracker.

This package was split out of a single ``tracker.py`` module; the public
surface is preserved through these re-exports so that ``import tracker``
keeps working unchanged.
"""
from __future__ import annotations

import logging
import os

from .bot import Tracker
from .config import Config
from .enrichment import (
    coin_tx_24h,
    coin_volume_24h,
    deployer_token_count,
    find_x1000_coin_details,
    format_tax,
    format_verification,
)
from .fmt import (
    bonding_stats,
    build_progress_bar,
    format_age,
    format_ton_short,
    format_usd,
    h,
    h_attr,
    human_amount,
    nano_to_ton_decimal,
    shorten_address,
    ton_from_nano,
)
from .http import Http, TTLCache
from .metrics import Metrics
from .pool import (
    STONFI_NATIVE_TON_ADDR,
    asset_image,
    asset_name,
    asset_symbol,
    is_native_ton,
    normalize_stonfi_pool,
    pick_jetton,
    pool_has_ton,
    pool_lt,
    pool_source,
    pool_ton_reserve,
)
from .social import (
    URL_RE,
    SocialLink,
    extract_social_links,
    extract_urls_from_text,
    normalize_social_url,
)
from .state import State

# Logging setup runs once on import. Apps that need a different config
# can call ``logging.basicConfig`` themselves before importing tracker.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

__all__ = [
    "Config",
    "Http",
    "Metrics",
    "STONFI_NATIVE_TON_ADDR",
    "SocialLink",
    "State",
    "TTLCache",
    "Tracker",
    "URL_RE",
    "asset_image",
    "asset_name",
    "asset_symbol",
    "bonding_stats",
    "build_progress_bar",
    "coin_tx_24h",
    "coin_volume_24h",
    "deployer_token_count",
    "extract_social_links",
    "extract_urls_from_text",
    "find_x1000_coin_details",
    "format_age",
    "format_tax",
    "format_ton_short",
    "format_usd",
    "format_verification",
    "h",
    "h_attr",
    "human_amount",
    "is_native_ton",
    "nano_to_ton_decimal",
    "normalize_social_url",
    "normalize_stonfi_pool",
    "pick_jetton",
    "pool_has_ton",
    "pool_lt",
    "pool_source",
    "pool_ton_reserve",
    "shorten_address",
    "ton_from_nano",
]

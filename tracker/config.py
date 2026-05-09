"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def _safe_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


@dataclass
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    poll_interval_seconds: int = 60
    skip_existing_on_first_run: bool = True
    require_native_ton: bool = True
    dedust_pools_url: str = "https://api.dedust.io/v2/pools"
    tonapi_base_url: str = "https://tonapi.io/v2"
    tonapi_key: str = ""
    x1000_enabled: bool = True
    x1000_api_url: str = "https://mainnet.api.dedust.io/v4/api/coins"
    x1000_base_url: str = "https://x1000.finance"
    x1000_token_route_pattern: str = ""
    x1000_cookie: str = ""
    # STON.fi (second-largest TON DEX). Pool source is opt-in; same dedup
    # state is shared with DeDust because pool addresses don't collide.
    stonfi_enabled: bool = True
    stonfi_pools_url: str = "https://api.ston.fi/v1/pools"
    progress_bar_length: int = 10
    description_max_chars: int = 300
    max_social_links: int = 5
    # Min TON liquidity filter for pool to qualify as a launch (0 = disabled).
    min_ton_reserves: Decimal = Decimal(0)
    # Bonded curve % at which a memepad token is treated as graduated and
    # gets its own alert. Cap of 100 enforced inside the helper.
    graduation_threshold_pct: Decimal = Decimal("99")
    # Decorate the Deployer block with a serial-farmer warning when the
    # author has launched >= this many tokens in the cached x1000 list.
    dev_cluster_warn_threshold: int = 3
    # Render Telegram inline-keyboard buttons for chart / pool / explorer
    # links instead of inline HTML <a> links inside the message body.
    inline_buttons: bool = True
    # In-memory cache TTLs (seconds). Jetton metadata is quasi-static;
    # balance changes often but intra-tick reuse is still worthwhile;
    # x1000 list is shared across all pools in a tick.
    tonapi_cache_ttl: int = 3600
    balance_cache_ttl: int = 60
    x1000_cache_ttl: int = 30
    # HTTP retry policy (429/5xx). total=0 disables retries.
    http_retries: int = 3
    http_backoff_factor: float = 1.0
    state_file: Path = Path("./state/seen_pools.json")
    # Prometheus metrics HTTP server port. 0 = disabled.
    metrics_port: int = 0

    @classmethod
    def from_env(cls) -> Config:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not token or token.startswith("123456"):
            raise SystemExit("TELEGRAM_BOT_TOKEN belum di-set. Copy .env.example ke .env lalu isi token BotFather.")
        if not chat_id:
            raise SystemExit("TELEGRAM_CHAT_ID belum di-set.")

        return cls(
            telegram_bot_token=token,
            telegram_chat_id=chat_id,
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
            skip_existing_on_first_run=os.getenv("SKIP_EXISTING_ON_FIRST_RUN", "true").lower() == "true",
            require_native_ton=os.getenv("REQUIRE_NATIVE_TON", "true").lower() == "true",
            dedust_pools_url=os.getenv("DEDUST_POOLS_URL", "https://api.dedust.io/v2/pools"),
            tonapi_base_url=os.getenv("TONAPI_BASE_URL", "https://tonapi.io/v2").rstrip("/"),
            tonapi_key=os.getenv("TONAPI_KEY", "").strip(),
            x1000_enabled=os.getenv("X1000_ENABLED", "true").lower() == "true",
            x1000_api_url=os.getenv("X1000_API_URL", "https://mainnet.api.dedust.io/v4/api/coins"),
            x1000_base_url=os.getenv("X1000_BASE_URL", "https://x1000.finance").rstrip("/"),
            x1000_token_route_pattern=os.getenv("X1000_TOKEN_ROUTE_PATTERN", "").strip(),
            x1000_cookie=os.getenv("X1000_COOKIE", "").strip(),
            stonfi_enabled=os.getenv("STONFI_ENABLED", "true").lower() == "true",
            stonfi_pools_url=os.getenv("STONFI_POOLS_URL", "https://api.ston.fi/v1/pools"),
            progress_bar_length=int(os.getenv("PROGRESS_BAR_LENGTH", "10")),
            description_max_chars=int(os.getenv("DESCRIPTION_MAX_CHARS", "300")),
            max_social_links=int(os.getenv("MAX_SOCIAL_LINKS", "5")),
            min_ton_reserves=_safe_decimal(os.getenv("MIN_TON_RESERVES", "0")),
            graduation_threshold_pct=_safe_decimal(os.getenv("GRADUATION_THRESHOLD_PCT", "99")),
            dev_cluster_warn_threshold=int(os.getenv("DEV_CLUSTER_WARN_THRESHOLD", "3")),
            inline_buttons=os.getenv("INLINE_BUTTONS", "true").lower() == "true",
            tonapi_cache_ttl=int(os.getenv("TONAPI_CACHE_TTL_SECONDS", "3600")),
            balance_cache_ttl=int(os.getenv("BALANCE_CACHE_TTL_SECONDS", "60")),
            x1000_cache_ttl=int(os.getenv("X1000_CACHE_TTL_SECONDS", "30")),
            http_retries=int(os.getenv("HTTP_RETRIES", "3")),
            http_backoff_factor=float(os.getenv("HTTP_BACKOFF_FACTOR", "1.0")),
            state_file=Path(os.getenv("STATE_FILE", "./state/seen_pools.json")),
            metrics_port=int(os.getenv("METRICS_PORT", "0")),
        )

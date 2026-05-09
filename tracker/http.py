"""HTTP client with retry logic and a lightweight TTL cache."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Config

log = logging.getLogger("ton-launch-tracker")


class TTLCache:
    """Tiny in-process cache with per-entry TTL.

    Designed for idempotent read-through caching of TonAPI and x1000
    responses so that bursts of new-pool discoveries don't fan out into
    duplicate network hits.
    """

    __slots__ = ("ttl", "_store")

    def __init__(self, ttl_seconds: float):
        self.ttl = float(ttl_seconds)
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        rec = self._store.get(key)
        if not rec:
            return None
        ts, val = rec
        if (time.time() - ts) > self.ttl:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


def _build_retry(cfg: Config) -> Retry:
    # Retry on 429 + common 5xx. Honor Retry-After if servers provide it.
    kwargs: dict[str, Any] = {
        "total": max(0, int(cfg.http_retries)),
        "backoff_factor": float(cfg.http_backoff_factor),
        "status_forcelist": (429, 500, 502, 503, 504),
        "respect_retry_after_header": True,
        "raise_on_status": False,
    }
    # urllib3 ≥1.26 uses allowed_methods; older versions used method_whitelist.
    try:
        return Retry(allowed_methods=frozenset(["GET", "POST"]), **kwargs)
    except TypeError:
        return Retry(  # type: ignore[call-arg]
            method_whitelist=frozenset(["GET", "POST"]), **kwargs
        )


class Http:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ton-launch-tracker/1.0"})
        if cfg.tonapi_key:
            self.session.headers.update({"Authorization": f"Bearer {cfg.tonapi_key}"})
        adapter = HTTPAdapter(max_retries=_build_retry(cfg))
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_json(
        self,
        url: str,
        *,
        timeout: int = 25,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        r = self.session.get(url, params=params, timeout=timeout, headers=headers)
        r.raise_for_status()
        return r.json()

    def post_telegram(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/{method}"
        r = self.session.post(url, data=payload, timeout=30)
        if not r.ok:
            log.warning("Telegram %s failed: %s %s", method, r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()

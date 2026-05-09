"""Tracker orchestrator: fetches pools, builds alert messages, dispatches."""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Any, Optional

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
    ton_from_nano,
)
from .http import Http, TTLCache
from .metrics import Metrics, start_metrics_server
from .pool import (
    asset_image,
    asset_name,
    asset_symbol,
    normalize_stonfi_pool,
    pick_jetton,
    pool_has_ton,
    pool_lt,
    pool_source,
    pool_ton_reserve,
)
from .social import extract_social_links
from .state import State

log = logging.getLogger("ton-launch-tracker")


class Tracker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = Http(cfg)
        self.state = State(cfg.state_file)
        self._jetton_cache = TTLCache(cfg.tonapi_cache_ttl)
        self._balance_cache = TTLCache(cfg.balance_cache_ttl)
        # x1000 is a full-list cache (not per-jetton): all pools in one tick
        # reuse the same snapshot. Value is the `items` list.
        self._x1000_items: Optional[list[dict[str, Any]]] = None
        self._x1000_items_ts: float = 0.0
        # Metrics: always present; the underlying counters are no-ops when
        # prometheus_client is missing or metrics_port == 0.
        self.metrics = Metrics()
        self._metrics_server = start_metrics_server(
            self.metrics, cfg.metrics_port, cfg.poll_interval_seconds
        )

    def fetch_pools(self) -> list[dict[str, Any]]:
        pools: list[dict[str, Any]] = []

        # DeDust source: failure here is fatal — primary feed.
        dedust = self.http.get_json(self.cfg.dedust_pools_url)
        if not isinstance(dedust, list):
            raise RuntimeError(f"Unexpected DeDust response: {type(dedust)}")
        for p in dedust:
            if pick_jetton(p):
                p.setdefault("_source", "dedust")
                pools.append(p)

        # STON.fi source: best-effort, never blocks DeDust alerts.
        if self.cfg.stonfi_enabled:
            try:
                stonfi = self.http.get_json(self.cfg.stonfi_pools_url)
            except Exception as e:
                log.warning("STON.fi pools fetch failed: %s", e)
                stonfi = None
            if isinstance(stonfi, dict):
                for raw in stonfi.get("pool_list", []) or []:
                    np = normalize_stonfi_pool(raw)
                    if np and pick_jetton(np):
                        pools.append(np)

        if self.cfg.require_native_ton:
            pools = [p for p in pools if pool_has_ton(p)]
        if self.cfg.min_ton_reserves > 0:
            pools = [p for p in pools if pool_ton_reserve(p) >= self.cfg.min_ton_reserves]
        return sorted(pools, key=pool_lt)

    def tonapi(self, path: str) -> Any:
        return self.http.get_json(f"{self.cfg.tonapi_base_url}{path}")

    def jetton_details(self, address: str) -> dict[str, Any]:
        if not address:
            return {}
        cached = self._jetton_cache.get(address)
        if cached is not None:
            return cached
        try:
            data = self.tonapi(f"/jettons/{address}")
        except Exception as e:
            log.warning("TonAPI jetton lookup failed for %s: %s", address, e)
            return {}
        # Only cache a non-empty successful response; transient {} would
        # otherwise poison the cache for the full TTL.
        if isinstance(data, dict) and data:
            self._jetton_cache.set(address, data)
        return data if isinstance(data, dict) else {}

    def _fetch_x1000_items(self) -> list[dict[str, Any]]:
        """Return cached x1000/DeDust coins items, refreshing if stale.

        On failure, keep the previous snapshot (best-effort) so a transient
        outage doesn't erase enrichment mid-tick.
        """
        if not self.cfg.x1000_enabled:
            return []
        now = time.time()
        if (
            self._x1000_items is not None
            and (now - self._x1000_items_ts) < self.cfg.x1000_cache_ttl
        ):
            return self._x1000_items
        params = {
            "memecoin_extra_details": "true",
            "offset": 0,
            "limit": 100,
            "sort_by": "age",
            "sort_direction": "desc",
            "sort_period": "24h",
            "filter_period": "24h",
            "include_without_price": "true",
            "skip_total_count": "true",
            "compact": "false",
        }
        headers = {"Cookie": self.cfg.x1000_cookie} if self.cfg.x1000_cookie else None
        try:
            data = self.http.get_json(self.cfg.x1000_api_url, params=params, headers=headers)
        except Exception as e:
            log.warning("x1000/DeDust coins fetch failed: %s", e)
            return self._x1000_items or []
        items = data.get("items", []) if isinstance(data, dict) else []
        self._x1000_items = items
        self._x1000_items_ts = now
        return items

    def x1000_coin_for(self, jetton_addr: str, details: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Return the full DeDust/x1000 Memepad coin item for a jetton when available.

        Uses a single cached fetch of the top-100 memepad list per
        X1000_CACHE_TTL_SECONDS so N pools in a tick share 1 HTTP call.
        """
        if not self.cfg.x1000_enabled or not jetton_addr:
            return None
        items = self._fetch_x1000_items()
        return find_x1000_coin_details(jetton_addr, details, items)

    def build_action_keyboard(
        self,
        *,
        chart_url: str,
        pool_addr: str,
        jetton_addr: str,
        source: str,
    ) -> Optional[dict[str, Any]]:
        """Construct a Telegram inline_keyboard for the alert action buttons.

        Returns None when inline buttons are disabled in config so callers
        fall back to the HTML link footer inside the message body.
        """
        if not self.cfg.inline_buttons:
            return None
        rows: list[list[dict[str, str]]] = []
        if chart_url:
            rows.append([{"text": "🟧 x1000 Chart", "url": chart_url}])
        secondary: list[dict[str, str]] = []
        if pool_addr:
            if source == "stonfi":
                secondary.append(
                    {"text": "🔎 STON.fi", "url": f"https://app.ston.fi/pools/{pool_addr}"}
                )
            else:
                secondary.append(
                    {"text": "🔎 DeDust", "url": f"https://dedust.io/pools/{pool_addr}"}
                )
        if jetton_addr:
            secondary.append(
                {"text": "🧭 Tonviewer", "url": f"https://tonviewer.com/{jetton_addr}"}
            )
        if secondary:
            rows.append(secondary)
        return {"inline_keyboard": rows} if rows else None

    def build_x1000_link(self, jetton_addr: str, x1000_asset: Optional[str]) -> str:
        """Build a chart URL on x1000 terminal. Falls back to base URL if no
        token route pattern is configured (or formatting fails).

        X1000_TOKEN_ROUTE_PATTERN supports placeholders: {asset}, {address},
        {jetton_addr}, {jetton_address}. Pattern can be a relative path
        (joined to base) or absolute URL.
        """
        base = (self.cfg.x1000_base_url or "https://x1000.finance").rstrip("/")
        pattern = self.cfg.x1000_token_route_pattern
        if pattern and (jetton_addr or x1000_asset):
            try:
                url = pattern.format(
                    asset=(x1000_asset or jetton_addr or ""),
                    address=(jetton_addr or x1000_asset or ""),
                    jetton_addr=(jetton_addr or x1000_asset or ""),
                    jetton_address=(jetton_addr or x1000_asset or ""),
                )
                if url.startswith(("http://", "https://")):
                    return url
                if url.startswith("/"):
                    return base + url
                return f"{base}/{url}"
            except Exception as e:
                log.warning("X1000_TOKEN_ROUTE_PATTERN format failed: %s", e)
        return base + "/"

    def account_balance_ton(self, address: str) -> Optional[str]:
        if not address or address.endswith(":" + "0" * 64):
            return None
        cached = self._balance_cache.get(address)
        if cached is not None:
            return cached
        try:
            data = self.tonapi(f"/blockchain/accounts/{address}")
            result = ton_from_nano(data.get("balance"))
        except Exception as e:
            log.warning("TonAPI account lookup failed for %s: %s", address, e)
            return None
        self._balance_cache.set(address, result)
        return result

    def pool_reserve_line(self, pool: dict[str, Any], metadata_by_address: Optional[dict[str, dict[str, Any]]] = None) -> str:
        metadata_by_address = metadata_by_address or {}
        assets = pool.get("assets", [])
        reserves = pool.get("reserves", [])
        parts: list[str] = []
        for i, asset in enumerate(assets):
            raw = reserves[i] if i < len(reserves) else "0"
            md = dict(asset.get("metadata") or {})
            if asset.get("address") in metadata_by_address:
                md.update(metadata_by_address[asset.get("address")] or {})
            sym = md.get("symbol") or asset_symbol(asset)
            parts.append(f"{human_amount(raw, md.get('decimals', 9))} {sym}")
        return " / ".join(parts) if parts else "-"

    def build_message(
        self, pool: dict[str, Any]
    ) -> tuple[str, Optional[str], Optional[dict[str, Any]]]:
        jetton_asset = pick_jetton(pool) or {}
        jetton_addr = jetton_asset.get("address", "") or ""
        details = self.jetton_details(jetton_addr) if jetton_addr else {}
        metadata = details.get("metadata") or jetton_asset.get("metadata") or {}

        # Single x1000 fetch reused across all enrichment fields.
        x1000_coin = self.x1000_coin_for(jetton_addr, details) if jetton_addr else None
        x1000_meta = (x1000_coin or {}).get("metadata") or {}
        x1000_extra = (x1000_coin or {}).get("memecoin_extra_details") or {}
        x1000_asset = (x1000_coin or {}).get("asset") if x1000_coin else None

        # Identity
        name = (
            x1000_meta.get("name")
            or metadata.get("name")
            or asset_name(jetton_asset)
        )
        symbol = (
            x1000_meta.get("ticker")
            or x1000_meta.get("symbol")
            or metadata.get("symbol")
            or asset_symbol(jetton_asset)
        )
        image = (
            x1000_meta.get("image_url")
            or details.get("preview")
            or metadata.get("image")
            or asset_image(jetton_asset)
        )

        # Description (HTML-escape, trim to configured max length)
        description = (
            x1000_meta.get("description")
            or metadata.get("description")
            or ""
        )
        description = str(description or "").strip()
        desc_max = max(50, int(self.cfg.description_max_chars))
        if len(description) > desc_max:
            description = description[:desc_max].rstrip() + "..."

        # Socials (defensive walk over multiple sources + URLs in description)
        socials = extract_social_links(
            x1000_coin or {},
            x1000_meta,
            metadata,
            description_text=description
                or x1000_meta.get("description")
                or metadata.get("description"),
            max_count=int(self.cfg.max_social_links),
        )

        # Deployer
        admin = details.get("admin") or {}
        x1000_author = x1000_extra.get("author")
        deployer_addr = x1000_author or admin.get("address") or ""
        is_zero = bool(deployer_addr) and deployer_addr.endswith(":" + "0" * 64)
        deployer_balance = (
            self.account_balance_ton(deployer_addr)
            if deployer_addr and not is_zero
            else None
        )
        # How many other tokens did this wallet deploy in the cached x1000
        # window? High number = serial farmer / dump pattern.
        deployer_other_tokens = max(
            0,
            deployer_token_count(self._x1000_items or [], deployer_addr) - 1,
        ) if deployer_addr and not is_zero else 0

        # Bonding curve
        bond = bonding_stats(x1000_extra)
        bond_collected: Optional[Decimal] = bond["collected"]
        bond_max: Optional[Decimal] = bond["max"]
        bond_pct: Optional[Decimal] = bond["percent"]
        bar = build_progress_bar(bond_pct, length=int(self.cfg.progress_bar_length))

        # Stats
        holders = x1000_coin.get("holders") if x1000_coin else None
        age_str = format_age(x1000_coin.get("created_at") if x1000_coin else None)
        market_cap = format_usd(x1000_coin.get("market_cap") if x1000_coin else None)
        volume = coin_volume_24h(x1000_coin)
        tx_24h = coin_tx_24h(x1000_coin)

        pool_addr = pool.get("address", "") or ""
        chart_url = self.build_x1000_link(
            jetton_addr, str(x1000_asset) if x1000_asset else None
        )

        # ---------- Compose message ----------
        lines: list[str] = []

        # Header
        lines.append(f"<b>${h(symbol)} just launched on TON</b>")
        lines.append("")
        lines.append(f"<b>{h(name)}</b>")
        if jetton_addr:
            lines.append(f"<code>{h(jetton_addr)}</code>")

        # Description
        if description:
            lines.append("")
            lines.append("📖 <b>Description</b>")
            for ln in description.splitlines() or [description]:
                ln = ln.strip()
                if ln:
                    lines.append(f"┃ {h(ln)}")

        # Socials
        lines.append("")
        lines.append("🎒 <b>Socials</b>")
        if socials:
            for i, s in enumerate(socials):
                connector = "┗" if i == len(socials) - 1 else "┣"
                lines.append(
                    f'{connector} {s.icon} <a href="{h_attr(s.url)}">{h(s.label)}</a>'
                )
        else:
            lines.append("┗ <code>Not found</code>")

        # Deployer
        lines.append("")
        lines.append("👤 <b>Deployer</b>")
        if deployer_addr and not is_zero:
            wallet_short = self._shorten(deployer_addr)
            balance_str = (
                f"{deployer_balance} TON" if deployer_balance else "Unknown"
            )
            deploy_amount = (
                f"{format_ton_short(bond_collected)} TON"
                if bond_collected is not None
                else "Unknown"
            )
            cluster_warn = (
                " ⚠️"
                if deployer_other_tokens >= int(self.cfg.dev_cluster_warn_threshold)
                else ""
            )
            lines.append(f"┣ Wallet: <code>{h(wallet_short)}</code>")
            lines.append(f"┣ Full: <code>{h(deployer_addr)}</code>")
            lines.append(f"┣ Balance: <code>{h(balance_str)}</code>")
            lines.append(f"┣ Deploy Amount: <code>{h(deploy_amount)}</code>")
            if deployer_other_tokens > 0:
                lines.append(
                    f"┣ Other tokens 24h: <code>{deployer_other_tokens}{cluster_warn}</code>"
                )
            lines.append("┗ Dev Buy: <code>Unknown</code>")
        else:
            lines.append("┗ <code>Revoked / zero address / unknown</code>")

        # Launch Stats
        stats_rows: list[tuple[str, str]] = []
        if bond_collected is not None and bond_max is not None:
            stats_rows.append(
                (
                    "Raised",
                    f"{format_ton_short(bond_collected)} / "
                    f"{format_ton_short(bond_max)} TON",
                )
            )
        if bond_pct is not None:
            pct_str = (
                f"{float(bond_pct):.2f}%"
                if bond_pct < Decimal(10)
                else f"{float(bond_pct):.1f}%"
            )
            stats_rows.append(("Bonded", pct_str))
        if holders is not None:
            stats_rows.append(("Holders", str(holders)))
        if age_str and age_str != "Unknown":
            stats_rows.append(("Age", age_str))
        if market_cap:
            stats_rows.append(("Market Cap", market_cap))
        if volume:
            stats_rows.append(("Volume 24h", volume))
        if tx_24h:
            stats_rows.append(("Tx 24h", tx_24h))
        tax_str = format_tax(x1000_coin)
        if tax_str:
            stats_rows.append(("Tax (buy/sell)", tax_str))
        verif = format_verification(x1000_coin)
        if verif:
            stats_rows.append(("Status", verif))

        if not stats_rows:
            metadata_by_address = {jetton_addr: metadata} if jetton_addr else {}
            reserves = self.pool_reserve_line(pool, metadata_by_address)
            stats_rows.append(("Reserves", reserves))
            trade_fee = pool.get("tradeFee")
            if trade_fee is not None:
                stats_rows.append(("Fee", f"{trade_fee}%"))

        lines.append("")
        lines.append("📊 <b>Launch Stats</b>")
        for i, (k, v) in enumerate(stats_rows):
            connector = "┗" if i == len(stats_rows) - 1 else "┣"
            lines.append(f"{connector} {h(k)}: <code>{h(v)}</code>")

        # Progress bar (always show; shows ▱… Unknown when no curve data)
        lines.append("")
        lines.append(f"<code>{h(bar)}</code>")

        # Action links — inline HTML <a> when inline_buttons disabled, else
        # rendered as Telegram inline_keyboard (returned via reply_markup).
        src = pool_source(pool)
        reply_markup = self.build_action_keyboard(
            chart_url=chart_url,
            pool_addr=pool_addr,
            jetton_addr=jetton_addr,
            source=src,
        )
        if reply_markup is None:
            lines.append("")
            lines.append(f'🟧 <a href="{h_attr(chart_url)}">Open x1000 Chart</a>')
            if pool_addr:
                if src == "stonfi":
                    lines.append(
                        f'🔎 <a href="https://app.ston.fi/pools/{h_attr(pool_addr)}">STON.fi Pool</a>'
                    )
                else:
                    lines.append(
                        f'🔎 <a href="https://dedust.io/pools/{h_attr(pool_addr)}">DeDust Pool</a>'
                    )
            if jetton_addr:
                lines.append(
                    f'🧭 <a href="https://tonviewer.com/{h_attr(jetton_addr)}">Tonviewer</a>'
                )

        # Disclaimer
        lines.append("")
        lines.append("⚠️ <b>Tracker Note</b>")
        lines.append("Automated alert, not financial advice. Always DYOR.")

        return "\n".join(lines), image, reply_markup

    @staticmethod
    def _shorten(addr: str) -> str:
        # Inline copy of fmt.shorten_address to avoid re-importing in hot path.
        if not addr:
            return "-"
        a = str(addr)
        if len(a) <= 13:
            return a
        return f"{a[:6]}...{a[-4:]}"

    def send_launch(self, pool: dict[str, Any]) -> None:
        text, image_url, reply_markup = self.build_message(pool)
        try:
            self._send_alert(text=text, image_url=image_url, reply_markup=reply_markup)
            self.metrics.alerts_sent_total.labels("launch").inc()
        except Exception:
            self.metrics.alert_errors_total.labels("launch").inc()
            raise

    def _send_alert(
        self,
        *,
        text: str,
        image_url: Optional[str],
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> None:
        """Common send path for launch + graduation alerts.

        Photo with caption when short enough; else photo + separate message.
        Inline-keyboard reply_markup is attached to whichever call carries
        the full text body (so buttons land on the message users actually
        read, not on a photo header).
        """
        base_payload: dict[str, Any] = {
            "chat_id": self.cfg.telegram_chat_id,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
        markup_str = json.dumps(reply_markup) if reply_markup else None
        short = len(text) <= 1000

        if image_url:
            photo_payload = dict(base_payload, photo=image_url)
            if short:
                photo_payload["caption"] = text
                if markup_str:
                    photo_payload["reply_markup"] = markup_str
            try:
                self.http.post_telegram("sendPhoto", photo_payload)
                if short:
                    return
            except Exception as e:
                log.warning("sendPhoto failed, fallback sendMessage: %s", e)

        msg_payload = dict(base_payload, text=text)
        if markup_str:
            msg_payload["reply_markup"] = markup_str
        self.http.post_telegram("sendMessage", msg_payload)

    # ---------------- Graduation alert ----------------

    def build_graduation_message(
        self, item: dict[str, Any]
    ) -> tuple[str, Optional[str], Optional[dict[str, Any]]]:
        """Build a separate alert for a memepad token whose bonding curve
        crossed the configured graduation threshold.

        Reuses the same x1000 enrichment shape as build_message but has its
        own header / wording so users can distinguish it from a fresh launch.
        """
        meta = item.get("metadata") or {}
        extra = item.get("memecoin_extra_details") or {}
        symbol = meta.get("ticker") or meta.get("symbol") or "?"
        name = meta.get("name") or symbol
        jetton_addr = str(item.get("asset") or meta.get("address") or "")
        image = meta.get("image_url") or None

        bond = bonding_stats(extra)
        bar = build_progress_bar(
            bond.get("percent"),
            length=int(self.cfg.progress_bar_length),
        )
        holders = item.get("holders")
        market_cap = format_usd(item.get("market_cap"))
        volume = coin_volume_24h(item)
        chart_url = self.build_x1000_link(jetton_addr, jetton_addr)

        lines: list[str] = []
        lines.append(f"<b>🎓 ${h(symbol)} graduated on TON</b>")
        lines.append("")
        lines.append(f"<b>{h(name)}</b>")
        if jetton_addr:
            lines.append(f"<code>{h(jetton_addr)}</code>")

        lines.append("")
        lines.append("Bonding curve filled — token migrated to a real DEX pool.")

        lines.append("")
        lines.append("📊 <b>Final Stats</b>")
        rows: list[tuple[str, str]] = []
        if bond.get("collected") is not None and bond.get("max") is not None:
            rows.append(
                (
                    "Raised",
                    f"{format_ton_short(bond['collected'])} / "
                    f"{format_ton_short(bond['max'])} TON",
                )
            )
        if holders is not None:
            rows.append(("Holders", str(holders)))
        if market_cap:
            rows.append(("Market Cap", market_cap))
        if volume:
            rows.append(("Volume 24h", volume))
        rendered_rows: list[tuple[str, str]] = rows or [("Status", "Graduated")]
        for i, (k, v) in enumerate(rendered_rows):
            connector = "┗" if i == len(rendered_rows) - 1 else "┣"
            lines.append(f"{connector} {h(k)}: <code>{h(v)}</code>")

        lines.append("")
        lines.append(f"<code>{h(bar)}</code>")

        reply_markup = self.build_action_keyboard(
            chart_url=chart_url,
            pool_addr="",  # graduation has no pool; kept jetton + chart only
            jetton_addr=jetton_addr,
            source="dedust",
        )
        if reply_markup is None:
            lines.append("")
            lines.append(f'🟧 <a href="{h_attr(chart_url)}">Open x1000 Chart</a>')
            if jetton_addr:
                lines.append(
                    f'🧭 <a href="https://tonviewer.com/{h_attr(jetton_addr)}">Tonviewer</a>'
                )

        lines.append("")
        lines.append("⚠️ <b>Tracker Note</b>")
        lines.append("Automated alert, not financial advice. Always DYOR.")

        return "\n".join(lines), image, reply_markup

    def send_graduation(self, item: dict[str, Any]) -> None:
        text, image_url, reply_markup = self.build_graduation_message(item)
        try:
            self._send_alert(text=text, image_url=image_url, reply_markup=reply_markup)
            self.metrics.alerts_sent_total.labels("graduation").inc()
        except Exception:
            self.metrics.alert_errors_total.labels("graduation").inc()
            raise

    def _check_graduations(self) -> int:
        """Fire one-shot graduation alerts for memepad assets that crossed
        the configured threshold this tick.

        Idempotent through `state.graduated` — each asset alerts at most
        once for its lifetime.
        """
        if not self.cfg.x1000_enabled:
            return 0
        items = self._fetch_x1000_items()
        if not items:
            return 0
        threshold = Decimal(self.cfg.graduation_threshold_pct)
        sent = 0
        for item in items:
            asset_raw = str(item.get("asset") or "").strip().lower()
            if not asset_raw or asset_raw in self.state.graduated:
                continue
            extra = item.get("memecoin_extra_details") or {}
            pct = bonding_stats(extra).get("percent")
            if pct is None or pct < threshold:
                continue
            try:
                self.send_graduation(item)
                sent += 1
            except Exception as e:
                log.exception("Failed sending graduation %s: %s", asset_raw, e)
            finally:
                self.state.graduated.add(asset_raw)
                self.state.save()
        return sent

    def tick(self) -> int:
        start = time.time()
        try:
            pools = self.fetch_pools()
        except Exception:
            self.metrics.tick_errors_total.inc()
            raise
        unseen = [p for p in pools if p.get("address") not in self.state.seen]
        log.info("Fetched %d pools, unseen=%d", len(pools), len(unseen))
        self.metrics.pools_fetched.set(len(pools))

        if not self.state.seen and self.cfg.skip_existing_on_first_run:
            self.state.seen.update(
                addr for p in pools if (addr := p.get("address"))
            )
            # Baseline graduated set too, so first-run never spams a fresh
            # install with already-graduated tokens.
            for item in self._fetch_x1000_items() or []:
                asset_raw = str(item.get("asset") or "").strip().lower()
                if not asset_raw:
                    continue
                pct = bonding_stats(item.get("memecoin_extra_details") or {}).get("percent")
                if pct is not None and pct >= Decimal(self.cfg.graduation_threshold_pct):
                    self.state.graduated.add(asset_raw)
            self.state.save()
            log.info("First run: marked existing pools as seen without alerts")
            self._record_tick_done(start)
            return 0

        sent = 0
        for pool in unseen:
            addr = pool.get("address")
            if not addr:
                continue
            try:
                self.send_launch(pool)
                sent += 1
            except Exception as e:
                log.exception("Failed sending launch %s: %s", addr, e)
            finally:
                self.state.seen.add(addr)
                self.state.save()
        # Graduation alerts run even when no new pools showed up this tick.
        sent += self._check_graduations()
        self.state.save()
        self._record_tick_done(start)
        return sent

    def _record_tick_done(self, started_at: float) -> None:
        now = time.time()
        self.metrics.ticks_total.inc()
        self.metrics.tick_duration_seconds.observe(now - started_at)
        self.metrics.last_tick_unixtime.set(now)
        if self._metrics_server is not None:
            self._metrics_server.last_tick_ts = now

    def run_forever(self) -> None:
        log.info("Starting TON launch tracker; interval=%ss", self.cfg.poll_interval_seconds)
        while True:
            try:
                self.tick()
            except Exception as e:
                log.exception("Tick failed: %s", e)
            time.sleep(self.cfg.poll_interval_seconds)

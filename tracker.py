import argparse
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("ton-launch-tracker")


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
    progress_bar_length: int = 10
    description_max_chars: int = 300
    max_social_links: int = 5
    state_file: Path = Path("./state/seen_pools.json")

    @classmethod
    def from_env(cls) -> "Config":
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
            progress_bar_length=int(os.getenv("PROGRESS_BAR_LENGTH", "10")),
            description_max_chars=int(os.getenv("DESCRIPTION_MAX_CHARS", "300")),
            max_social_links=int(os.getenv("MAX_SOCIAL_LINKS", "5")),
            state_file=Path(os.getenv("STATE_FILE", "./state/seen_pools.json")),
        )


class Http:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ton-launch-tracker/1.0"})
        if cfg.tonapi_key:
            self.session.headers.update({"Authorization": f"Bearer {cfg.tonapi_key}"})

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


class State:
    def __init__(self, path: Path):
        self.path = path
        self.seen: set[str] = set()
        self.last_checked_at: Optional[str] = None
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self.seen = set(data.get("seen_pool_addresses", []))
        self.last_checked_at = data.get("last_checked_at")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "seen_pool_addresses": sorted(self.seen),
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.write_text(json.dumps(data, indent=2))


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
        if isinstance(created_at, (int, float)):
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
        now = datetime.now(timezone.utc).timestamp()
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


URL_RE = re.compile(r"https?://[^\s<>\"'\\\)]+", re.IGNORECASE)


def extract_urls_from_text(text: Any) -> list[str]:
    if not text:
        return []
    raw = URL_RE.findall(str(text))
    cleaned: list[str] = []
    for u in raw:
        while u and u[-1] in ".,;:!?)]}>'\"":
            u = u[:-1]
        if u:
            cleaned.append(u)
    return cleaned


@dataclass
class SocialLink:
    label: str
    icon: str
    url: str
    priority: int


SOCIAL_PRIORITY = {
    "telegram": 1,
    "twitter": 2,
    "discord": 3,
    "youtube": 4,
    "github": 5,
    "medium": 6,
    "website": 7,
    "other": 8,
}

SOCIAL_LABELS = {
    "telegram": ("Telegram", "💬"),
    "twitter": ("X", "🐦"),
    "discord": ("Discord", "🎮"),
    "youtube": ("YouTube", "📺"),
    "github": ("GitHub", "🐙"),
    "medium": ("Medium", "📰"),
    "website": ("Website", "🌐"),
    "other": ("Link", "🔗"),
}


def _classify_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "other"
    if not host:
        return "other"
    if host.startswith("www."):
        host = host[4:]
    if host in ("t.me", "telegram.me", "telegram.org"):
        return "telegram"
    if host in ("x.com", "twitter.com"):
        return "twitter"
    if host in ("discord.gg", "discord.com"):
        return "discord"
    if host in ("youtube.com", "youtu.be"):
        return "youtube"
    if host == "github.com":
        return "github"
    if host == "medium.com" or host.endswith(".medium.com"):
        return "medium"
    return "website"


def normalize_social_url(url: Any) -> Optional[SocialLink]:
    if not url:
        return None
    s = str(url).strip().strip("'\"")
    if not s:
        return None
    if not s.lower().startswith(("http://", "https://")):
        if "." in s and " " not in s and "/" not in s.split(".", 1)[0]:
            s = "https://" + s
        else:
            return None
    try:
        parsed = urlparse(s)
        if not parsed.netloc or "." not in parsed.netloc:
            return None
    except Exception:
        return None
    kind = _classify_url(s)
    label, icon = SOCIAL_LABELS[kind]
    return SocialLink(label=label, icon=icon, url=s, priority=SOCIAL_PRIORITY[kind])


_SOCIAL_FIELD_KEYS = {
    "telegram", "tg",
    "twitter", "x",
    "discord",
    "youtube", "yt",
    "github",
    "medium",
    "website", "site", "homepage", "url", "web",
}
_SOCIAL_CONTAINER_KEYS = {"socials", "social", "links", "websites", "external_urls"}


def _walk_for_urls(obj: Any, depth: int = 0) -> list[str]:
    if obj is None or depth > 6:
        return []
    if isinstance(obj, str):
        s = obj.strip()
        return [s] if s else []
    if isinstance(obj, dict):
        out: list[str] = []
        for k, v in obj.items():
            kl = str(k).lower()
            if (
                kl in _SOCIAL_CONTAINER_KEYS
                or kl in _SOCIAL_FIELD_KEYS
                or "link" in kl
                or "url" in kl
                or "site" in kl
                or "social" in kl
            ):
                out.extend(_walk_for_urls(v, depth + 1))
        return out
    if isinstance(obj, (list, tuple, set)):
        out = []
        for item in obj:
            out.extend(_walk_for_urls(item, depth + 1))
        return out
    return []


def extract_social_links(
    *sources: Any,
    description_text: Any = None,
    max_count: int = 5,
) -> list[SocialLink]:
    raw_urls: list[str] = []
    for src in sources:
        raw_urls.extend(_walk_for_urls(src))
    if description_text:
        raw_urls.extend(extract_urls_from_text(description_text))

    seen: set[str] = set()
    links: list[SocialLink] = []
    for u in raw_urls:
        for piece in re.split(r"[\s,;\n]+", u):
            piece = piece.strip()
            if not piece:
                continue
            sl = normalize_social_url(piece)
            if not sl:
                continue
            key = sl.url.lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            links.append(sl)
    links.sort(key=lambda x: (x.priority, x.url))
    return links[: max(1, int(max_count))]


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


class Tracker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = Http(cfg)
        self.state = State(cfg.state_file)

    def fetch_pools(self) -> list[dict[str, Any]]:
        pools = self.http.get_json(self.cfg.dedust_pools_url)
        if not isinstance(pools, list):
            raise RuntimeError(f"Unexpected DeDust response: {type(pools)}")
        pools = [p for p in pools if pick_jetton(p)]
        if self.cfg.require_native_ton:
            pools = [p for p in pools if pool_has_ton(p)]
        return sorted(pools, key=pool_lt)

    def tonapi(self, path: str) -> Any:
        return self.http.get_json(f"{self.cfg.tonapi_base_url}{path}")

    def jetton_details(self, address: str) -> dict[str, Any]:
        try:
            return self.tonapi(f"/jettons/{address}")
        except Exception as e:
            log.warning("TonAPI jetton lookup failed for %s: %s", address, e)
            return {}

    def x1000_coin_for(self, jetton_addr: str, details: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Return the full DeDust/x1000 Memepad coin item for a jetton when available.

        x1000.finance/launches uses the public DeDust API endpoint
        https://mainnet.api.dedust.io/v4/api/coins. With memecoin_extra_details=true,
        DeDust memepad launches include memecoin_extra_details.author, curve_*,
        plus richer metadata (image_url, description, holders, market_cap, ...).
        Returning the whole item lets build_message reuse one network call.
        """
        if not self.cfg.x1000_enabled or not jetton_addr:
            return None
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
            log.warning("x1000/DeDust coins lookup failed for %s: %s", jetton_addr, e)
            return None
        items = data.get("items", []) if isinstance(data, dict) else []
        return find_x1000_coin_details(jetton_addr, details, items)

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
        try:
            data = self.tonapi(f"/blockchain/accounts/{address}")
            return ton_from_nano(data.get("balance"))
        except Exception as e:
            log.warning("TonAPI account lookup failed for %s: %s", address, e)
            return None

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

    def build_message(self, pool: dict[str, Any]) -> tuple[str, Optional[str]]:
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
        volume = format_usd(x1000_coin.get("volume") if x1000_coin else None)

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
            wallet_short = shorten_address(deployer_addr)
            balance_str = (
                f"{deployer_balance} TON" if deployer_balance else "Unknown"
            )
            deploy_amount = (
                f"{format_ton_short(bond_collected)} TON"
                if bond_collected is not None
                else "Unknown"
            )
            lines.append(f"┣ Wallet: <code>{h(wallet_short)}</code>")
            lines.append(f"┣ Full: <code>{h(deployer_addr)}</code>")
            lines.append(f"┣ Balance: <code>{h(balance_str)}</code>")
            lines.append(f"┣ Deploy Amount: <code>{h(deploy_amount)}</code>")
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

        # Action links
        lines.append("")
        lines.append(f'🟧 <a href="{h_attr(chart_url)}">Open x1000 Chart</a>')
        if pool_addr:
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

        return "\n".join(lines), image

    def send_launch(self, pool: dict[str, Any]) -> None:
        text, image_url = self.build_message(pool)
        payload = {
            "chat_id": self.cfg.telegram_chat_id,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
        if image_url:
            photo_payload = dict(payload)
            photo_payload["photo"] = image_url
            # Telegram photo captions max 1024 chars. If message is longer, send
            # the image first then send the full formatted alert as a message.
            if len(text) <= 1000:
                photo_payload["caption"] = text
            try:
                self.http.post_telegram("sendPhoto", photo_payload)
                if len(text) <= 1000:
                    return
            except Exception as e:
                log.warning("sendPhoto failed, fallback sendMessage: %s", e)
        payload.update({"text": text})
        self.http.post_telegram("sendMessage", payload)

    def tick(self) -> int:
        pools = self.fetch_pools()
        unseen = [p for p in pools if p.get("address") not in self.state.seen]
        log.info("Fetched %d pools, unseen=%d", len(pools), len(unseen))

        if not self.state.seen and self.cfg.skip_existing_on_first_run:
            self.state.seen.update(p.get("address") for p in pools if p.get("address"))
            self.state.save()
            log.info("First run: marked existing pools as seen without alerts")
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
        self.state.save()
        return sent

    def run_forever(self) -> None:
        log.info("Starting TON launch tracker; interval=%ss", self.cfg.poll_interval_seconds)
        while True:
            try:
                self.tick()
            except Exception as e:
                log.exception("Tick failed: %s", e)
            time.sleep(self.cfg.poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram bot: TON new token launch tracker from DeDust pools")
    parser.add_argument("--once", action="store_true", help="Run one polling tick then exit")
    parser.add_argument("--dry-run", action="store_true", help="Fetch/build first unseen message and print it without Telegram send")
    args = parser.parse_args()

    cfg = Config.from_env()
    tracker = Tracker(cfg)

    if args.dry_run:
        pools = tracker.fetch_pools()
        unseen = [p for p in pools if p.get("address") not in tracker.state.seen]
        sample = unseen[0] if unseen else (pools[-1] if pools else None)
        if not sample:
            print("No pools returned by DeDust")
            return
        text, image = tracker.build_message(sample)
        print("IMAGE:", image or "-")
        print(text)
        return

    if args.once:
        sent = tracker.tick()
        print(f"sent={sent}")
        return

    tracker.run_forever()


if __name__ == "__main__":
    main()

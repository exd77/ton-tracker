"""Social-link extraction from x1000 / TonAPI metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

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
# Keys that *contain* url/link/site substrings but are not social. These bias
# the heuristic walker away from media/asset URLs.
_NON_SOCIAL_HINTS = (
    "image", "preview", "icon", "logo", "thumb", "avatar", "banner",
    "asset", "media", "video_url", "audio_url", "address",
)
# URL paths ending in these extensions are media, not socials.
_MEDIA_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".mp4", ".mov", ".webm", ".mp3", ".wav", ".ogg",
)


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
            if any(hint in kl for hint in _NON_SOCIAL_HINTS):
                continue
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
    if isinstance(obj, (list | tuple | set)):
        out = []
        for item in obj:
            out.extend(_walk_for_urls(item, depth + 1))
        return out
    return []


def _is_media_url(url: str) -> bool:
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    return any(path.endswith(ext) for ext in _MEDIA_EXTS)


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
            if _is_media_url(sl.url):
                continue
            key = sl.url.lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            links.append(sl)
    links.sort(key=lambda x: (x.priority, x.url))
    return links[: max(1, int(max_count))]

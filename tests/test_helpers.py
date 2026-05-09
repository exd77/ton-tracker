"""Unit tests for pure helper functions in tracker.py.

These don't touch the network and run in <100ms. They're the cheap
regression layer for the formatting/extraction logic; AC end-to-end tests
live in test_build_message.py.
"""
from __future__ import annotations

import time
from decimal import Decimal

import pytest

import tracker

# ---------- nano <-> ton ----------

def test_nano_to_ton_decimal_basic():
    assert tracker.nano_to_ton_decimal("1000000000") == Decimal("1")
    assert tracker.nano_to_ton_decimal("4854368933") == Decimal("4.854368933")


def test_nano_to_ton_decimal_handles_garbage():
    assert tracker.nano_to_ton_decimal(None) is None
    assert tracker.nano_to_ton_decimal("") is None
    assert tracker.nano_to_ton_decimal("not-a-number") is None


# ---------- format_ton_short ----------

@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("4.854368933"), "4.85"),
        (Decimal("1050"), "1050"),
        (Decimal("1.0"), "1"),
        (Decimal("0"), "0"),
        (Decimal("0.0001"), "0.0001"),
    ],
)
def test_format_ton_short(value, expected):
    assert tracker.format_ton_short(value) == expected


# ---------- format_usd ----------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("901", "$901"),
        ("12.53", "$12.53"),
        ("4260.123", "$4.26K"),
        ("1234567", "$1.23M"),
        ("0", "$0"),
    ],
)
def test_format_usd(value, expected):
    assert tracker.format_usd(value) == expected


def test_format_usd_rejects_non_scalars():
    assert tracker.format_usd({"h24": "1"}) is None
    assert tracker.format_usd([1, 2]) is None
    assert tracker.format_usd(None) is None


# ---------- shorten_address ----------

def test_shorten_address():
    addr = "0:01a700000000000000000000000000000000000000000000000000000000e1c5"
    assert tracker.shorten_address(addr) == "0:01a7...e1c5"
    assert tracker.shorten_address("") == "-"
    assert tracker.shorten_address("short") == "short"


# ---------- format_age ----------

def test_format_age_seconds():
    now = time.time()
    assert tracker.format_age(now - 30).endswith("s")


def test_format_age_minutes():
    now = time.time()
    out = tracker.format_age(now - 600)
    assert out.endswith("m")


def test_format_age_hours():
    now = time.time()
    out = tracker.format_age(now - 3 * 3600 - 12 * 60)
    assert "h" in out and "m" in out


def test_format_age_days():
    now = time.time()
    out = tracker.format_age(now - 2 * 86400 - 3 * 3600)
    assert out.endswith("h") and "d" in out


def test_format_age_unknown():
    assert tracker.format_age(None) == "Unknown"
    assert tracker.format_age("") == "Unknown"
    assert tracker.format_age("not-a-date") == "Unknown"


def test_format_age_iso_z_suffix():
    # "2026-01-01T00:00:00Z" needs the Z->+00:00 fixup we wrote.
    assert tracker.format_age("2026-01-01T00:00:00Z") != "Unknown"


# ---------- build_progress_bar ----------

@pytest.mark.parametrize(
    "pct,expected",
    [
        (Decimal("0.46232"), "▰▱▱▱▱▱▱▱▱▱ 0.46%"),  # AC-2 from PRD
        (Decimal("42.0"), "▰▰▰▰▱▱▱▱▱▱ 42.0%"),
        (Decimal("100"), "▰▰▰▰▰▰▰▰▰▰ 100.0%"),
        (Decimal("0"), "▱▱▱▱▱▱▱▱▱▱ 0.00%"),
    ],
)
def test_build_progress_bar(pct, expected):
    assert tracker.build_progress_bar(pct, length=10) == expected


def test_build_progress_bar_unknown():
    assert "Unknown" in tracker.build_progress_bar(None, length=10)


def test_build_progress_bar_clamps_over_100():
    bar = tracker.build_progress_bar(Decimal("250"), length=10)
    assert bar.startswith("▰" * 10)


def test_build_progress_bar_min_one_block_when_positive():
    # Tiny positive % should still show 1 block, not 0
    bar = tracker.build_progress_bar(Decimal("0.01"), length=10)
    assert bar.startswith("▰▱")


# ---------- bonding_stats ----------

def test_bonding_stats_active_curve():
    stats = tracker.bonding_stats(
        {"curve_ton_collected": "4854368933", "curve_ton_max": "1050000000000"}
    )
    assert stats["collected"] == Decimal("4.854368933")
    assert stats["max"] == Decimal("1050")
    assert stats["percent"] is not None and stats["percent"] < Decimal(1)


def test_bonding_stats_missing_fields():
    assert tracker.bonding_stats({})["percent"] is None
    assert tracker.bonding_stats({"curve_ton_collected": "1"})["percent"] is None


def test_bonding_stats_zero_max():
    stats = tracker.bonding_stats(
        {"curve_ton_collected": "1", "curve_ton_max": "0"}
    )
    assert stats["percent"] is None


# ---------- URL extraction & socials ----------

def test_extract_urls_from_text_basic():
    urls = tracker.extract_urls_from_text(
        "Join https://t.me/example and follow https://x.com/example."
    )
    assert "https://t.me/example" in urls
    assert "https://x.com/example" in urls


def test_extract_urls_strips_trailing_punct():
    urls = tracker.extract_urls_from_text("link: https://example.com.")
    assert urls == ["https://example.com"]


def test_normalize_social_classifies():
    assert tracker.normalize_social_url("https://t.me/foo").label == "Telegram"
    assert tracker.normalize_social_url("https://x.com/foo").label == "X"
    assert tracker.normalize_social_url("https://twitter.com/foo").label == "X"
    assert tracker.normalize_social_url("https://discord.gg/foo").label == "Discord"
    assert tracker.normalize_social_url("https://example.com").label == "Website"


def test_normalize_social_auto_https_for_bare_host():
    sl = tracker.normalize_social_url("t.me/Noblee33")
    assert sl is not None
    assert sl.url == "https://t.me/Noblee33"
    assert sl.label == "Telegram"


def test_normalize_social_rejects_garbage():
    assert tracker.normalize_social_url("") is None
    assert tracker.normalize_social_url("not a url") is None
    assert tracker.normalize_social_url(None) is None


def test_extract_social_links_dedup_and_sort():
    sources = (
        {"social_links": {"telegram": "t.me/foo", "twitter": "https://x.com/foo"}},
        {"website": "https://example.com"},
    )
    links = tracker.extract_social_links(*sources, max_count=10)
    labels = [link.label for link in links]
    # Telegram < X < Website by priority
    assert labels[0] == "Telegram"
    assert "X" in labels
    assert "Website" in labels


def test_extract_social_links_skips_media_urls():
    """Image/media URLs must not surface as 'Website' socials."""
    src = {"image_url": "https://cdn.example.com/img.webp"}
    assert tracker.extract_social_links(src, max_count=10) == []


def test_extract_social_links_walks_description_text():
    links = tracker.extract_social_links(
        {}, description_text="visit https://t.me/abc", max_count=10
    )
    assert any(link.url == "https://t.me/abc" for link in links)


# ---------- find_x1000_coin_details ----------

def test_find_x1000_coin_matches_eq_to_raw_via_metadata():
    items = [{"asset": "0:abcdef", "metadata": {"name": "Foo"}}]
    details = {"metadata": {"address": "0:abcdef"}}
    coin = tracker.find_x1000_coin_details("EQfake", details, items)
    assert coin is items[0]


def test_find_x1000_coin_no_match():
    items = [{"asset": "0:1234"}]
    assert tracker.find_x1000_coin_details("EQfake", {}, items) is None


def test_find_x1000_coin_empty_jetton():
    assert tracker.find_x1000_coin_details("", {}, [{"asset": "0:1"}]) is None


# ---------- coin_volume_24h ----------

def test_coin_volume_24h_total_periods():
    coin = {"volume": {"total_periods": {"h24": "12.53"}}}
    assert tracker.coin_volume_24h(coin) == "$12.53"


def test_coin_volume_24h_buy_plus_sell():
    coin = {"volume": {"buy_periods": {"h24": "10"}, "sell_periods": {"h24": "5"}}}
    assert tracker.coin_volume_24h(coin) == "$15"


def test_coin_volume_24h_scalar_form():
    assert tracker.coin_volume_24h({"volume": "100"}) == "$100"


def test_coin_volume_24h_missing():
    assert tracker.coin_volume_24h({}) is None
    assert tracker.coin_volume_24h(None) is None


# ---------- coin_tx_24h ----------

def test_coin_tx_24h():
    coin = {"transactions": {"buy": {"h24": 21}, "sell": {"h24": 14}}}
    assert tracker.coin_tx_24h(coin) == "21 buy / 14 sell"


def test_coin_tx_24h_missing():
    assert tracker.coin_tx_24h({}) is None
    assert tracker.coin_tx_24h(None) is None
    assert tracker.coin_tx_24h({"transactions": "weird"}) is None


# ---------- pool_ton_reserve ----------

def test_pool_ton_reserve():
    pool = {
        "assets": [{"type": "native"}, {"type": "jetton", "address": "EQ..."}],
        "reserves": ["50000000000", "12345"],  # 50 TON
    }
    assert tracker.pool_ton_reserve(pool) == Decimal("50")


def test_pool_ton_reserve_no_native():
    pool = {"assets": [{"type": "jetton"}, {"type": "jetton"}], "reserves": ["1", "1"]}
    assert tracker.pool_ton_reserve(pool) == Decimal(0)


def test_pool_ton_reserve_garbage():
    pool = {"assets": [{"type": "native"}], "reserves": ["bogus"]}
    assert tracker.pool_ton_reserve(pool) == Decimal(0)


# ---------- TTLCache ----------

def test_ttl_cache_set_get():
    c = tracker.TTLCache(60)
    c.set("k", "v")
    assert c.get("k") == "v"


def test_ttl_cache_expires(monkeypatch):
    c = tracker.TTLCache(0.1)
    c.set("k", "v")
    time.sleep(0.2)
    assert c.get("k") is None


def test_ttl_cache_clear():
    c = tracker.TTLCache(60)
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert len(c) == 0


# ---------- HTML safety helpers ----------

def test_h_escapes_html():
    assert tracker.h("<script>") == "&lt;script&gt;"


def test_h_attr_escapes_quotes():
    out = tracker.h_attr('"\'<>&')
    assert "&quot;" in out and "&lt;" in out

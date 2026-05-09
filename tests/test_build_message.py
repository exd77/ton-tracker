"""End-to-end tests for Tracker.build_message covering PRD AC-1..AC-5
plus regressions caught during backtest (media URLs, nested volume dict,
tx 24h, chart pattern, zero deployer)."""
from __future__ import annotations

from decimal import Decimal

import pytest

import tracker


JETTON = "0:1111111111111111111111111111111111111111111111111111111111111111"
DEPLOYER = "0:01a700000000000000000000000000000000000000000000000000000000e1c5"
ZERO = "0:" + "0" * 64

POOL = {
    "address": "EQPoolAddr",
    "type": "volatile",
    "tradeFee": "0.25",
    "lt": 1,
    "assets": [
        {"type": "native"},
        {
            "type": "jetton",
            "address": JETTON,
            "metadata": {"symbol": "SHITON", "name": "Shit on TON", "decimals": 9},
        },
    ],
    "reserves": ["1000000000", "5000000000000"],
}

DETAILS = {
    "metadata": {
        "address": JETTON,
        "name": "Shit on TON",
        "symbol": "SHITON",
        "description": "From $SHIT to $SHITON.",
        "image": "https://tonapi.example/img.png",
        "decimals": "9",
    },
    "preview": "https://tonapi.example/preview.png",
    "admin": {"address": DEPLOYER, "name": "tonapi-admin"},
}

COIN_FULL = {
    "asset": JETTON.lower(),
    "holders": 10,
    "created_at": "",
    "market_cap": "901",
    "volume": "12.53",
    "metadata": {
        "name": "Shit on TON",
        "ticker": "SHITON",
        "description": (
            "From $SHIT to $SHITON. Same smell, new chain. "
            "Join https://t.me/example and follow https://x.com/example"
        ),
        "image_url": "https://x1000.example/img.png",
    },
    "memecoin_extra_details": {
        "author": DEPLOYER,
        "curve_ton_collected": "4854368933",
        "curve_ton_max": "1050000000000",
    },
}


@pytest.fixture
def tr(tmp_path):
    """Default tracker fixture used by existing tests.

    Inline buttons are disabled here so message-body assertions can keep
    matching against HTML <a> link footers. Tests that exercise the
    keyboard path opt in explicitly via `tr_buttons`.
    """
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.inline_buttons = False
    cfg.state_file = tmp_path / "state.json"
    return tracker.Tracker(cfg)


@pytest.fixture
def tr_buttons(tmp_path):
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.inline_buttons = True
    cfg.state_file = tmp_path / "state.json"
    return tracker.Tracker(cfg)


def patch(t, *, coin=None, balance="12.34", details=None):
    """Replace network-touching methods with deterministic stubs."""
    t.jetton_details = lambda addr: details if details is not None else DETAILS
    t.x1000_coin_for = lambda addr, det: coin
    t.account_balance_ton = lambda addr: balance


# =============== AC-1 ===============

def test_ac1_message_has_all_sections(tr):
    patch(tr, coin=COIN_FULL)
    text, image, _ = tr.build_message(POOL)
    for section in (
        "just launched on TON",
        "Description",
        "Socials",
        "Deployer",
        "Launch Stats",
        "Open x1000 Chart",
        "Tracker Note",
        "▰",  # progress bar contains at least one filled block
    ):
        assert section in text, f"missing: {section}"
    assert image == "https://x1000.example/img.png"


# =============== AC-2 ===============

def test_ac2_bonding_curve_renders_correctly(tr):
    patch(tr, coin=COIN_FULL)
    text, _, _ = tr.build_message(POOL)
    assert "4.85 / 1050 TON" in text
    assert "0.46%" in text
    assert "▰▱▱▱▱▱▱▱▱▱ 0.46%" in text


# =============== AC-3 ===============

def test_ac3_socials_extracted_from_description(tr):
    coin = {
        "asset": JETTON.lower(),
        "metadata": {
            "name": "x",
            "ticker": "Y",
            "description": "Join https://t.me/example and https://x.com/example",
        },
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert '<a href="https://t.me/example">Telegram</a>' in text
    assert '<a href="https://x.com/example">X</a>' in text


# =============== AC-4 ===============

def test_ac4_fallback_when_x1000_unavailable(tr):
    patch(tr, coin=None)
    text, image, _ = tr.build_message(POOL)
    # Still produces a valid alert
    assert "just launched on TON" in text
    assert "Shit on TON" in text
    assert JETTON in text
    # Deployer falls back to TonAPI admin.address
    assert DEPLOYER in text
    # x1000 chart link falls back to base URL
    assert "https://x1000.finance/" in text
    # Progress bar shows Unknown
    assert "Unknown" in text
    # Image falls back to TonAPI preview
    assert image == "https://tonapi.example/preview.png"


# =============== AC-5 ===============

def test_ac5_html_in_token_metadata_is_escaped(tr):
    nasty = {
        "metadata": {
            "address": JETTON,
            "name": "<script>alert(1)</script>",
            "symbol": "<b>EVIL</b>",
            "description": "<img src=x onerror=alert(1)> & 'q'",
            "image": "https://tonapi.example/img.png",
            "decimals": "9",
        },
        "preview": None,
        "admin": {"address": DEPLOYER},
    }
    patch(tr, coin=None, details=nasty)
    text, _, _ = tr.build_message(POOL)
    # Raw HTML must NOT survive into output
    assert "<script>alert(1)</script>" not in text
    assert "<img src=x onerror=alert(1)>" not in text
    # Properly escaped form must appear
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&lt;img src=x onerror=alert(1)&gt;" in text
    assert "&amp;" in text


# =============== Regressions ===============

def test_regression_image_url_not_in_socials(tr):
    """Image CDN URLs (image_url field) must not surface as Website socials."""
    coin = {
        "asset": JETTON.lower(),
        "metadata": {
            "name": "x",
            "ticker": "Y",
            "description": "no urls",
            "image_url": "https://cdn.dedust.io/image.webp",
            "preview_url": "https://cdn.example/p.png",
        },
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert "https://cdn.dedust.io/image.webp" not in text
    assert "cdn.example/p.png" not in text


def test_regression_social_links_telegram_bare_host(tr):
    """metadata.social_links.telegram with bare 't.me/...' must be promoted."""
    coin = {
        "asset": JETTON.lower(),
        "metadata": {
            "name": "x",
            "ticker": "Y",
            "description": "no urls",
            "social_links": {"telegram": "t.me/Noblee33"},
        },
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert '<a href="https://t.me/Noblee33">Telegram</a>' in text


def test_regression_volume_nested_dict(tr):
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "x", "ticker": "Y", "description": "d"},
        "memecoin_extra_details": {
            "author": DEPLOYER,
            "curve_ton_collected": "1000000000",
            "curve_ton_max": "1050000000000",
        },
        "market_cap": "1095.71",
        "volume": {"total_periods": {"h24": "12.53"}},
        "transactions": {"buy": {"h24": 21}, "sell": {"h24": 14}},
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert "Volume 24h" in text
    assert "$12.53" in text
    assert "Tx 24h" in text
    assert "21 buy / 14 sell" in text


def test_chart_pattern_with_asset(tr):
    tr.cfg.x1000_token_route_pattern = "/coins/{asset}"
    patch(tr, coin=COIN_FULL)
    text, _, _ = tr.build_message(POOL)
    assert f"https://x1000.finance/coins/{JETTON.lower()}" in text


def test_chart_pattern_absolute_url(tr):
    tr.cfg.x1000_token_route_pattern = "https://other.example/{asset}"
    patch(tr, coin=COIN_FULL)
    text, _, _ = tr.build_message(POOL)
    assert f"https://other.example/{JETTON.lower()}" in text


def test_chart_pattern_invalid_falls_back_to_base(tr):
    # Unknown placeholder triggers KeyError → fallback path
    tr.cfg.x1000_token_route_pattern = "/coins/{nonexistent}"
    patch(tr, coin=COIN_FULL)
    text, _, _ = tr.build_message(POOL)
    assert "https://x1000.finance/" in text


def test_zero_deployer(tr):
    zd = dict(DETAILS)
    zd["admin"] = {"address": ZERO}
    zc = dict(COIN_FULL)
    zc["memecoin_extra_details"] = dict(zc["memecoin_extra_details"])
    zc["memecoin_extra_details"]["author"] = ZERO
    patch(tr, coin=zc, details=zd)
    text, _, _ = tr.build_message(POOL)
    assert "Revoked / zero address / unknown" in text


# =============== Sprint 1 additions ===============

def test_caching_jetton_details_avoids_repeat_calls(tr, monkeypatch):
    calls = {"n": 0}

    def fake_tonapi(path):
        calls["n"] += 1
        return {"metadata": {"name": "X", "address": JETTON}, "admin": {}}

    tr.tonapi = fake_tonapi  # type: ignore
    tr.jetton_details(JETTON)
    tr.jetton_details(JETTON)
    tr.jetton_details(JETTON)
    assert calls["n"] == 1, "jetton_details should hit network only once"


def test_caching_does_not_poison_on_failure(tr):
    """Empty/failed responses must not be cached so retries are possible."""
    calls = {"n": 0}

    def fake_tonapi(path):
        calls["n"] += 1
        raise RuntimeError("boom")

    tr.tonapi = fake_tonapi  # type: ignore
    assert tr.jetton_details(JETTON) == {}
    assert tr.jetton_details(JETTON) == {}
    assert calls["n"] == 2, "should retry on failure (no negative caching)"


def test_x1000_items_cache_reused_across_pools(tr):
    calls = {"n": 0}
    items = [{"asset": JETTON.lower(), "metadata": {"name": "C"}}]

    def fake_get_json(*a, **kw):
        calls["n"] += 1
        return {"items": items}

    tr.http.get_json = fake_get_json  # type: ignore

    # Two consecutive calls — second should reuse cache.
    tr.x1000_coin_for(JETTON, {})
    tr.x1000_coin_for(JETTON, {})
    assert calls["n"] == 1, "x1000 list should be fetched once per cache window"


def test_min_ton_reserves_filter():
    cfg = tracker.Config.from_env()
    cfg.min_ton_reserves = Decimal("10")
    tr = tracker.Tracker(cfg)

    pools = [
        {
            "address": "small",
            "assets": [{"type": "native"}, {"type": "jetton", "address": "x"}],
            "reserves": ["1000000000", "1"],  # 1 TON
            "lt": 1,
        },
        {
            "address": "big",
            "assets": [{"type": "native"}, {"type": "jetton", "address": "x"}],
            "reserves": ["50000000000", "1"],  # 50 TON
            "lt": 2,
        },
    ]

    tr.http.get_json = lambda url, **kw: pools  # type: ignore

    out = tr.fetch_pools()
    addrs = [p["address"] for p in out]
    assert "big" in addrs
    assert "small" not in addrs

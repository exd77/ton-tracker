"""Tests for Sprint 2 features: STON.fi adapter, signal-quality badges
(tax, verification, dev cluster), graduation alert, and Telegram inline
buttons."""
from __future__ import annotations

from decimal import Decimal

import pytest

import tracker

JETTON = "0:" + "1" * 64
DEPLOYER = "0:01a700000000000000000000000000000000000000000000000000000000e1c5"
DEPLOYER2 = "0:abc7000000000000000000000000000000000000000000000000000000001234"


# =================================================================
#                       STON.fi pool adapter
# =================================================================

def test_stonfi_normalize_basic_pool():
    raw = {
        "address": "EQTestPool",
        "token0_address": "EQJetton",
        "token1_address": tracker.STONFI_NATIVE_TON_ADDR,
        "reserve0": "1000",
        "reserve1": "2000",
        "lp_fee": "20",
        "protocol_fee": "10",
        "deprecated": False,
    }
    out = tracker.normalize_stonfi_pool(raw)
    assert out["address"] == "EQTestPool"
    assert out["type"] == "stonfi"
    assert out["_source"] == "stonfi"
    assert out["assets"][0] == {
        "type": "jetton",
        "address": "EQJetton",
        "metadata": {},
    }
    assert out["assets"][1] == {"type": "native"}
    assert out["reserves"] == ["1000", "2000"]
    # lp+proto = 30bp = 0.30 → trimmed to "0.3"
    assert out["tradeFee"] == "0.3"


def test_stonfi_normalize_skips_deprecated():
    assert tracker.normalize_stonfi_pool({"address": "x", "deprecated": True}) == {}


def test_stonfi_normalize_skips_missing_address():
    assert tracker.normalize_stonfi_pool({"token0_address": "a"}) == {}


def test_stonfi_normalize_handles_garbage_fees():
    raw = {
        "address": "EQ",
        "token0_address": "EQ1",
        "token1_address": tracker.STONFI_NATIVE_TON_ADDR,
        "lp_fee": "not-a-number",
        "protocol_fee": None,
    }
    assert tracker.normalize_stonfi_pool(raw)["tradeFee"] == "?"


def test_stonfi_normalize_native_first_position():
    raw = {
        "address": "EQ",
        "token0_address": tracker.STONFI_NATIVE_TON_ADDR,
        "token1_address": "EQJ",
        "reserve0": "1",
        "reserve1": "2",
    }
    out = tracker.normalize_stonfi_pool(raw)
    assert out["assets"][0] == {"type": "native"}
    assert out["assets"][1]["address"] == "EQJ"


def test_pool_source_dedust_default():
    assert tracker.pool_source({"type": "volatile"}) == "dedust"


def test_pool_source_stonfi():
    assert tracker.pool_source({"type": "stonfi"}) == "stonfi"


def test_pool_source_explicit_label():
    assert tracker.pool_source({"_source": "custom", "type": "x"}) == "custom"


def test_fetch_pools_merges_dedust_and_stonfi():
    cfg = tracker.Config.from_env()
    cfg.stonfi_enabled = True
    tr = tracker.Tracker(cfg)

    dedust_response = [
        {
            "address": "DD1",
            "type": "volatile",
            "lt": 100,
            "assets": [
                {"type": "native"},
                {"type": "jetton", "address": "EQJ1", "metadata": {}},
            ],
            "reserves": ["1", "1"],
        }
    ]
    stonfi_response = {
        "pool_list": [
            {
                "address": "SF1",
                "token0_address": "EQJ2",
                "token1_address": tracker.STONFI_NATIVE_TON_ADDR,
                "reserve0": "1",
                "reserve1": "1",
                "lp_fee": "20",
                "protocol_fee": "10",
            }
        ]
    }

    def fake_get(url, **kw):
        if "ston.fi" in url:
            return stonfi_response
        return dedust_response

    tr.http.get_json = fake_get  # type: ignore
    pools = tr.fetch_pools()
    addrs = [p["address"] for p in pools]
    assert "DD1" in addrs
    assert "SF1" in addrs


def test_fetch_pools_stonfi_failure_does_not_block_dedust():
    cfg = tracker.Config.from_env()
    cfg.stonfi_enabled = True
    tr = tracker.Tracker(cfg)

    def fake_get(url, **kw):
        if "ston.fi" in url:
            raise RuntimeError("stonfi down")
        return [
            {
                "address": "DD1",
                "type": "volatile",
                "lt": 100,
                "assets": [
                    {"type": "native"},
                    {"type": "jetton", "address": "EQJ1", "metadata": {}},
                ],
                "reserves": ["1", "1"],
            }
        ]

    tr.http.get_json = fake_get  # type: ignore
    pools = tr.fetch_pools()
    assert any(p["address"] == "DD1" for p in pools)


# =================================================================
#                         Signal badges
# =================================================================

@pytest.mark.parametrize(
    "buy,sell,expected_substr",
    [
        (0, 0, "0% / 0%"),
        (5, 5, "5% / 5%"),
        (10, 0, "⚠️"),
        (50, 50, "🚨"),
    ],
)
def test_format_tax(buy, sell, expected_substr):
    assert expected_substr in tracker.format_tax({"buy_tax": buy, "sell_tax": sell})


def test_format_tax_zero_gets_check_icon():
    assert "✅" in tracker.format_tax({"buy_tax": 0, "sell_tax": 0})


def test_format_tax_missing_returns_none():
    assert tracker.format_tax({}) is None
    assert tracker.format_tax(None) is None


def test_format_tax_garbage_input():
    assert tracker.format_tax({"buy_tax": "huh"}) is None


@pytest.mark.parametrize(
    "level,label",
    [(0, "Unverified"), (1, "Indexed"), (2, "Verified"), (3, "Whitelisted")],
)
def test_format_verification(level, label):
    out = tracker.format_verification({"verification_level": level})
    assert label in out


def test_format_verification_unknown_level():
    out = tracker.format_verification({"verification_level": 99})
    assert "Level 99" in out


def test_format_verification_missing():
    assert tracker.format_verification({}) is None
    assert tracker.format_verification(None) is None


def test_deployer_token_count():
    items = [
        {"memecoin_extra_details": {"author": DEPLOYER}},
        {"memecoin_extra_details": {"author": DEPLOYER}},
        {"memecoin_extra_details": {"author": DEPLOYER2}},
        {"memecoin_extra_details": {}},
        {},
    ]
    assert tracker.deployer_token_count(items, DEPLOYER) == 2
    assert tracker.deployer_token_count(items, DEPLOYER2) == 1
    assert tracker.deployer_token_count(items, "unknown") == 0
    assert tracker.deployer_token_count(items, "") == 0
    assert tracker.deployer_token_count(None, DEPLOYER) == 0


def test_deployer_token_count_case_insensitive():
    items = [{"memecoin_extra_details": {"author": DEPLOYER.upper()}}]
    assert tracker.deployer_token_count(items, DEPLOYER) == 1


# =================================================================
#                  Build message: badges integration
# =================================================================

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
            "metadata": {"symbol": "TKN", "name": "Tkn", "decimals": 9},
        },
    ],
    "reserves": ["1000000000", "1"],
}

DETAILS = {
    "metadata": {"address": JETTON, "name": "Tkn", "symbol": "TKN", "decimals": "9"},
    "admin": {"address": DEPLOYER},
}


@pytest.fixture
def tr(tmp_path):
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.inline_buttons = False
    cfg.state_file = tmp_path / "state.json"
    return tracker.Tracker(cfg)


def patch(t, *, coin):
    t.jetton_details = lambda addr: DETAILS
    t.x1000_coin_for = lambda addr, det: coin
    t.account_balance_ton = lambda addr: "10"


def test_message_includes_tax_line_when_present(tr):
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "Tkn", "ticker": "TKN", "description": "d"},
        "memecoin_extra_details": {"author": DEPLOYER},
        "buy_tax": 5,
        "sell_tax": 10,
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert "Tax (buy/sell)" in text
    assert "5% / 10%" in text


def test_message_includes_verification_line(tr):
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "Tkn", "ticker": "TKN", "description": "d"},
        "memecoin_extra_details": {"author": DEPLOYER},
        "verification_level": 3,
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert "Status" in text
    assert "Whitelisted" in text


def test_message_includes_dev_cluster_when_high(tr):
    """If the deployer has many tokens in the cached x1000 list, the
    Deployer block must surface the count + warning icon."""
    items = [
        {"memecoin_extra_details": {"author": DEPLOYER}, "asset": "0:a"},
        {"memecoin_extra_details": {"author": DEPLOYER}, "asset": "0:b"},
        {"memecoin_extra_details": {"author": DEPLOYER}, "asset": "0:c"},
        {"memecoin_extra_details": {"author": DEPLOYER}, "asset": "0:d"},
    ]
    tr._x1000_items = items
    tr._x1000_items_ts = 1e12
    coin = items[0]
    coin["metadata"] = {"name": "X", "ticker": "X", "description": "d"}
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert "Other tokens 24h" in text
    assert "⚠️" in text


def test_message_omits_dev_cluster_when_only_self(tr):
    tr._x1000_items = []
    tr._x1000_items_ts = 1e12
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "X", "ticker": "X", "description": "d"},
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(POOL)
    assert "Other tokens 24h" not in text


def test_stonfi_pool_uses_stonfi_link_in_text_mode(tr):
    sf_pool = {
        "address": "EQStonFiPool",
        "type": "stonfi",
        "_source": "stonfi",
        "lt": 0,
        "assets": [
            {"type": "native"},
            {
                "type": "jetton",
                "address": JETTON,
                "metadata": {"symbol": "T", "decimals": 9},
            },
        ],
        "reserves": ["1", "1"],
    }
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "X", "ticker": "X", "description": "d"},
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr, coin=coin)
    text, _, _ = tr.build_message(sf_pool)
    assert "https://app.ston.fi/pools/EQStonFiPool" in text
    assert "https://dedust.io/pools/" not in text


# =================================================================
#                           Inline buttons
# =================================================================

@pytest.fixture
def tr_buttons():
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.inline_buttons = True
    return tracker.Tracker(cfg)


def test_inline_buttons_returned_as_reply_markup(tr_buttons):
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "X", "ticker": "X", "description": "d"},
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr_buttons, coin=coin)
    text, _, kb = tr_buttons.build_message(POOL)
    assert kb is not None
    rows = kb["inline_keyboard"]
    # First row: chart button
    assert any(b["text"].endswith("x1000 Chart") for b in rows[0])
    # Second row: pool + tonviewer
    flat = [b for r in rows for b in r]
    assert any("DeDust" in b["text"] for b in flat)
    assert any("Tonviewer" in b["text"] for b in flat)
    # And the body should NOT carry the redundant link footer
    assert "Open x1000 Chart" not in text
    assert "DeDust Pool</a>" not in text


def test_inline_buttons_uses_stonfi_label(tr_buttons):
    sf_pool = {
        "address": "EQSF",
        "type": "stonfi",
        "_source": "stonfi",
        "lt": 0,
        "assets": [
            {"type": "native"},
            {"type": "jetton", "address": JETTON, "metadata": {"symbol": "T"}},
        ],
        "reserves": ["1", "1"],
    }
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "X", "ticker": "X", "description": "d"},
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr_buttons, coin=coin)
    _, _, kb = tr_buttons.build_message(sf_pool)
    flat = [b for r in kb["inline_keyboard"] for b in r]
    assert any("STON.fi" in b["text"] for b in flat)
    assert not any("DeDust" in b["text"] for b in flat)


def test_inline_buttons_disabled_keeps_links_in_text(tr):
    coin = {
        "asset": JETTON.lower(),
        "metadata": {"name": "X", "ticker": "X", "description": "d"},
        "memecoin_extra_details": {"author": DEPLOYER},
    }
    patch(tr, coin=coin)
    text, _, kb = tr.build_message(POOL)
    assert kb is None
    assert "Open x1000 Chart" in text


# =================================================================
#                       Graduation alert
# =================================================================

def test_graduation_message_basic(tr):
    item = {
        "asset": "0:graduated",
        "metadata": {
            "name": "Graduated Coin",
            "ticker": "GRAD",
            "image_url": "https://x.example/i.png",
            "address": "0:graduated",
        },
        "memecoin_extra_details": {
            "curve_ton_collected": "1050000000000",
            "curve_ton_max": "1050000000000",
        },
        "holders": 245,
        "market_cap": "156000",
    }
    text, image, _ = tr.build_graduation_message(item)
    assert "graduated on TON" in text
    assert "GRAD" in text
    assert "Graduated Coin" in text
    assert "1050 / 1050 TON" in text
    assert "Bonding curve filled" in text
    assert image == "https://x.example/i.png"


def test_check_graduations_fires_once_per_asset(tr):
    item = {
        "asset": "0:grad-token",
        "metadata": {"name": "G", "ticker": "G"},
        "memecoin_extra_details": {
            "curve_ton_collected": "1050000000000",
            "curve_ton_max": "1050000000000",
        },
    }
    tr._x1000_items = [item]
    tr._x1000_items_ts = 1e12
    tr.cfg.graduation_threshold_pct = Decimal("99")

    sent_calls: list[str] = []
    tr.send_graduation = lambda it: sent_calls.append(it["asset"])  # type: ignore

    n1 = tr._check_graduations()
    n2 = tr._check_graduations()
    assert n1 == 1
    assert n2 == 0
    assert sent_calls == ["0:grad-token"]
    assert "0:grad-token" in tr.state.graduated


def test_check_graduations_skips_below_threshold(tr):
    item = {
        "asset": "0:not-graduated",
        "metadata": {"name": "N", "ticker": "N"},
        "memecoin_extra_details": {
            "curve_ton_collected": "10000000000",  # 10 TON
            "curve_ton_max": "1050000000000",
        },
    }
    tr._x1000_items = [item]
    tr._x1000_items_ts = 1e12
    tr.cfg.graduation_threshold_pct = Decimal("99")
    tr.send_graduation = lambda it: None  # type: ignore
    assert tr._check_graduations() == 0
    assert "0:not-graduated" not in tr.state.graduated


def test_state_persists_graduated_set(tmp_path):
    p = tmp_path / "seen.json"
    s = tracker.State(p)
    s.seen.add("EQ1")
    s.graduated.add("0:asset1")
    s.save()

    s2 = tracker.State(p)
    assert s2.seen == {"EQ1"}
    assert s2.graduated == {"0:asset1"}

"""Tests for the Prometheus metrics + /healthz HTTP endpoints.

These exercise both the in-process counter increments (verified via the
exposition output) and the health endpoint's stale-tick logic.
"""
from __future__ import annotations

import json
import time
import urllib.request
from contextlib import closing

import pytest

import tracker


@pytest.fixture
def tr(tmp_path):
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.inline_buttons = False
    cfg.state_file = tmp_path / "state.json"
    return tracker.Tracker(cfg)


def test_metrics_no_op_when_prometheus_missing(monkeypatch, tmp_path):
    """When prometheus_client is patched out, alerts/observations don't blow up."""
    monkeypatch.setattr(tracker.metrics, "_PROM_AVAILABLE", False)
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.state_file = tmp_path / "state.json"
    tr = tracker.Tracker(cfg)

    tr.metrics.ticks_total.inc()
    tr.metrics.alerts_sent_total.labels("launch").inc()
    tr.metrics.tick_duration_seconds.observe(1.5)
    tr.metrics.pools_fetched.set(42)
    # render() returns empty bytes when prometheus is missing
    assert tr.metrics.render() == b""


def test_metrics_counter_increments(tr):
    """alerts_sent_total counter goes up after a successful send."""
    tr.http.post_telegram = lambda method, payload: {"ok": True}  # type: ignore[method-assign]
    tr.send_launch({
        "address": "EQpool",
        "assets": [
            {"type": "native"},
            {"type": "jetton", "address": "0:abc", "metadata": {"symbol": "ABC"}},
        ],
        "reserves": ["0", "0"],
    })
    body = tr.metrics.render().decode()
    assert 'tracker_alerts_sent_total{kind="launch"} 1.0' in body


def test_metrics_pools_fetched_gauge(tr):
    """pools_fetched gauge reflects the latest fetch size after a tick."""
    tr.fetch_pools = lambda: [  # type: ignore[method-assign]
        {"address": f"P{i}", "assets": [
            {"type": "native"},
            {"type": "jetton", "address": f"0:{i:064x}", "metadata": {"symbol": "X"}},
        ], "reserves": ["0", "0"]} for i in range(7)
    ]
    tr.send_launch = lambda pool: None  # type: ignore[method-assign]
    tr._check_graduations = lambda: 0  # type: ignore[method-assign]
    tr.tick()
    body = tr.metrics.render().decode()
    assert "tracker_pools_fetched 7.0" in body
    assert "tracker_ticks_total 1.0" in body


def test_health_endpoint_initial_ok():
    """A fresh tracker reports healthy until the first tick deadline elapses."""
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.poll_interval_seconds = 60
    # Pick an unprivileged port; let the server pick if 0
    cfg.metrics_port = _free_port()
    tr = tracker.Tracker(cfg)
    try:
        # Wait a moment for the http server thread to bind
        time.sleep(0.05)
        with closing(
            urllib.request.urlopen(
                f"http://127.0.0.1:{cfg.metrics_port}/healthz", timeout=2
            )
        ) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["ok"] is True
            assert data["last_tick_unixtime"] == 0.0
            assert data["stale_after_seconds"] == 180
    finally:
        if tr._metrics_server is not None:
            tr._metrics_server.shutdown()


def test_health_endpoint_stale_after_threshold():
    """Old last-tick timestamp -> 503 unhealthy."""
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.poll_interval_seconds = 1
    cfg.metrics_port = _free_port()
    tr = tracker.Tracker(cfg)
    try:
        # Force the last tick to look "old"
        assert tr._metrics_server is not None
        tr._metrics_server.last_tick_ts = time.time() - 600
        time.sleep(0.05)
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{cfg.metrics_port}/healthz", timeout=2
            )
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            assert e.code == 503
            data = json.loads(e.read().decode())
            assert data["ok"] is False
    finally:
        if tr._metrics_server is not None:
            tr._metrics_server.shutdown()


def test_metrics_endpoint_returns_prometheus_text():
    cfg = tracker.Config.from_env()
    cfg.skip_existing_on_first_run = False
    cfg.metrics_port = _free_port()
    tr = tracker.Tracker(cfg)
    try:
        tr.metrics.ticks_total.inc()
        time.sleep(0.05)
        with closing(
            urllib.request.urlopen(
                f"http://127.0.0.1:{cfg.metrics_port}/metrics", timeout=2
            )
        ) as resp:
            body = resp.read().decode()
            assert resp.status == 200
            assert "tracker_ticks_total" in body
    finally:
        if tr._metrics_server is not None:
            tr._metrics_server.shutdown()


def _free_port() -> int:
    """Grab an available TCP port for tests to avoid collisions."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

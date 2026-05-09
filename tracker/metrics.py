"""Prometheus metrics + lightweight /healthz HTTP server.

Metrics are best-effort: when ``prometheus_client`` is not installed the
counters become no-op stubs and the HTTP server is silently disabled, so
the bot keeps running unchanged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

log = logging.getLogger("ton-launch-tracker")


class _NoOpMetric:
    """Drop-in fallback so the bot survives without prometheus_client.

    Mirrors the small subset of the Counter/Histogram/Gauge API used by
    ``Tracker`` (labels/inc/observe/set) and silently swallows the calls.
    """

    def labels(self, *args: Any, **kwargs: Any) -> _NoOpMetric:
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None


try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only when lib is missing
    _PROM_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"


class Metrics:
    """Holds Prometheus metric objects keyed to one CollectorRegistry.

    A registry per Metrics instance keeps tests isolated (each ``Tracker``
    gets its own counters) without leaking state across the test session.
    """

    # Typed as Any so mypy is happy with both the prometheus_client classes
    # and the _NoOpMetric fallback being assigned to the same attribute.
    ticks_total: Any
    tick_errors_total: Any
    tick_duration_seconds: Any
    pools_fetched: Any
    alerts_sent_total: Any
    alert_errors_total: Any
    last_tick_unixtime: Any

    def __init__(self) -> None:
        if _PROM_AVAILABLE:
            self.registry: Any = CollectorRegistry()
            self.ticks_total = Counter(
                "tracker_ticks_total",
                "Number of polling ticks executed.",
                registry=self.registry,
            )
            self.tick_errors_total = Counter(
                "tracker_tick_errors_total",
                "Number of polling ticks that raised before completing.",
                registry=self.registry,
            )
            self.tick_duration_seconds = Histogram(
                "tracker_tick_duration_seconds",
                "Wall-clock duration of one tick (fetch+alerts).",
                buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
                registry=self.registry,
            )
            self.pools_fetched = Gauge(
                "tracker_pools_fetched",
                "Pools returned by the latest fetch (after filters).",
                registry=self.registry,
            )
            self.alerts_sent_total = Counter(
                "tracker_alerts_sent_total",
                "Telegram alerts dispatched.",
                ("kind",),
                registry=self.registry,
            )
            self.alert_errors_total = Counter(
                "tracker_alert_errors_total",
                "Telegram alert send failures (post-retry).",
                ("kind",),
                registry=self.registry,
            )
            self.last_tick_unixtime = Gauge(
                "tracker_last_tick_unixtime",
                "Unix timestamp of the last successful tick.",
                registry=self.registry,
            )
        else:
            self.registry = None
            stub: Any = _NoOpMetric()
            self.ticks_total = stub
            self.tick_errors_total = stub
            self.tick_duration_seconds = stub
            self.pools_fetched = stub
            self.alerts_sent_total = stub
            self.alert_errors_total = stub
            self.last_tick_unixtime = stub

    def render(self) -> bytes:
        if not _PROM_AVAILABLE or self.registry is None:
            return b""
        return generate_latest(self.registry)


class _MetricsHandler(BaseHTTPRequestHandler):
    server_version = "ton-launch-tracker/1.0"

    # ``log_message`` is noisy by default; route to our logger at debug.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug("metrics http: " + format, *args)

    def do_GET(self) -> None:  # noqa: N802 — stdlib API
        srv: Any = self.server  # _MetricsServer
        path = (self.path or "/").split("?", 1)[0]

        if path == "/healthz":
            stale_after = max(1, int(srv.poll_interval * 3))
            last = float(srv.last_tick_ts or 0.0)
            now = time.time()
            healthy = last == 0.0 or (now - last) <= stale_after
            body = json.dumps(
                {
                    "ok": healthy,
                    "last_tick_unixtime": last,
                    "stale_after_seconds": stale_after,
                }
            ).encode()
            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/metrics":
            body = srv.metrics.render()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _MetricsServer(HTTPServer):
    def __init__(
        self,
        addr: tuple[str, int],
        metrics: Metrics,
        poll_interval: int,
    ) -> None:
        super().__init__(addr, _MetricsHandler)
        self.metrics = metrics
        self.poll_interval = poll_interval
        self.last_tick_ts: float = 0.0


def start_metrics_server(
    metrics: Metrics, port: int, poll_interval: int
) -> Optional[_MetricsServer]:
    """Start the metrics+health HTTP server in a daemon thread.

    Returns the server instance (so callers can update last_tick_ts) or
    None when port==0 (disabled).
    """
    if port <= 0:
        return None
    server = _MetricsServer(("0.0.0.0", port), metrics, poll_interval)
    thread = threading.Thread(
        target=server.serve_forever, name="metrics-http", daemon=True
    )
    thread.start()
    log.info("Metrics HTTP server listening on :%d", port)
    return server

"""Financial module: pattern detection, network, transaction summary."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.financial import build_transfer_network, detect_patterns, summarize_transactions

ROLES = {
    "source_account": "source_account_id",
    "destination_account": "destination_account_id",
    "amount_source": "source_amount",
    "status": "transaction_status",
}


def _frame() -> pd.DataFrame:
    rows = []
    t0 = datetime(2025, 3, 1, 10, 0)

    def add(src: str, dst: str, amt: float, dt: datetime, st: str = "success") -> None:
        rows.append({
            "source_account_id": src,
            "destination_account_id": dst,
            "source_amount": amt,
            "initiated_at_utc": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "transaction_status": st,
        })

    # ordinary traffic
    for i in range(250):
        add(f"A{i % 30:02d}", f"B{i % 40:02d}", 500 + (i * 37) % 4000,
            t0 + timedelta(hours=i * 3))
    # large legit settlements (lift the data-derived threshold)
    for k in range(15):
        add(f"A{10 + k:02d}", f"B{20 + k % 15:02d}", 300_000 + k * 1_000,
            t0 + timedelta(days=k))
    # structuring: five near-threshold payments inside two hours
    for k in range(5):
        add("A90", "B99", 95_000 + k * 1_000, t0 + timedelta(minutes=k * 25))
    # fan-out burst to 30 counterparties in one hour
    for k in range(30):
        add("A91", f"B7{k:02d}", 8_000, t0 + timedelta(minutes=k))
    # three-hop cycle
    add("A92", "A93", 500_000, t0 + timedelta(hours=1))
    add("A93", "A94", 500_000, t0 + timedelta(hours=2))
    add("A94", "A92", 500_000, t0 + timedelta(hours=3))
    # rapid pass-through
    add("A95", "A96", 400_000, t0 + timedelta(hours=4))
    add("A96", "A97", 380_000, t0 + timedelta(hours=4, minutes=20))
    return pd.DataFrame(rows)


def test_detect_patterns_finds_injected_shapes():
    res = detect_patterns(_frame(), ROLES, "initiated_at_utc")
    assert {"findings", "methodology", "disclaimer", "total"} <= set(res)
    kinds = {f["kind"] for f in res["findings"]}
    assert len(res["findings"]) >= 3
    assert "circular_transfer" in kinds
    assert "amount_anomaly" in kinds
    for f in res["findings"]:
        assert f["severity"] in ("info", "medium", "high")
        assert f["title"] and f["evidence"]
        assert f["method"]


def test_detect_patterns_without_roles_is_graceful():
    res = detect_patterns(_frame(), {}, "initiated_at_utc")
    assert isinstance(res["findings"], list)
    assert res["disclaimer"]


def test_build_transfer_network():
    net = build_transfer_network(_frame(), ROLES)
    assert net.status == "completed"
    assert net.node_count >= 2
    assert net.edge_count >= 1
    assert len(net.nodes) == net.node_count
    assert len(net.edges) == net.edge_count
    assert "density" in net.metrics


def test_network_requires_account_roles():
    net = build_transfer_network(_frame(), {})
    assert net.status == "unavailable"
    assert "account" in net.reason.lower()


def test_summarize_transactions():
    df = _frame()
    summary = summarize_transactions(df, ROLES, "initiated_at_utc")
    assert summary.status == "completed"
    assert summary.metrics["row_count"] == len(df)
    assert summary.metrics["total_volume_completed"] > 0
    assert summary.metrics["distinct_source_accounts"] >= 2


def test_summary_without_amount_role_is_unavailable():
    summary = summarize_transactions(_frame(), {}, "initiated_at_utc")
    assert summary.status == "unavailable"

#!/usr/bin/env python3
"""Standalone tests for the Darkbloom integration's pure logic.

Run: python3 tests/test_logic.py   (no pytest needed)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "darkbloom"))

import logic  # noqa: E402

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)


def row(hours_ago, amount_micro, model="glm-5.3-flash", rid=None):
    t = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"i": rid, "t": t, "m": model, "u": amount_micro}


def test_exact_window():
    # 6 jobs across the last 1h, plus an older row that lets the cache span 1h
    rows = [
        row(0.2, 1000), row(0.5, 2000), row(0.9, 3000),
        row(2.0, 10_000_000),
    ]
    w = logic.compute_window(rows, 1, NOW)
    assert w["exact"] is True
    assert w["jobs"] == 3
    assert w["earned_micro_usd"] == 6000
    assert w["shown_micro_usd"] == 6000
    assert abs(w["rate_usd_h"] - 6000 / 1e6) < 1e-12
    print("  ok: exact window")


def test_exact_zero_window():
    # cache spans the window but no jobs in it -> exact zero, rate 0
    rows = [row(3.0, 1000)]
    w = logic.compute_window(rows, 1, NOW)
    assert w["exact"] is True
    assert w["jobs"] == 0 and w["rate_usd_h"] == 0.0
    print("  ok: exact zero window")


def test_extrapolated_window():
    # window is 1h; cache only reaches 0.75h back, jobs fill that 0.75h
    rows = [row(0.25, 3000), row(0.5, 3000), row(0.75, 3000)]
    w = logic.compute_window(rows, 1, NOW)
    assert w["exact"] is False
    # visible: 9000 micro over 0.75h span -> 12000 micro/h rate; shown = total + per_s*missing
    # missing = 0.25h = 900s -> est shown = 9000 + (9000/2700)*900 = 12000
    assert abs(w["shown_micro_usd"] - 12000) < 1e-6
    assert abs(w["rate_usd_h"] - 0.012) < 1e-9
    print("  ok: extrapolated window matches hand math")


def test_unknown_window():
    # empty cache -> nothing knowable about the window -> rate None.
    # (With any row present, exact=False implies that row is inside the
    # window, so the extrapolated rate always exists.)
    w = logic.compute_window([], 24, NOW)
    assert w["exact"] is False
    assert w["jobs"] == 0 and w["rate_usd_h"] is None
    # a lone recent row in a 24h window is instead an extrapolated estimate
    w2 = logic.compute_window([row(0.5, 1000)], 24, NOW)
    assert w2["exact"] is False and w2["rate_usd_h"] is not None
    print("  ok: unknown window -> None rate, partial window -> estimate")


def test_reward_split():
    rows = [
        row(0.5, 5000, model="glm-5.3-flash"),
        row(0.4, 182, model="base_reward"),
    ]
    w = logic.compute_window(rows, 1, NOW)
    assert w["jobs"] == 2  # reward rows are still ledger rows, but:
    assert logic.is_reward("base_reward") and not logic.is_reward("glm-5.3-flash")
    print("  ok: reward detection")


def test_merge_dedup():
    cache = {}
    a = [row(0.1, 100, rid=1), row(0.2, 200, rid=2)]
    b = [row(0.1, 100, rid=1), row(0.3, 300, rid=3)]
    first = logic.merge_new_rows(cache, a)
    second = logic.merge_new_rows(cache, b)
    assert len(cache) == 3
    assert [r["i"] for r in first] == [1, 2]
    assert [r["i"] for r in second] == [3]
    print("  ok: merge dedupes by id")


def test_prune_rows():
    cache = {str(i): row(i, 100, rid=i) for i in (0.1, 5, 30)}  # 30h old
    logic.prune_rows(cache, NOW)
    assert set(cache) == {"0.1", "5"}  # 30h > ROW_HOURS=26 -> dropped
    print("  ok: row pruning by age")


def test_hourly_buckets():
    hourly = {}
    new = [row(0.4, 1000, rid=1), row(0.6, 2000, rid=2), row(1.4, 500, rid=3)]
    logic.add_hourly(hourly, new)
    h1 = (NOW - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat()
    h2 = (NOW - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0).isoformat()
    assert hourly[h1]["u"] == 3000   # 0.4h and 0.6h ago both fall in the 11:00 bucket
    assert hourly[h1]["n"] == 2
    assert hourly[h2]["u"] == 500
    logic.prune_hourly(hourly, NOW)
    assert all(isinstance(v["u"], int) for v in hourly.values())
    print("  ok: hourly buckets accumulate and prune")


def test_compute_windows_keys():
    rows = {"1": row(0.5, 100, rid=1), "2": row(11, 100, rid=2)}
    windows = logic.compute_windows(rows, NOW)
    assert sorted(windows) == [1, 2, 3, 4, 6, 12, 24]
    assert windows[1]["exact"] is True
    assert windows[12]["exact"] is False  # oldest row (11h) is newer than the 12h cutoff
    assert windows[24]["exact"] is False
    print("  ok: all seven windows present")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"ALL {len(tests)} TESTS PASSED")

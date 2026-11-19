"""Pure logic for the Darkbloom integration: no Home Assistant imports.

Kept import-clean so it can be unit-tested without a running HA instance.
All money values are micro-USD (int) unless the key name says _usd.
"""
from __future__ import annotations

from datetime import datetime, timedelta

WINDOW_HOURS = (1, 2, 3, 4, 6, 12, 24)
ROW_HOURS = 26      # keep per-row data long enough to span the 24h window
HOURLY_DAYS = 8     # keep hourly aggregates for trend/history fills
MAX_ROWS = 20000    # failsafe cap on the row cache


def parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp (with Z) into an aware UTC datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def is_reward(model: str) -> bool:
    """`base_reward` rows are floor payouts, not inference jobs."""
    return "reward" in model.lower()


def compress_earnings(earnings: list[dict]) -> list[dict]:
    """Reduce API rows to the four fields the math needs."""
    return [
        {"i": e["id"], "t": e["created_at"], "m": e["model"], "u": e["amount_micro_usd"]}
        for e in earnings
    ]


def merge_new_rows(rows: dict[str, dict], compressed: list[dict]) -> list[dict]:
    """Insert unseen rows by id; return the list that was actually new."""
    new: list[dict] = []
    for r in compressed:
        rid = str(r["i"])
        if rid not in rows:
            rows[rid] = r
            new.append(r)
    return new


def prune_rows(rows: dict[str, dict], now: datetime) -> None:
    """Drop rows older than ROW_HOURS, then enforce the hard cap by age."""
    cutoff = now - timedelta(hours=ROW_HOURS)
    for rid in [k for k, v in rows.items() if parse_ts(v["t"]) < cutoff]:
        del rows[rid]
    if len(rows) > MAX_ROWS:
        keep = sorted(rows.values(), key=lambda r: r["t"])[-MAX_ROWS:]
        rows.clear()
        for r in keep:
            rows[str(r["i"])] = r


def add_hourly(hourly: dict[str, dict], new_rows: list[dict]) -> None:
    """Accumulate micro-USD and job counts into hour buckets (UTC hour keys)."""
    for r in new_rows:
        key = parse_ts(r["t"]).replace(minute=0, second=0, microsecond=0).isoformat()
        bucket = hourly.setdefault(key, {"u": 0, "n": 0})
        bucket["u"] += r["u"]
        bucket["n"] += 1


def prune_hourly(hourly: dict[str, dict], now: datetime) -> None:
    cutoff = (now - timedelta(days=HOURLY_DAYS)).replace(
        minute=0, second=0, microsecond=0
    )
    for key in [k for k in hourly if datetime.fromisoformat(k) < cutoff]:
        del hourly[key]


def compute_window(
    rows: list[dict], hours: int, now: datetime
) -> dict:
    """Window stats over row dicts (any order; sorted internally by `t`).

    exact: True when the cache spans the whole window (oldest row <= cutoff).
    rate_usd_h: None when the cache cannot say anything about the window
    (younger than the window AND no jobs in it); otherwise the (possibly
    extrapolated) rate in USD/hour.
    """
    rows_asc = sorted(rows, key=lambda r: r["t"])
    cutoff = now - timedelta(hours=hours)
    inwin = [r for r in rows_asc if parse_ts(r["t"]) >= cutoff]
    total = sum(r["u"] for r in inwin)
    jobs = len(inwin)
    by_src: dict[str, dict] = {}
    for r in inwin:
        src = by_src.setdefault(r["m"], {"jobs": 0, "earned_micro_usd": 0})
        src["jobs"] += 1
        src["earned_micro_usd"] += r["u"]

    exact = bool(rows_asc) and parse_ts(rows_asc[0]["t"]) <= cutoff
    shown = total
    rate: float | None = None

    if exact:
        rate = total / 1e6 / hours
    elif inwin:
        oldest = parse_ts(inwin[0]["t"])
        span_s = (now - oldest).total_seconds()
        if span_s > 0:
            per_s = total / span_s
            shown = total + per_s * (oldest - cutoff).total_seconds()
        rate = shown / 1e6 / hours

    return {
        "hours": hours,
        "earned_micro_usd": total,
        "shown_micro_usd": shown,
        "jobs": jobs,
        "exact": exact,
        "rate_usd_h": rate,
        "sources": by_src,
    }


def compute_windows(
    rows: dict[str, dict], now: datetime
) -> dict[int, dict]:
    rows_asc = sorted(rows.values(), key=lambda r: r["t"])
    return {h: compute_window(rows_asc, h, now) for h in WINDOW_HOURS}

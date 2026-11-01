"""Bounded EXP0018.1 journal reports; no collection, source writes or live orders."""

import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from premetar.research.battle_store import read_battle
from premetar.research.entry_reconstruction_clocks import known_clock
from premetar.research.entry_timing_monitor import ROOT
from premetar.research.surge_hunter import DIRECTORY
from premetar.research.trader_store import readonly_connection


def export() -> dict[str, Any]:
    records = read_battle(DIRECTORY, limit=100000)
    surges = [r["payload"] for r in records if r["kind"] == "SURGE_DETECTED"]
    windows = [r["payload"] for r in records if r["kind"] == "SURGE_ENTRY_WINDOW"]
    associations = [r["payload"] for r in records if r["kind"] == "SURGE_ASSOCIATION_REVIEW"]
    arrivals = [r["payload"] for r in records if r["kind"] == "SURGE_ARRIVAL_REVIEW"]
    quotes = [r["payload"] for r in records if r["kind"] == "SURGE_BOOK_STATE"]
    sessions = []
    quality: list[dict[str, Any]] = []
    for path in sorted((DIRECTORY / "books").glob("*.sqlite3"))[:30]:
        c = readonly_connection(path)
        try:
            run = c.execute(
                "SELECT payload FROM events WHERE kind='RUN' ORDER BY id LIMIT 1"
            ).fetchone()
            stop = c.execute(
                "SELECT payload FROM events WHERE kind='STOP' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not run:
                continue
            manifest = json.loads(run[0])
            done = json.loads(stop[0]) if stop else None
            health = [
                dict(received_at=t, **json.loads(p))
                for t, p in c.execute(
                    "SELECT received_at,payload FROM events WHERE kind='STREAMHEALTH' ORDER BY id"
                )
            ]
            frames = dict(c.execute("SELECT kind,count(*) FROM events GROUP BY kind"))
            reconnects = sum(h.get("state") == "RECONNECTING" for h in health)
            sessions.append(
                dict(
                    capture_id=manifest["capture_id"],
                    contracts=len(manifest["markets"]),
                    tokens=len(manifest["tokens"]),
                    token_ids=manifest["tokens"],
                    markets=[
                        dict(
                            condition_id=m["condition_id"],
                            station=m.get("station"),
                            settlement_day=m.get("settlement_day"),
                            title=m.get("metadata_payload", {}).get("question"),
                        )
                        for m in manifest["markets"]
                    ],
                    started_at=manifest["created_at"],
                    ended_at=done.get("ended_at") if done else None,
                    duration_seconds=done.get("actual_duration_seconds") if done else None,
                    reconnects=reconnects,
                    counts=frames,
                    status="BOUNDED_SESSION_COMPLETE"
                    if done
                    else "OPEN_SESSION_NOT_LIVENESS_PROOF",
                    storage_bytes=sum(
                        p.stat().st_size for p in (path, Path(str(path) + "-wal")) if p.exists()
                    ),
                    integrity=c.execute("PRAGMA integrity_check").fetchone()[0],
                )
            )
            quality.extend(dict(capture_id=manifest["capture_id"], **h) for h in health)
        finally:
            c.close()
    well = json.loads(
        (ROOT / "reports/trader/wellington_surge_forensic.json").read_text(encoding="utf-8")
    )
    summary = dict(
        surges=len(surges),
        entries=len(windows),
        associations=sum(
            bool(
                r.get("association", {}).get("source_clock_following_trade_ids")
                or r.get("association", {}).get("detection_following_trade_ids")
            )
            for r in associations
        ),
        association_reviews=len(associations),
        supported_fills=0,
        matched_controls=0,
        market_day_clusters=len({(s.get("condition_id"), s.get("settlement_day")) for s in surges}),
        source_packets=len(
            {
                (s.get("condition_id"), s.get("source_event_id"), s.get("received_at"))
                for s in surges
            }
        ),
        complete_pre_entry_windows=sum(
            w.get("recorded_session_window_complete") is True for w in windows
        ),
        window_scope="RECORDED_SESSION_BEFORE_SOURCE_REPORTED_TIME_NOT_VERIFIED_MATCHING_TIME",
        events_by_kind=dict(Counter(s["kind"] for s in surges)),
        independent_entry_probability=None,
        shadow_profit=None,
        matched_comparison_status="INSUFFICIENT_DATA",
    )
    now = datetime.now(UTC)
    last_by_token = {}
    for q in quotes:
        last_by_token[q["token_id"]] = q
    freshness = [
        dict(
            token_id=t,
            condition_id=q.get("condition_id"),
            last_book_receipt=q["received_at"],
            age_seconds=(now - known_clock(q["received_at"])).total_seconds(),
            state="STALE_BOOK"
            if (now - known_clock(q["received_at"])).total_seconds() > 10
            else q["state"],
        )
        for t, q in sorted(last_by_token.items())
    ]
    result = dict(
        version="SURGE-HUNTER-v1",
        published_at=now.isoformat(),
        mode="OBSERVED_BOUNDED_SESSIONS_NOT_PERSISTENT",
        summary=summary,
        sessions=sessions,
        session=sessions[-1] if sessions else {},
        events=surges[-50:],
        freshness=freshness,
        wellington=well,
        connection_quality=quality,
        journal_read_metadata=getattr(records, "metadata", {}),
        stage="INTERESTING_EVENTS_AND_FEASIBILITY_ONLY_NOT_FILLED_TRADES",
    )
    output = ROOT / "reports/trader"
    output.mkdir(parents=True, exist_ok=True)
    (output / "exp0018_surge_hunter.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for name, rows, fields in [
        (
            "arrival_feasibility",
            arrivals,
            [
                "surge_id",
                "latency_seconds",
                "decision_time",
                "modeled_arrival",
                "review_time",
                "feasibility",
                "maximum_supported_quantity",
                "supported_fill_quantity",
                "net_profit",
            ],
        ),
        (
            "surge_events",
            surges,
            [
                "surge_id",
                "received_at",
                "condition_id",
                "token_id",
                "outcome",
                "kind",
                "field",
                "before",
                "after",
                "delta",
                "elapsed_seconds",
                "boundary_kind",
            ],
        ),
        (
            "pre_entry_windows",
            windows,
            [
                "trade_id",
                "source_trade_timestamp",
                "first_detection",
                "source_precision_seconds",
                "coverage",
            ],
        ),
        (
            "entry_associations",
            associations,
            ["surge_id", "condition_id", "settlement_day", "matched_control_status"],
        ),
        (
            "connection_quality",
            quality,
            [
                "capture_id",
                "received_at",
                "state",
                "connection_id",
                "error_class",
                "session_seconds",
                "backoff_seconds",
                "received_close_code",
                "sent_close_code",
            ],
        ),
        (
            "negative_controls",
            associations,
            ["surge_id", "condition_id", "settlement_day", "matched_control_status"],
        ),
        (
            "shadow_feasibility",
            [
                dict(surge_id=s["surge_id"], received_at=s["received_at"], **s["feasibility"])
                for s in surges
            ],
            [
                "surge_id",
                "received_at",
                "classification",
                "reason",
                "direct_no_ask",
                "theoretical_no_from_yes_bid",
                "direct_quantity",
                "complementary_quantity",
                "supported_fill_quantity",
                "net_profit",
            ],
        ),
    ]:
        with (output / f"exp0018_{name}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    lines = [
        "# EXP0018.1 — Surge Hunter",
        "",
        f"Generated {now.isoformat()}. Bounded prospective capture, separate retrospective Wellington replay.",
        "",
        "## Actual session evidence",
        "",
        "| Contracts/tokens | Duration s | BOOK / DELTA | Reconnects | Storage bytes | Integrity |",
        "|---|---:|---|---:|---:|---|",
    ]
    lines += [
        f"|{s['contracts']}/{s['tokens']}|{s['duration_seconds']}|{s['counts'].get('BOOK', 0)}/{s['counts'].get('WS_DELTA', 0)}|{s['reconnects']}|{s['storage_bytes']}|{s['integrity']}|"
        for s in sessions
    ]
    lines += [
        "",
        "## Prospective independent detector",
        "",
        "```json",
        json.dumps(summary, indent=2),
        "```",
        "",
        "Mirrored YES/NO and different threshold fields are not independent decisions. Source packets and market/day clusters are reported separately. No-entry labels remain delayed/censored. Missing market-age, exact settlement-window and verified METAR context prevent a valid matched-control effect estimate; no entry-probability percentage is reported.",
        "",
        "## Wellington: new discriminating evidence",
        "",
        "Exact RAW WS BUY transaction hash joins the canonical receipt. Public BUY receipt08:58:29.775972 precedes the genuine bid insertion08:58:29.863130 by87.158ms; exchange timestamps also order BUY before bid (54ms). Data API time08:58:33 equals block timestamp, not an independently verified matching-engine clock. This specific bid jump is not evidence of a signal preceding the observed execution print.",
        "The executed BUY is BUY/BUY mint:207.78NO funded by196.0404pUSD from HighTempTation plus11.7396pUSD from five YES makers. Effective NO fills0.92/0.93/0.94/0.95/0.98. SELL207.78at0.99 is also chain-verified TAKER. Gross cash difference9.6618before unknown external costs, conditional inventory association; no copy fill or net-profit claim.",
        "",
        "## Reconnect diagnosis",
        "",
        "Confirmed amplifier: baseline backoff reset after each handshake, so short-lived sessions repeatedly waited only3s. New experiment opts into60s stable-session reset; synthetic regression verifies3/6/12s retry progression. Existing default unchanged. Old disconnect root cause remains UNKNOWN: original logs have ConnectionClosedError but no close frames/codes. Small clean sessions cannot establish causation by cohort size. No healthy process restarted.",
        "",
        "## Frozen research definitions",
        "",
        "Same-token/same-session quote changes>=0.10 within<=5s; depth change>=100shares and>=50%; spread change>=0.05. Initial/gap states cannot trigger. Snapshot transitions explicitly labeled. Empty sides remain distinct from missing data. Complementary1-bidYES is theoretical without exchange/fee/arrival proof; no optimistic maker queue fills. Real source event histories are persisted before wallet attribution, not selected after future trades.",
        "",
        "## Operational limitations",
        "",
        "Recorded session duration can exceed300s while event activity is sparse; PONG is not a depth freshness certificate. Current old quotes are stale, not current executable books. No complete actual pre-entry event window is claimed without an entry and continuity evidence. Continuous command cycles finite sessions with explicit gaps; autostart was not installed. Storage caps stop rather than deleting research evidence. See EXP0018_SURGE_OPERATIONS.md for budgets/commands.",
    ]
    (output / "exp0018_surge_hunter.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    target = ROOT / "src/premetar/dashboard/static/surge_hunter_summary.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    temp.replace(target)
    return result


if __name__ == "__main__":
    r = export()
    print(json.dumps(dict(summary=r["summary"], sessions=r["sessions"]), indent=2))

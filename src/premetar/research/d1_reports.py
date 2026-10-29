"""Deterministic EXP0016 immutable-journal report; unknown is never zero profit."""

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from premetar.research.battle_store import read_battle
from premetar.research.d1_monitor import DIRECTORY, ROOT, view


def generate(
    at: datetime, directory: Path = DIRECTORY, output: Path | None = None
) -> dict[str, Any]:
    output = output or ROOT / "reports/research/exp0016"
    output.mkdir(parents=True, exist_ok=True)
    records = read_battle(directory, at, limit=20000)
    data = view(at, directory)
    data["event_counts"] = dict(Counter(e["kind"] for e in records))
    candidates = [e for e in records if e["kind"] == "D1_CANDIDATE"]
    reasons = Counter(
        reason for e in candidates for reason in e["payload"]["candidate"].get("reasons", [])
    )
    data["candidate_rejection_reasons"] = dict(reasons)
    data["observed_settlement_dates"] = sorted(
        {e["payload"]["settlement_date"] for e in candidates}
    )
    data["independent_completed_days"] = 0
    (output / "summary.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    for filename, rows in [
        ("forecasts.csv", data["forecasts"]),
        ("markets.csv", data["markets"]),
        (
            "candidates.csv",
            [dict(id=e["id"], created_at=e["at"], **e["payload"]) for e in candidates],
        ),
    ]:
        fields = sorted({key for row in rows for key in row}) or ["status"]
        with (output / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(
                {
                    k: json.dumps(v, sort_keys=True, ensure_ascii=True)
                    if isinstance(v, (dict, list))
                    else v
                    for k, v in row.items()
                }
                for row in rows
            )
    lines = [
        "# EXP-0016 — Tomorrow forecast versus market",
        f"\nSnapshot cutoff UTC: {at.isoformat()}. Settlement date Warsaw: {data['settlement_date']}.",
        "\nProspective raw-first capture only. No real orders. CALIBRATION PENDING; no probability, EV or positive edge is established.",
        "\n## Model availability\n",
        "Model | Family | Daily API Tmax | Hourly point max | First collector receipt | Original run",
        "---|---|---:|---:|---|---",
    ]
    lines += [
        f"{m['model']} | {m['family']} | {m['daily_tmax_c']} | {m['hourly_point_max_c']} | {m['first_received']} | UNKNOWN"
        for m in data["forecasts"]
    ]
    lines += [
        "\n## Actual tomorrow contracts\n",
        "Outcome | YES bid/ask | NO bid/ask | Rules | Candidate",
        "---|---|---|---|---",
    ]
    lines += [
        f"{m.get('outcome')} | {m['yes_book'].get('best_bid')}/{m['yes_book'].get('best_ask')} | {m['no_book'].get('best_bid')}/{m['no_book'].get('best_ask')} | {m['rules_status']} | {','.join(m['candidate'].get('reasons', []))}"
        for m in data["markets"]
    ]
    lines += [
        "\n## Required research answers\n",
        "1. Available models/receipt timestamps are listed above. Original initialization and publication timestamps are not supplied by this live endpoint.",
        "2. Forecast/price disagreement is descriptive only: no calibrated probability exists, so a mispricing frequency cannot yet be measured.",
        "3. Decision-book depth is conditional. See candidate CSV for ask-side quantities, freshness and rejected cases. No arrival fill is inferred.",
        "4. D-1 settlement Tmax error/accuracy: INSUFFICIENT VERIFIED ARCHIVED_RUN_AND_OFFICIAL_TARGET PAIRS.",
        "5. P(NO9C | forecast10-13C): NOT IDENTIFIABLE. Consensus is not probability.",
        "6. Overnight/D0 repricing: prospective multi-day follow-up required; no reconstructed profitable history.",
        "7. Best OOS exit: NOT IDENTIFIABLE; three frozen triggers are recorded, execution remains blocked until calibration promotion.",
        "8. D1 committed capital/known inventory:0/0, because entries are blocked. Tail losses and capital-time performance are unmeasured, not proven absent.",
        "9. No matched completed independent settlement days to establish D1 superiority over SIMPLE/WEATHER/HYBRID. Equal100USD/5USDorder/25USDday budgets are frozen.",
        "10. No positive prospective economic edge established.",
        "\n## Accounting and limits\n",
        f"Captured candidate evaluations:{len(candidates)} (not independent trades). Completed identified days:0. Negative reasons:{dict(reasons)}.",
        "Rule parser policy (only certified per contract when captured clauses match): qualifying routine observation T-remark maximum with body fallback, SPECI exclusion, warmer ties and correction cutoff. Empty/unverified markets do not establish those rules. This is not silently equated with true continuous daily Tmax or only nominal routine integers.",
        "Existing audit:14 archived runs (7 ICON Global/7 ICON EU,21-27Oct00UTC) downloaded28Oct. Their availability is APPROXIMATE_REPLAY with unknown publication and assumed init+6h. Earlier hourly study has94 independent targets/5days, but0 verified final settlement Tmax days. Thus0 audited D-1 forecast/final-settlement calibration pairs; do not confuse missing eligible pairs with no archived forecasts. Related ICON/ECMWF models are grouped, not five independent votes.",
        "D0/D1 are local calendar dates, including DST. Current snapshots and book statuses may be stale. Existing collectors untouched. The independent bounded journal stops at storage cap rather than deleting evidence.",
        f"Read limits: {records.metadata}",
    ]
    (output / "exp0016_d1_forecast_mispricing.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return dict(
        cutoff=at.isoformat(),
        output=str(output),
        models=len(data["forecasts"]),
        markets=len(data["markets"]),
        candidates=len(candidates),
        probability="CALIBRATION_PENDING",
    )

"""Offline capture integrity and compact evidence export; never fabricates live data."""

import argparse
import base64
import hashlib
import json
import sqlite3
from pathlib import Path


def verify(database: Path) -> dict:
    with sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        raw = [dict(row) for row in connection.execute("SELECT * FROM raw_payloads")]
        for row in raw:
            envelope = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
            digest = hashlib.sha256(base64.b64decode(envelope["body_base64"])).hexdigest()
            assert digest == envelope["sha256"] == row["sha256"], row["id"]
            assert envelope["id"] == row["id"] and envelope["run_id"] == row["run_id"]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        samples = [
            dict(row)
            for row in connection.execute(
                "SELECT station_icao,source,product_type,event_time,report_time,source_publish_time,source_receipt_time,collector_request_start_time,collector_receive_time,temperature_c,raw_sha256,startup_censored FROM observations WHERE id IN (SELECT max(id) FROM observations GROUP BY station_icao,source) ORDER BY source,station_icao"
            )
        ]
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "runs",
                "raw_payloads",
                "observations",
                "canonical_reports",
                "report_receipts",
                "errors",
            )
        }
    return {
        "raw_payloads_sha256_verified": len(raw),
        "sqlite_integrity": "ok",
        "foreign_keys": "ok",
        "counts": counts,
        "samples": samples,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/premetar.sqlite3"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.database)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)

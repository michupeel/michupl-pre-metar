# Decisions

## 2026-10-21 — DEC-0001: independent prospective baseline

Create a separate Git repository inside the available writable workspace. No
parent-lab imports, process changes, credential access or trading. Use Python3.12,
uv, httpx, Pydantic, Typer/Rich, SQLite WAL and Polars exports. User authorized
implementation and local commits; no existing remote is assumed.

## DEC-0002: availability is observed, not inferred

Do not fill missing publish timestamps with receive time. Initial snapshots and
backfilled rows are censored. Keep every source receipt and full report identity.
Match within run using monotonic clocks. Source race measures collector reception
among configured paths, not global publication. A request-start lead only flags
request overlap; it does not bound publication time.

## DEC-0003: legal no-key M1, disabled optional adapters

Enable verified AWC, DWD01262 and direct KNMI EHAM full-report endpoints. DWD
TT_10 is an experimental candidate with unverified sensor parity and potentially
hourly publication. KNMI10min and METAR.ws stay visibly disabled, preserving the
no-new-subscription baseline and avoiding a second use of an existing WS key.

## DEC-0004: durable raw before derived results

One dedicated worker serializes fsynced raw writes, parsing and transactional DB
updates. Independent HTTP loops can continue while another payload is stored.
No historical timestamp fabricates a realtime observation. Parser failures retain
raw; infrastructure failures stop visibly rather than silently losing evidence.

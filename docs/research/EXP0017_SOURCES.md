# EXP0017 — bounded historical source capture

The frozen EXP0012 trader database is opened with SQLite `mode=ro` and
`query_only=ON`. No running process or live database is modified. Original
EXP0012 captures and their first-receipt evidence remain unchanged.

## Exact market identities

Official [Gamma list-markets documentation](https://docs.polymarket.com/api-reference/markets/list-markets)
allows up to100 `condition_ids` per identifier lookup and `closed=any` for both
open and closed markets. We requested all4,540 distinct weather NO BUY conditions
from4,751 frozen economic records in46 batches, `limit=100`, with repeated
`condition_ids` parameters. Every requested condition returned exactly matching
metadata, and all4,751 rows also match an actual binary token in that condition.

Actual execution:46 successful public requests,34,740,841 raw body bytes.
Fifty distinct reference ICAO stations were extracted from those exact rules;
none were inferred from a city name. The existing verified `station_from_rules`
parser rejects contradictory/missing station references. Captures are current
retrospective identity evidence, not proof that those descriptions or present
resolution metadata were known before an older trade.

Output: ignored `data/research/exp0017/markets.json`, containing original market
objects, actual metadata capture UTC, raw SHA256 and request records. Every HTTP
body is preserved before JSON parsing in `evidence/{sha256}.raw`; request metadata
retains original URL, actual request/receipt clocks, status, size and hash.

## Historical nominal METAR archive

The [Iowa Environmental Mesonet download service](https://mesonet.agron.iastate.edu/request/download.phtml)
is a university historical archive of disseminated raw observations, **not an
official original-publication-time source**. Its
[backend documentation](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help)
documents repeated station parameters, `data=metar`, UTC `sts`/`ets`, `tz=UTC`,
`format=onlycomma`, routine report type3 and special type4. Its per-IP throttle is
one request per second. Requests here are sequential, at least1.05seconds apart,
with no automatic retry, a60second timeout, maximum100 cached/new requests and
200MB aggregate preserved body budget. HTTP429/503 halts further source work.

Stations were grouped in batches of at most8, using each batch's earliest/latest
trade clocks plus two days for schedule/neighbor coverage. All50 explicit stations
were requested; US domestic aliases are additionally queried, but rows are accepted
only when the original TAC contains the exact requested ICAO. No airport is inferred
from the archive's short station ID. Report nominal UTC must agree with original
TAC DDHHMMZ. Routine/special query paths are separate and preserved, including COR
text. The archive may not preserve every superseded correction; it cannot certify
historical correction availability or original receipt order.

Actual execution:14 successful IEM requests,26,611,992 raw body bytes. Accepted:
299,240 rows, consisting of196,057 IEM hourly-class records and103,183 IEM
nonhourly-class records, all50 requested stations. **These archive classes do not
establish ICAO METAR versus SPECI report identity.** Nominal range:31March2026
00:00UTC through28October2026 23:56UTC.
One raw row was not accepted because exact TAC station identity could not be
established; its raw capture is preserved under SHA256
`743ecdec689e404aeca1ec88da159b057bb1dc0c810ca02125db365f0e7ba94b`, data-row6459.
Missing source temperature remains NULL. Archive ingestion does not create a
production temperature observation or change any QC eligibility policy.

Output: ignored `data/research/exp0017/metars.json`. Each row contains nominal
`event_time`, complete TAC, report type, original COR flag, parsed body temperature,
raw hash and **actual present archive retrieval time** separately.
`collector_receive_time` is always NULL for these historical backfills. The archive
cannot establish when HighTempTation or our collector first saw an old METAR.

Combined source acquisition:60 successful requests and61,352,833 raw bytes.
Repeated execution reuses URL-keyed, SHA256-checked captures instead of requesting
the network again. It never copies a live WAL database file.

## Correction: IEM hourly class is not ICAO report identity

The initial normalization equated IEM `report_type=4` with original SPECI. Review
of an EPWA22October20:30UTC report revealed that this excluded a regularly
scheduled half-hour report. This inference was rejected before final analysis.

The upstream author's [METAR Report Types explanation](https://mesonet.agron.iastate.edu/onsite/news.phtml?id=1434)
describes a classifier created to distinguish a station's hourly precipitation
reset report from other reports. It notes that some AWOS have several reports an
hour without a special-report concept. The
[original issue104](https://github.com/akrherz/iem/issues/104) describes a derived
reset-minute algorithm. The current upstream
[adjust_report_type.py](https://github.com/akrherz/iem/blob/main/scripts/asos/adjust_report_type.py)
(Git blob `808f3d957d1aa54059624b7cee36d77fd2c935c4`, reviewed29October2026)
groups reports by station and hour and can assign type3 to the latest report
when that hour has none. A field changed by this algorithm is not authoritative
evidence of an original ICAO SPECI declaration. In particular it can classify a
routine half-hour report as type4.

Final parser `EXP0017-IEM-TAC-TYPE-v2` therefore uses:

* Original explicit `METAR` prefix: `product_type=METAR`.
* Original explicit `SPECI` prefix: `product_type=SPECI`.
* Neither prefix: `product_type=UNKNOWN_ROUTINE_OR_SPECI`, preserving the original
  IEM type and `archive_hourly_class` separately. `candidate_product_type=METAR`
  identifies a nominal-timing candidate, **not certified routine eligibility**.

All299,240 captured archive rows lack original prefixes, so all remain explicitly
type-uncertain. The analytical timing study may compare recurring nominal times
using these candidates, with that limitation prominent and separate from any
strict original-report-type analysis. It must not call every type4 report SPECI,
nor call every unprefixed report routine. Scheduled minute compatibility does not
independently certify the exact report type or publication time.

The14 cached raw responses were re-normalized without additional observation
requests. Original HTTP evidence and production weather records were not changed.

## Reproduction

```powershell
cd D:\metar-execution-lab\michupl-pre-metar
uv run python -m scripts.research.entry_timing_sources --markets-only
uv run python -m scripts.research.entry_timing_sources --archive-only
uv run pytest -q tests/test_entry_timing_sources.py
$env:MYPYPATH = 'src'
uv run mypy --explicit-package-bases scripts/research/entry_timing_sources.py
```

Only this experiment's ignored directory is written. Do not treat historical
archive retrieval as a prospective feed or substitute it for first local receipts.

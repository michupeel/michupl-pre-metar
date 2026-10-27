# EXP-0012 market identity and local-clock audit

Only the frozen `trader_pinned.sqlite3` snapshot is read. No service restart,
production import, live database write, new subscription or weather-data request
was performed by this component. The loader is
`scripts/research/hightemptation_metadata.py`; its timezone map is explicit and
its local-midnight arithmetic uses Python `zoneinfo`.

## Observed coverage

Snapshot pinned at2026-10-27T11:37:17.798402Z contains11867public economic rows,
4727traded tokens and11550captured MARKET events representing727conditions.

| Evidence | Coverage | Meaning |
|---|---:|---|
| Geographic city timezone |11856weather rows /4721weather tokens|Descriptive local civil time, `CITY_REFERENCE_ONLY` |
| Unidentified/nonweather timezone |11crypto rows /6tokens|UNKNOWN |
| Exact condition+token captured market reference |430trade rows /123tokens|Original captured description/source, not inferred from city |
| Exact rules captured before source block time |6trade rows|Our metadata receipt precedes the reported source clock; no claim about trader access |
| Captured tokens with explicit local-day wording |63tokens|UTC local-calendar bounds may be stated with the explicit city timezone reference |

Most old contracts have no captured exact MARKET description. They retain NULL
reference station, source, unit and precision policy. Their city and date may be
parsed from the recorded slug, with that provenance retained. A contemporary
description for a different market is not retroactively substituted.

For matched captured contracts, the earliest recorded description is used and
its receipt and SHA256 retained. The number of different description hashes is
exposed. A caller must compare metadata receipt with the individual trade before
using it as as-of evidence. The source timestamp has whole-second precision;
metadata availability at that clock does not establish an earlier decision time.

## Important geography mismatch

Captured London contracts reference **EGLC, London City**, while the production
weather experiment monitors **EGLL, Heathrow**. Those are different airports.
EGLL temperatures must not be labeled the official settlement observation for
an EGLC market. Other directly captured references include AnkaraLTAC, NYCKLGA,
TaipeiRCSS, ParisLFPB and WarsawEPWA. Codes are taken from original `site=`,
`ids=` or Weather Underground station URLs, or explicit airport-code text.
Conflicting codes stay NULL. No nearest airport is guessed.

## Geographic clocks versus settlement boundaries

The explicit49city lookup references [IANA time zones](https://www.iana.org/time-zones)
and uses its historical rule implementation through `ZoneInfo`. IANA describes
representative geographic regions, not Polymarket settlement contracts; see
[tz database scope](https://www.iana.org/time-zones/theory).

Consequently `timezone_status=CITY_REFERENCE_ONLY` permits descriptive trade-hour
analysis but does not verify a market's settlement-day convention or causal Tmax
forecast. `city_calendar_day_start_utc` and `city_calendar_day_end_utc` are separate
from `settlement_day_start_utc`/`settlement_day_end_utc`. The latter remain NULL
unless the exact captured rule text explicitly refers to local time/date. Even
then the geographic timezone provenance remains visible.

Adjacent local midnights are constructed independently. For Warsaw25October2026,
the bounds are24October22:00Z to25October23:00Z, exclusive:25hours. Repeated02:30
readings retain their different offsets. The29March2026day has23hours. No24hour
UTC addition or fixed current offset is used. Historical IANA data installed in
the project environment determines DST behavior; a timezone key is not a claim
about subsecond clock synchronization.

## One bounded official reference request

Parent-authorized single request:
`GET https://aviationweather.gov/api/data/stationinfo?ids=<27capturedICAOs>&format=json`.
It returned HTTP200 and all27station records. The raw response and request/receipt
clocks are preserved at `data/research/exp0012/stationinfo_reference.json`.
The API exposes station name, country, coordinates and elevation, **no timezone
field** in this response. It therefore corroborates station identity only and
does not upgrade city-reference timezone status to verified settlement geography.
The request does not retrieve historical weather or prove public availability
at an old trade. No second request or full-network lookup was made.

Current [official AWC API documentation](https://aviationweather.gov/data/api/)
documents station-info products, scoped queries, rate restrictions and cache
alternatives. No paid provider or undocumented endpoint was used.

## Unavailable causal inputs

The metadata component never manufactures forecast Tmax time, observed Tmax time,
or weather values. Both timing fields remain NULL and the default status is
`NO_CAUSAL_FORECAST_ARCHIVE`. Any actual-weather retrospective calculation must
be done separately against the correct station/day and cannot be presented as
the trader's forecast input. Geographic local14:00–16:00 counts alone cannot
establish a relationship to expected local Tmax.

## Verification

42offline tests passed: Warsaw23/25hour days, repeated local hour, valid explicit
zone keys, wrong/missing/ambiguous references, retrospective rule availability,
unknown market identity and no invention of forecast inputs. Ruff and strict
mypy pass for this module. No live database bytes were changed by fixture tests.

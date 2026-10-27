# EXP-0011 — legitimate weather information candidates

Review date: 27 October 2026. This is an access/clock evidence register, not a
claim that HighTempTation uses any particular feed. No weather collector, station
selection or subscription was changed. No paid API, customer account or restricted
aviation service was activated. Current primary documentation was checked; prior
local measurements are explicitly distinguished from new source measurements.

## Candidate matrix

| Source / current project status | Information and documented cadence | Measurement versus publication clocks | Access, cost and terms | Measured receipt evidence |
|---|---|---|---|---|
| AWC METAR — existing weather collector enabled | Original worldwide METAR/SPECI/COR; station-dependent cadence; aggregate cache updated once/minute | TAC/obsTime identify observation; receiptTime is upstream AWC receipt, not our receipt or proven global first publication | Public HTTPS, no key; scope requests/custom User-Agent, maximum100/minute; NOAA attribution and third-party rights caveat | Existing local immutable receipts; exact matched EHAM example below; no new polling added |
| KNMI direct EHAM METAR — existing enabled | Latest original EHAM IWXXM/TAC; routine :25/:55; producer calls direct route its fastest available access, best-effort | Nominal time may be later than delivery; retain translation/bulletin receipt fields separately; HTTP Last-Modified is not sensor/publication time | Public direct HTTPS without key; dataset CC-BY4.0; best-effort service may be withdrawn | Existing same-report receipt preceded AWC by427.275458seconds in the example below; this is not a general SLA |
| DWD CDC10min EDDM — existing enabled | Station01262, TT_10 instantaneous2m°C;10-minute measurement series; now/ product described as hourly or <1h refresh | Current timestamps UTC; file modification time does not give individual public availability; provisional QC may revise values | Anonymous public ZIP; CC-BY4.0 with DWD attribution | Existing project raw/normalized records; no new prospective latency distribution computed here; cadence is not latency |
| KNMI10min + MQTT notifications — disabled optional candidate |10-minute station variables; official docs say available a few minutes later, with late additions up to7days; notifications announce new/updated files | Timestamp denotes interval end UTC; notification/file receipt must be measured separately | Open Data API Authorization key, registered or shared anonymous according to current policy; notification credentials separate; CC-BY4.0 | Not connected in this repository; NO MEASURED LOCAL RECEIPT LATENCY |
| DWD ASDUV Airport Customer Telegram — unimplemented access candidate | Prior checked aviation catalogue describes airport XML and transfer every minute; not a public METAR JSON endpoint | Sensor averaging, issue/send clocks and parity with METAR require the actual schema/provider confirmation | Catalogue says free for aviation; independent non-aviation eligibility, credentials, protocol and terms NOT ESTABLISHED | No local capture; current catalogue fetch returned403; no anonymous URL inferred |
| IMGW public synop/meteo — unimplemented candidate here | Documented JSON synop and meteo products; API page supplies endpoints but no seconds-level delivery guarantee | Verify per-product time/zone semantics before normalization; observation date/hour cannot establish publication | Public documented GET, no key shown; IMGW terms distinguish private/high-value reuse from some commercial services; attribution and processing notice | No prospective source measurement added here; not interchangeable with EPWA METAR |
| IMGW EPWA aviation / registered SWIM — unimplemented here | Public aviation site displays METAR/TAF; separate SWIM offers15airports, AMQP1.0 push and EDR request/reply | Original TAC/IWXXM observation and issue clocks; availability requires recorded receipts; no public delivery SLA verified | SWIM delivery explicitly requires registration and customer-support access; cost/reuse eligibility require confirmation | Parent-lab producer captures exist separately; not integrated or represented as this repository's live feed |
| CHMI MET-SWIM — unimplemented here | Official API documents Czech TAC/IWXXM, routine METAR :00/:30 and SPECI; not a feed for our four airports | IWXXM observation/issue clocks; listing updated is file update UTC, not proof of initial global dissemination | Documented public read-only HTTPS/no registration; standard-use availability is not unlimited request permission; reuse terms still require product-specific review | No new local prospective latency measurement here; parent-lab LKPR capture is a distinct experiment |
| ATIS / D-ATIS — disabled interface only | Aviation terminal information; D-ATIS carries local automated/manual weather through datalink and voice; issuance depends on service | Message/letter issue time is not necessarily sensor measurement time; no verified publication clock or sensor parity here | FAA documents subscriber/provider distribution; public research access, redistribution and cost depend on particular legitimate service | No verified connection or measured local latency; UNKNOWN, not an assertion that all legitimate access is forbidden |

## Current primary sources checked

- [AWC API](https://aviationweather.gov/data/api/): documented product formats,
  minute cache refresh and request limits. Existing project adapter and clock
  mappings remain in [sources.md](../sources.md); no burst polling authorized.
- [KNMI direct-feed announcement](https://developer.dataplatform.knmi.nl/news),
  dated2October2026, links the existing
  [EHAM latest XML](https://d2whtzszevhgqk.cloudfront.net/metar-EHAM-latest.xml).
  [Dataset license and report definition](https://dataplatform.knmi.nl/dataset/metar-1-0).
- [KNMI10-minute technical documentation](https://dataplatform.knmi.nl/dataset/docs/10-minute-in-situ-meteorological-observations-1-0)
  and [dataset/license](https://dataplatform.knmi.nl/en/dataset/10-minute-in-situ-meteorological-observations-1-0).
  Use current [Open Data API](https://developer.dataplatform.knmi.nl/open-data-api)
  and [notification documentation](https://developer.dataplatform.knmi.nl/notification-service)
  before implementation; credentials are not requested or printed here.
- [DWD10-minute product description](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/DESCRIPTION_obsgermany_climate_10min_air_temperature_en.pdf)
  rechecked: v24.03, provisional now/ QC, UTC, CC-BY4.0. Hourly publication is
  specifically distinct from the10-minute measurement cadence.
- [DWD aviation product catalogue](https://www.dwd.de/EN/specialusers/aviation/download/services/wafor/productlist_aviation_download.pdf?__blob=publicationFile&v=20):
  current request403, so catalogue-specific access claims remain PARTIALLY_VERIFIED,
  based on the parent lab's22October source review. The official
  [DWD observation-system publication](https://gcos.dwd.de/SharedDocs/broschueren/DE/presse/professio_wetterbeobachtung.pdf.pdf?__blob=publicationFile&v=2)
  corroborates ASDUV's airport distribution role, not anonymous access.
- [IMGW API and reuse rules](https://danepubliczne.imgw.pl/apiinfo):
  `/api/data/synop`, station selection and `/api/data/meteo/` are documented.
  [Public aviation site](https://awiacja.imgw.pl/metar-i-taf) and
  [official SWIM service description](https://eur-registry.swim.aero/service-description/metar-iwxxm-poland)
  distinguish public display from registered machine delivery. Do not extrapolate
  an unrestricted redistribution license from an HTTP200response.
- [CHMI API reference](https://swim.chmi.cz/SWIM_API_reference.pdf), current
  document control2026-06, confirms GET
  `https://swim.chmi.cz/api.php?action=get&file=LKPR_METAR.txt&format=txt`;
  [service information](https://swim.chmi.cz/info.php) describes products/schedules.
  Its advertised latency target is not our measured latency.
- [FAA D-ATIS definition](https://www.faa.gov/air_traffic/publications/atpubs/pcg_html/glossary-d.html)
  and [TDLS subscriber distribution](https://www.faa.gov/air_traffic/publications/atpubs/pcg_html/chap1_section_21.html).
  No undocumented internal interface is used.

## Concrete previously recorded comparison

The frozen EXP0010 source receipt export contains this same EHAM report identity:

| Nominal UTC | Source | Our first recorded receipt UTC |
|---|---|---|
|2026-10-26 08:55:00|knmi_metar|2026-10-26 08:52:11.841493|
|2026-10-26 08:55:00|awc|2026-10-26 08:59:19.116951|

Source: `reports/research/early_metar_reference_receipts.csv`, report identity
`ef8a061c3faf23dcb4a32b4705ea936c0ef6d09ccdff592b65f8a6bc21f2d0c5`,
derived from the consistent EXP0010 snapshot cut off
`2026-10-26T19:06:15.753046Z`. KNMI arrived168.158507seconds before the nominal
label and427.275458seconds before AWC in our recorded system. This demonstrates
why source/event/receipt clocks and earliest-provider closure matter. It neither
proves precise publication latency nor establishes that the trader had or used
this feed. Collector clock uncertainty remains relevant.

## Decision and next discriminating observation

Prefer existing recorded producer-versus-aggregator races where market geography
matches. Extend only through independently verified legitimate endpoints and
terms, in a separately authorized experiment. Freeze exact market settlement rules,
record original messages/receipts, include unchanged cycles, corrections, failed
signals and comparable no-trades. A producer received before a wallet execution
supports possible availability; it does not identify the trader's source or time
of decision. PWS and forecast archives need their own first-receipt/version evidence.
None of this source review alone distinguishes H1 from H3, H5 or H6.

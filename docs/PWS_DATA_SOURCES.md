# PWS source register — Milestone 1.5

Checked 2026-10-23 UTC (2026-10-24 in Warsaw). Public HTTP verification bodies
and schemas are retained locally in `data/pws-verification/`; collection evidence
is in `data/pws-smoke-raw/` and `data/pws-smoke.sqlite3`. These are ignored,
not redistributed as part of the MIT source-code license.

| Provider | Geographic discovery | Latest | History implementation | Status |
|---|---|---|---|---|
| openSenseMap | bbox, then exact haversine radius | box/sensors | bounded sensor history, offline schema-tested | PARTIALLY_VERIFIED |
| Sensor.Community | documented v1 area filter | v1 individual sensor | no; daily archive exists separately | PARTIALLY_VERIFIED |
| Netatmo | documented public bounding rectangle; disabled | disabled | public history not verified | BLOCKED |
| CWOP | not implemented | not implemented | not implemented | UNAVAILABLE in this module |

## openSenseMap

Primary sources: [official REST overview](https://osem.books.sensebox.de/en/osem_api.html),
[API documentation](https://docs.opensensemap.org/),
[official API source](https://github.com/sensebox/openSenseMap-API), and its
[configuration example](https://github.com/sensebox/openSenseMap-API/blob/master/config/config.example.json).
The documentation app needed source/API inspection; no undocumented substitute
endpoint was invented.

Implemented documented GETs at `https://api.opensensemap.org`:

- `/boxes?bbox=west,south,east,north`
- `/boxes/{boxId}/sensors`
- `/boxes/{boxId}/data/{sensorId}?from-date=...&to-date=...&format=json`

Public reading needs no credentials. Discovery returns box identifiers, names,
declared exposure, currentLocation GeoJSON coordinates, sensor IDs, titles,
units, sensorType and optional lastMeasurement. Titles identify temperature;
unknown phenomena are not silently interpreted as temperature. The actual unit
is retained and validated, not inferred from sensor price/model. Latest returns
a box object with sensors; missing/null measurements remain missing. History
is documented as at most 10,000 values over at most one month; our requests cap
at 28 days and explicitly reject a possibly truncated 10,000-row result. History
always carries HISTORICAL_EVENT_ONLY, even when downloaded today.

`lastMeasurement.createdAt` is the provider's measurement label, not publication
proof. No publish timestamp is invented. Third coordinate is retained as reported
height/elevation but is **not verified above sea level**, so no lapse adjustment
uses it automatically. Instrument resolution/manufacturer are unknown unless
explicitly supplied; textual values do not establish hardware precision.

The upstream API code is MIT; that does not establish the data license. The
current controlling data-license statement and numeric request quota were not
conclusively retrieved from primary terms during verification. They remain
unverified, rather than inferred from third-party summaries. Local research
captures and attribution are retained; raw data is not published with this code.
This is why the status is PARTIALLY_VERIFIED. Defaults are conservative: 300s
per station minimum, one request/s per provider, no burst; HTTP 429 overrides
these defaults. These are our limits, not a claimed provider allowance.

## Sensor.Community

Primary sources: [official API wiki](https://github.com/opendata-stuttgart/meta/wiki/EN-APIs),
[backend clock configuration](https://github.com/opendata-stuttgart/feinstaub-api/blob/master/feinstaub/feinstaub/settings/base.py),
[models](https://github.com/opendata-stuttgart/feinstaub-api/blob/master/feinstaub/sensors/models.py),
[installation/data terms](https://sensor.community/it/sensors/airrohr/),
and [archive](https://archive.sensor.community/).

Use `data.sensor.community` for reads, with an identifying User-Agent, not the
ingestion host. No authentication is required. Implemented v1 GETs:

- `/airrohr/v1/filter/area={latitude},{longitude},{distance_km}`
- `/airrohr/v1/sensor/{API_sensor_id}/`

V1 returns recent individual values; v2 is a five-minute average and is deliberately
not substituted. The wiki documents cache/update delay; response frequency is
not measurement frequency. No numeric hard quota was verified. Our baseline
is >=300s per station (slower if observed cadence warrants it), one request/s
per provider, no bursts, and Retry-After on 429. Availability only covers stations
in the API's recent window; this is not an exhaustive inventory of offline sensors.

Temperature/humidity value types map to Celsius/% in the documented ecosystem;
sensor type and location metadata are preserved. Location IDs group the API's
sensors without claiming they belong to one verified physical device. API sensor
IDs remain separate. Coordinates may be rounded/obfuscated, and location altitude
or height is not assumed to be verified station elevation.

The wiki explicitly says the server assigns the timestamp; backend defaults use
UTC/TZ-aware time. Thus the naive response timestamp is interpreted as UTC
**server-ingest** time and stored in `provider_timestamp` with its clock kind.
`observation_time` and `source_publish_time` stay NULL. Ages and update intervals
using this clock are explicitly labelled provider-server proxies. Unknown delivery
from the sensor to that server remains an important limitation.

The project identifies DbCL v1.0 data terms; retain DbCL/ODbL obligations and
attribution to Sensor.Community contributors when distributing derived databases.
Code licensing is separate. Daily CSV exports exist, generally generated around
08:00, but archive ingestion is not implemented and cannot prove historical
real-time availability. Partial status reflects incomplete quota/archive/runtime
coverage verification, not a failed anonymous-access test.

## Netatmo

Primary sources: [Weather API](https://dev.netatmo.com/apidocumentation/weather),
[OAuth](https://dev.netatmo.com/apidocumentation/oauth),
[guidelines](https://dev.netatmo.com/guideline),
and [legal portal](https://dev.netatmo.com/legal).

The official documentation JavaScript invokes a public documentation endpoint:
POST `https://dev.netatmo.com/api/getdocumentationjson`, form `fileName=Weather`.
That returned HTTP200 OpenAPI 3.0.1 and was inspected locally. It specifies
`https://api.netatmo.com/api/getpublicdata`, GET rectangle parameters
`lat_ne,lon_ne,lat_sw,lon_sw`, optional `required_data` and `filter`.
The operation security lists OAuth/read_station, while its description says
scope/none_required: the discrepancy is retained, not guessed away.

The schema specifies authorization-code OAuth at
`https://api.netatmo.com/oauth2/authorize` and token endpoint
`https://api.netatmo.com/oauth2/token`. `netatmo_auth.py` accepts externally
managed access tokens and supports explicit refresh in memory; token responses
are never raw weather payloads or logs. Permanent auth errors disable refresh.
No password flow, automatic account creation, credential prompts or paid plan.
Rotated refresh-token persistence belongs to an external credential manager.

No Netatmo credential was used. The public response schema exposes station/module
identities, place and measures, but coordinate ordering/clock/unit semantics,
current public-data entitlements, quota, licensing and historical access were
not adequately verified in an authenticated runtime. Therefore the adapter is
explicitly blocked, declares no implemented data capabilities, and is disabled
in default settings. The documented authentication helper does not pretend that
the weather runtime adapter is complete. This is a milestone limitation.

## Airports and future source work

Airport reference coordinates are centralized in `pws/airports.json`. An actual
HTTP200 request to [NOAA AWC stationinfo](https://aviationweather.gov/api/data/stationinfo?ids=EDDM,EHAM,EPWA,EGLL&format=json)
returned EDDM 48.348/11.813, EHAM 52.315/4.790, EPWA 52.163/20.961,
EGLL 51.477/-0.461 (latitude/longitude). These are airport weather-reference
points, not an assertion of runway-centre coordinates or sensor parity.

[CWOP](https://www.wxqa.com/) and [NOAA MADIS](https://madis.ncep.noaa.gov/)
are future candidates. Access, redistribution, metadata, timestamp meanings and
public discovery need a separate verified adapter. No CWOP endpoint is guessed.

# EXP-0013 — forecast and nearby-station source verification

Verified against current primary documentation on28October2026. This is a
source-capability audit, not a measured forecast-skill ranking. No services,
production databases or station selections were changed for this audit. No
Weathercloud pages were scraped and no undocumented endpoint was queried.

## Recommended minimal prospective source

Open-Meteo's coordinate forecast API supplies all four airport locations in one
request using comma-separated latitude/longitude lists. Use the repository's
verified coordinates, explicit `models=icon_global`, `hourly=temperature_2m`,
`temperature_unit=celsius`, `timezone=UTC`, `timeformat=unixtime`; retain returned
grid coordinates/elevation. API endpoint: `https://api.open-meteo.com/v1/forecast`.
The parameter/model identifiers are supported by the current official
[OpenAPI schema](https://github.com/open-meteo/open-meteo/blob/main/openapi/forecast.yml)
and [controller source](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Controllers/ForecastapiController.swift).
Explicit global ICON avoids a geographically changing `best_match` mixture;
it is an operationally simple baseline, not an assertion that11km is optimal
for airport or PWS microclimates. The official
[open-data catalog](https://github.com/open-meteo/open-data) identifies `dwd_icon`
as global, approximately11km, hourly, typically updated every6hours, and describes
the rolling-timeseries metadata path `data/<model>/static/meta.json`.

### Timestamp semantics and association limits

Forecast `hourly.time` is forecast validity, not issue time. `generationtime_ms`
is response/forecast generation processing duration used for performance
monitoring, not an epoch timestamp; never convert it to a publication clock.
Open-Meteo's returned timezone offset is resolved at request time and may be
fixed across a DST transition. Request UTC and perform each local conversion
with zoneinfo instead. [Forecast response documentation](https://open-meteo.com/en/docs).

The [official model-update documentation](https://open-meteo.com/en/docs/model-updates)
defines `last_run_initialisation_time`, `last_run_modification_time` and
`last_run_availability_time` separately. Modification means download/conversion
completion, not API publication. Availability is API-server access, but redundant
servers can temporarily disagree; the provider recommends10minutes before
assuming consistent freshness. Metadata is per-model and cannot identify the
exact constituents of `best_match`. Capture the small corresponding metadata
resource `https://api.open-meteo.com/data/dwd_icon/static/meta.json` with its own
first receipt and raw body. Even unchanged metadata before/after a forecast
request is supporting evidence, not cryptographic proof of the returned run.
Keep the association `CANDIDATE_RUN_METADATA`, unless content explicitly binds
the model run. Do not assign the metadata clock as each row's verified issue or
publication time. The web research tool could not render this JSON URL; actual
runtime success must be reported separately by the collector smoke test.

For stronger run identity, the documented
[Single Runs API](https://open-meteo.com/en/docs/single-runs-api) is
`https://single-runs-api.open-meteo.com/v1/forecast`, with required
`run=YYYY-MM-DDTHH:MM` specifying UTC initialization. It preserves individual
model runs. Initialization is explicitly not public availability: computation
and distribution follow later. An archival retrieval today cannot establish
that our collector had the forecast yesterday. Use such data only as labeled
retrospective model context, never fabricated prospective receipt evidence.

### Access, licensing and conservative cadence

The [service terms](https://open-meteo.com/en/terms) limit free access to
noncommercial purposes: under10000calls/day,5000/hour,600/minute, with a
300000/month free-tier table limit. Attribution is required under CC BY4.0.
Data licensing does not remove the free-service noncommercial restriction.
This public research-only experiment must stay within that scope; no paid plan
or commercial trading use is enabled by this audit. A four-location batch at
30minute intervals is conservative; multi-location request accounting must be
considered rather than assuming one HTTP request always equals one billed unit.
Publication uncertainty and source/platform outages remain explicit.

## Other legitimate forecast candidates

|Source|Useful data/time evidence|Access and limitations|Status for this audit|
|---|---|---|---|
|DWD MOSMIX|Point forecasts, hourly valid steps, explicit product issue metadata; temperature `TTT` in Kelvin requires conversion|Open-data KML/KMZ. Product/station mapping and successful small capture must be verified before integration; no giant all-station download required|PARTIALLY_VERIFIED; promising stronger product-clock alternative|
|KNMI HARMONIE|Hourly model forecasts, run/reference date in filenames, lead hours; distinguish forecast reference from receipt|Documented file API plus Notification Service; GRIB/tar extraction. Anonymous or registered API key. No credential requested or used by this audit|VERIFIED documented capability; not runtime-integrated|
|Met Office Weather DataHub|Global hourly site-specific deterministic forecast; probabilistic API exposes collection instances|Registration/subscription and API key; free quotas exist. No new account or subscription created|BLOCKED pending legitimate credentials/integration|
|IMGW public API|Verified `synop`/`meteo` measurement products, not a verified hourly point forecast endpoint|Do not relabel measurements as forecasts or derive undocumented weather-site endpoints|UNVERIFIED for requested hourly forecast use|
|ICM meteo.pl|Official research forecast API and initialization metadata are described|Official page warns indexing delay and does not guarantee uninterrupted operational access; licensing/access review needed|PARTIALLY_VERIFIED, not enabled|

DWD's primary [MOSMIX availability description](https://www.dwd.de/EN/ourservices/met_application_mosmix/mosmix_application_description.pdf?__blob=publicationFile&v=2)
lists MOSMIX_S hourly updates and MOSMIX_L four daily updates. Its
[KML format specification](https://www.dwd.de/DE/leistungen/met_verfahren_mosmix/kml_formatbeschreibung.pdf?__blob=publicationFile&v=16)
describes issue metadata, forecast timestamps and temperature fields. No actual
airport MOSMIX identifier or present-day cadence was inferred from an example.

KNMI's [HARMONIE product description](https://english.knmidata.nl/open-data/harmonie)
documents the filename/reference/lead structure. The
[Open Data API guide](https://developer.dataplatform.knmi.nl/open-data-api)
documents `https://api.dataplatform.knmi.nl/open-data/v1/datasets/{datasetName}/versions/{versionId}/files`
and the per-file `/files/{filename}/url` download-link endpoint. Authentication
is via Authorization header; this report intentionally contains no key.
Registered quota1000requests/hour and anonymous shared3000/hour are separate
from burst limits. Prefer notification-driven availability; excessive listing
polls are explicitly discouraged. Historical file retention varies by dataset.

Met Office [product overview](https://www.metoffice.gov.uk/services/data/met-office-weather-datahub)
and [pricing](https://datahub.metoffice.gov.uk/pricing/site-specific) describe
the global hourly product and free360calls/day tier. The
[API user guide](https://datahub.metoffice.gov.uk/docs/f/category/site-specific/type/probabilistic-forecast-feature/api-user-guide)
requires registration/key and documents instance-aware EDR access. Free is not
the same as anonymous. [IMGW's API index](https://danepubliczne.imgw.pl/apiinfo)
lists the observed-data endpoints; [ICM's official API](https://api.meteo.pl/)
and [FAQ](https://faq.meteo.pl/) distinguish research access, indexing lag and
discouraged aggressive checks. Neither was substituted for a current documented
forecast adapter.

## EPWA Weathercloud candidates: no established machine-readable identity

|Candidate|User-supplied location/elevation|Public station identity|Instrument/cadence/measurement timestamp|Authorized read source|
|---|---|---|---|---|
|A|52.180556,20.943611;120m|UNVERIFIED|UNKNOWN|UNKNOWN|
|B|52.158056,20.924722;114m|UNVERIFIED|UNKNOWN|UNKNOWN|

Exact-coordinate, nearby decimal-prefix, Weathercloud+Warszawa and adjacent
locality indexed web searches did not establish either station's public ID or
owner. This is a search limitation, not proof that a station does not exist.
Coordinates/elevations remain user assertions; no instrument, measurement,
shared hardware identity or owner contact was invented from them. No matching
openSenseMap identity can be inferred solely from approximate coordinates.

The current [Weathercloud FAQ](https://weathercloud.net/en/faq) explicitly states
there is no data-retrieval API. It describes Basic update cadence10minutes,
some paid plans1minute, and storage interval10minutes. Those platform values
do not prove these particular sensors' measurement cadence. The documented
[API](https://weathercloud.net/en/api) is `/v01/set` for authenticated station
uploads; its WID/key and temperature fields are not a public retrieval method.
An upload has no independently verified physical measurement-clock guarantee
for either candidate. No upload API request was sent.

Retain both as manually observed candidates with
`UNKNOWN_MACHINE_READABLE_AVAILABILITY`. Next legitimate evidence would be an
owner-provided public station link, hardware/model identity and an authorized
owner export or documented secondary-provider account. Owner permission alone
does not create undocumented Weathercloud read API access. No owner was
contacted and no alternative hardware feed was proven in this audit.

## Decision

Accept a prospective coordinate forecast archive with immutable receipt clocks
and explicit unknown publication/run association. Do not rank providers by
forecast accuracy before matched future observations exist. Keep DWD product
issue metadata as a documented next adapter candidate. Weathercloud A/B remain
unverified manual candidates; no automated collection is authorized by the
available evidence.

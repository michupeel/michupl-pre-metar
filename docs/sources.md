# Source register — verified 2026-10-21 UTC

Endpoint verification captures are local, ignored `data/verification/`. Runtime
evidence is separately captured under `data/raw/`. Fixtures never establish latency.

## AviationWeather / NOAA — enabled

- [Official API and request policy](https://aviationweather.gov/data/api/).
- [OpenAPI schema](https://aviationweather.gov/data/schema/openapi.yaml).
- Endpoint actually fetched: `https://aviationweather.gov/api/data/metar?ids=EDDM,EHAM&format=json` — HTTP200, two reports.
- No key. Custom User-Agent; baseline 60s between batch requests. Published maximum
  100 requests/minute is a ceiling, not a target. No burst enabled.
- JSON original `rawOb` supplies nominal DDHHMMZ and integer temperature. `obsTime`
  is event epoch; `receiptTime` is upstream AWC receipt, not our receive or proof
  of global first publication. `reportTime` can differ from TAC nominal time:
  first capture EDDM TAC16:50, JSON reportTime17:00; retain both distinctly.
- [NOAA information policy](https://oceanservice.noaa.gov/about/faq.html): US-government-produced data generally public domain;
  third-party contributions can have separate rights. Attribute NOAA/NWS/AWC.
- Latest-only polling may miss intervening reports/SPECI. No completeness guarantee.

## DWD CDC EDDM 10-minute — enabled baseline

- [Official product description v24.03](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/DESCRIPTION_obsgermany_climate_10min_air_temperature_en.pdf).
- [Station catalogue](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/historical/zehn_min_tu_Beschreibung_Stationen.txt) downloaded: `01262`, München-Flughafen,48.3477N11.8134E,446m.
- [DWD airport station metadata](https://www.dwd.de/DE/klimaumwelt/klimaforschung/klimawirk/stadtpl/projekt_waermeinseln/viewer/steckbrief_muenchen.pdf?__blob=publicationFile&v=7): WMO10870.
- Actual endpoint: `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/now/10minutenwerte_TU_01262_now.zip` — HTTP200,1381bytes at initial verification.
- ZIP contains `produkt_zehn_now_tu_20261021_20261021_01262.txt`, semicolon CSV.
  `MESS_DATUM` UTC, `TT_10` instantaneous2m Celsius (0.1 resolution), `TD_10`
  calculated dewpoint; missing -999, quality QN retained. PP_10 is station pressure.
- Description calls now updates hourly / less than1h; observation cadence alone
  proves no delivery edge. Last-Modified is file metadata, never assigned to
  observation publication. No API key; conservative polling60s, no burst.
- [CDC terms](https://opendata.dwd.de/climate_environment/CDC/Terms_of_use.pdf): CC-BY4.0. Attribution: Deutscher Wetterdienst, CDC.
- Same airport/WMO establishes location, **not identical sensor/aggregation** to METAR.
  This adapter does not supply extrema; min/max require separate verified products.

## KNMI EHAM full METAR — enabled

- [Official announcement,2026-10-02](https://developer.dataplatform.knmi.nl/news) links the direct latest feed and calls it best-effort.
- [METAR dataset/license](https://dataplatform.knmi.nl/dataset/metar-1-0): CC-BY4.0; attribute KNMI.
- Actual endpoint: `https://d2whtzszevhgqk.cloudfront.net/metar-EHAM-latest.xml` — HTTP200,4696bytes initial verification.
- Payload has WMO bulletin prefix, IWXXM XML and original METAR TAC comment.
  TAC nominal time is the report/event label. `translatedBulletinReceptionTime`
  is retained as upstream receipt; `translationTime` stays named metadata, not
  guessed publication. HTTP Last-Modified remains raw metadata.
- No key. Baseline60s, no burst. This is a second EHAM dissemination path distinct
  from AWC; common observation/upstream infrastructure is not claimed independent.
- [KNMI airport-report description](https://cdn.knmi.nl/knmi/pdf/bibliotheek/knmipubIR/IR2012-02.pdf): labels H+25/H+55 and generation can precede the nominal label. Timing semantics must not be inferred from DDHHMM alone.

## KNMI 10-minute observations / push — disabled optional

- [Current dataset](https://dataplatform.knmi.nl/en/dataset/10-minute-in-situ-meteorological-observations-1-0), CC-BY4.0: interval-end UTC reference and availability minutes later; station values can arrive late.
- [Open Data API](https://developer.dataplatform.knmi.nl/open-data-api): header Authorization required, including anonymous access. Registered limits200requests/s and1000/hour; shared anonymous50/minute and3000/hour. No credential is embedded or copied here.
- Verified documented list route: `https://api.dataplatform.knmi.nl/open-data/v1/datasets/10-minute-in-situ-meteorological-observations/versions/1.0/files`.
  Download-URL route is `/files/{filename}/url`; signed URLs must not be persisted.
  No authenticated endpoint or NetCDF parser was smoke-tested; adapter stays disabled.
- [Deprecation](https://developer.dataplatform.knmi.nl/deprecation): old `10_minute_observation_variables` is superseded. Do not implement against it.
- [Notification Service](https://developer.dataplatform.knmi.nl/notification-service): MQTT over WSS,443, own notification key. Topic `dataplatform/file/v1/10-minute-in-situ-meteorological-observations/1.0/#`. Recommended instead of excessive polling. Not connected in M1.
- [Schiphol station reference](https://cdn.knmi.nl/system/data_center_publications/files/000/051/399/original/hss_temperatuur_tr329_copy2.pdf): WMO06240. Sensor identity/parity with current METAR remains unverified.

## Routine schedules and temperature coding

- [DWD METAR guide](https://www.dwd.de/EN/specialusers/aviation/download/products/metar_taf/metar_taf_download.pdf?__blob=publicationFile&v=3) documents German nominal20/50minutes.
- [KNMI-authored airport study](https://cdn.knmi.nl/system/data_center_publications/files/000/068/587/original/2011jamc2601.pdf?1495621290=) documents Schiphol25/55minutes. Older official descriptions corroborated by current live TAC; treat as expected schedules, not publication SLA.
- [WMO FM15 section15.11 hosted by ICAO](https://www.icao.int/safety/meteorology/amofsg/AMOFSG%20Meeting%20Material/SN%2021%20Binder1.pdf): integer nearest, exact .5 toward warmer; negative-zero coding retains M, explicitly -0.5 -> M00. [ICAO Annex3 section4.6](https://www.icao.int/Meetings/METDIV14/Documents/an03_cons_secured.pdf) corroborates. Public copies are older standard editions; current-edition access was not established. This limitation is explicit, and boundary behavior follows their unambiguous examples.

## METAR.ws / D-ATIS — interfaces only, no connection

- [Current provider WS overview](https://metar.ws/websocket-metar-api): `wss://stream.metar.ws/v1`, auth required; obsTime,receiptTime and original rawOb distinct. METAR/SPECI and frequent observations depend on plan.
- [Historical service](https://metar.ws/historical-metar-api): documented functionality; exact REST route/auth protocol not verified here, so none invented.
- [Terms](https://metar.ws/terms-of-service): commercial service, not an open data redistribution license. No provider payload committed.
- Professional D-ATIS is optional. The message/auth specification and our access
  were not verified. `MetarWsAtisSource` is a typed future interface, not a fake working client.
- Existing lab socket and its key are untouched. Optional env names in .env.example
  reserve configuration; M1 does not read them or open another connection.

## Coverage limit

EHAM has two full-report paths in M1. EDDM has only AWC; DWD here supplies candidates,
not a second full-METAR feed. Measuring global earliest publication is impossible
from these paths. Extending EDDM provider race is an explicit M2 requirement.

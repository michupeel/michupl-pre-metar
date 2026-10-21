"""One bounded, raw-first documentation/endpoint verification; no credentials."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from ssl import PROTOCOL_TLS_CLIENT
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import truststore

URLS = {
    "dwd_stations": "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/historical/zehn_min_tu_Beschreibung_Stationen.txt",
    "dwd_now": "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/now/10minutenwerte_TU_01262_now.zip",
    "knmi_metar": "https://d2whtzszevhgqk.cloudfront.net/metar-EHAM-latest.xml",
    "awc": "https://aviationweather.gov/api/data/metar?ids=EDDM,EHAM&format=json",
    "awc_openapi": "https://aviationweather.gov/data/schema/openapi.yaml",
    "dwd_description": "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/DESCRIPTION_obsgermany_climate_10min_air_temperature_en.pdf",
}

if __name__ == "__main__":
    root = Path("data/verification") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    root.mkdir(parents=True)
    for name, url in URLS.items():
        start = datetime.now(UTC).isoformat()
        try:
            try:
                response = urlopen(
                    Request(
                        url,
                        headers={
                            "User-Agent": "michupl-pre-metar/0.1 research endpoint verification"
                        },
                    ),
                    timeout=30,
                    context=truststore.SSLContext(PROTOCOL_TLS_CLIENT),
                )
            except HTTPError as exc:
                response = exc
            body = response.read()
            end = datetime.now(UTC).isoformat()
            (root / (name + ".bin")).write_bytes(body)
            meta = {
                "url": url,
                "status": response.code,
                "start": start,
                "receive": end,
                "sha256": hashlib.sha256(body).hexdigest(),
                "headers": {
                    k: response.headers[k]
                    for k in ("Date", "Last-Modified", "Content-Type", "ETag")
                    if k in response.headers
                },
            }
            (root / (name + ".json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
            print(name, response.code, len(body), meta["sha256"], flush=True)
        except Exception as exc:
            print(name, type(exc).__name__, flush=True)
    print(root)

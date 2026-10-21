import csv
import io
import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from defusedxml import ElementTree

from premetar.model import Observation

IDENTITY = re.compile(r"\b(?:(METAR|SPECI)\s+)?(?:COR\s+)?([A-Z]{4})\s+(\d{6})Z\b")
TEMPERATURE = re.compile(r"(?<!\S)(M?\d{2}|//)/(M?\d{2}|//)(?=\s|=|$)")


def resolve_ddhhmm(value: str, anchor: datetime) -> datetime:
    """Nearest valid adjacent month, anchored to an aware provider/receipt clock."""
    if anchor.tzinfo is None:
        raise ValueError("Anchor must be timezone-aware")
    anchor = anchor.astimezone(UTC)
    day, hour, minute = int(value[:2]), int(value[2:4]), int(value[4:])
    choices = []
    for offset in (-1, 0, 1):
        index = anchor.year * 12 + anchor.month - 1 + offset
        year, month = divmod(index, 12)
        try:
            choices.append(datetime(year, month + 1, day, hour, minute, tzinfo=UTC))
        except ValueError:
            continue
    if not choices:
        raise ValueError("Invalid DDHHMMZ")
    result = min(choices, key=lambda t: abs(t - anchor))
    if abs(result - anchor) > timedelta(days=20):
        raise ValueError("Ambiguous DDHHMMZ")
    return result


def _temp(value: str) -> Decimal | None:
    return None if value == "//" else Decimal(value.replace("M", "-"))


def parse_metar(raw: str, anchor: datetime, source: str) -> Observation:
    match = IDENTITY.search(raw)
    if match is None:
        raise ValueError("No METAR identity")
    kind, station, time = match.groups()
    temperature = TEMPERATURE.search(raw.split(" RMK ", 1)[0])
    if temperature is None:
        raise ValueError("No METAR temperature group")
    nominal = resolve_ddhhmm(time, anchor)
    return Observation(
        station_icao=station,
        source=source,
        product_type="SPECI" if kind == "SPECI" else "METAR",
        event_time=nominal,
        report_time=nominal,
        temperature_c=_temp(temperature[1]),
        dewpoint_c=_temp(temperature[2]),
        temperature_precision=Decimal(1),
        raw_text=raw,
        auto="AUTO" in raw.split(),
        cor="COR" in raw.split(),
        metadata_json={"temperature_token": temperature[1], "dewpoint_token": temperature[2]},
    )


def parse_awc(body: bytes, anchor: datetime) -> list[Observation]:
    rows = json.loads(body)
    if not isinstance(rows, list):
        raise ValueError("AWC response must be an array")
    observations = []
    for row in rows:
        obs = parse_metar(row["rawOb"], anchor, "awc")
        if obs.station_icao != row["icaoId"]:
            raise ValueError("AWC station mismatch")
        if row.get("metarType") == "SPECI":
            obs.product_type = "SPECI"
        if row.get("receiptTime"):
            obs.source_receipt_time = datetime.fromisoformat(
                row["receiptTime"].replace("Z", "+00:00")
            )
        obs.metadata_json.update(
            {"awc_report_time": row.get("reportTime"), "awc_obs_time": row.get("obsTime")}
        )
        observations.append(obs)
    return observations


def parse_knmi_metar(body: bytes, anchor: datetime) -> list[Observation]:
    text = body.decode("utf-8")
    start = text.find("<?xml")
    if start < 0:
        raise ValueError("Missing IWXXM XML")
    root = ElementTree.fromstring(text[start:])
    comments = re.findall(r"<!--\s*((?:METAR|SPECI)\s+.*?)\s*-->", text, re.DOTALL)
    if len(comments) != 1:
        raise ValueError("Expected one original TAC comment")
    obs = parse_metar(comments[0], anchor, "knmi_metar")
    if obs.station_icao != "EHAM":
        raise ValueError("Unexpected KNMI station")
    upstream = root.attrib.get("translatedBulletinReceptionTime")
    if upstream:
        obs.source_receipt_time = datetime.fromisoformat(upstream.replace("Z", "+00:00"))
    obs.metadata_json.update(
        {
            "iwxxm_translation_time": root.attrib.get("translationTime"),
            "iwxxm_report_status": root.attrib.get("reportStatus"),
        }
    )
    return [obs]


def parse_dwd(body: bytes, anchor: datetime) -> list[Observation]:
    del anchor
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = [
            n
            for n in archive.namelist()
            if n.startswith(("produkt_zehn_min_tu_", "produkt_zehn_now_tu_")) and n.endswith(".txt")
        ]
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 5_000_000:
            raise ValueError("Unexpected DWD archive")
        text = archive.read(names[0]).decode("latin-1")
    rows = csv.DictReader(io.StringIO(text), delimiter=";")
    observations = []
    for original in rows:
        row = {k.strip(): v.strip() for k, v in original.items()}
        if row["STATIONS_ID"].zfill(5) != "01262":
            raise ValueError("DWD station mismatch")
        if row["TT_10"] == "-999":
            continue
        timestamp = datetime.strptime(row["MESS_DATUM"], "%Y%m%d%H%M").replace(tzinfo=UTC)
        observations.append(
            Observation(
                station_icao="EDDM",
                source="dwd_10min",
                product_type="DWD_10MIN",
                event_time=timestamp,
                temperature_c=Decimal(row["TT_10"]),
                temperature_precision=Decimal("0.1"),
                dewpoint_c=None if row["TD_10"] == "-999" else Decimal(row["TD_10"]),
                pressure=None if row["PP_10"] == "-999" else Decimal(row["PP_10"]),
                raw_text=json.dumps(row, sort_keys=True),
                metadata_json={
                    "dwd_station_id": "01262",
                    "quality": row.get("QN"),
                    "sensor_parity": "unverified",
                },
            )
        )
    return observations

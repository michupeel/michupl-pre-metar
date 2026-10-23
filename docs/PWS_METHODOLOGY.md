# Open PWS methodology

This is a research subsystem, not a validated airport thermometer or information
edge. Qwen supplied an initial outline; unsupported selection/tie/provenance
claims in that draft were removed during review.

## Provenance

Provider → station/location group → sensor → observation → arrivals. Station
identities never merge across platforms. Nearby locations are only duplicate
candidates; the inventory and original metadata remain intact. Discovery snapshots
retain raw references, distance and metadata changes. Raw HTTP bytes are durable
before JSON parsing. Every arrival retains request/receive clocks and raw hash;
identical sensor/value/time records deduplicate without deleting arrivals.
`pws_observation_provenance` exposes their joins, including airport associations.

All normalized clocks are aware UTC. Unknown measurement and publication clocks
stay NULL. Sensor.Community's server-ingest clock is named separately. Historical
downloads cannot acquire retrospective collector availability. Startups are
censored for latency, including the first successful snapshot of each station
in a collection run. Observation values, not HTTP response frequency, determine
update cadence.

## Deterministic QC

Metadata distinguishes known indoor/mobile sites and missing temperature sensors
from unknown hardware. The confidence categories are VERIFIED_METADATA,
PARTIAL_METADATA and UNKNOWN_METADATA; provider declarations do not verify siting.
Reported elevation is retained, but lapse adjustment requires explicitly verified
elevations on both compared stations.

Physical flags cover nonfinite/impossible values, unknown units, humidity outside
0–100%, malformed and future clocks. Defaults -95..65°C allow real extreme weather
and can be adjusted for the study's climate. Naive internal timestamps are rejected.
Temporal checks sort event times, collapse exact duplicates, flag conflicting
values, quantify median/p90 intervals, longest gap, missing intervals, freshness
and irregularity. Unchanged readings alone yield only STUCK_SUSPECT after six
hours. The standalone diagnostic can label STUCK_SENSOR only with corroborating
peer variation. Automated historical peer corroboration of a stuck sensor remains
experimental; normal QC snapshots do not manufacture it.

Availability is a completeness proxy over the observed span, not independently
verified station uptime. It is NULL without a declared cadence or at least ten
intervals from which to infer a median cadence. Inferred denominators are labelled.
Unobserved periods before the first capture and during collector outages cannot
be certified. Freshness distinguishes sensor-event age from server-clock age.

Spatial comparison uses nearby eligible peers, distance-weighted medians and one
vote per 200m location cluster. Three distinct peer clusters are required. This
is a conservative independence proxy, not proof of independent hardware. Persistent
differences remain MICROCLIMATE_OR_SENSOR_BIAS flags. They are not destructive
exclusions. Historical diagnostics use values available by each sample's receipt,
with a bounded most-recent-1000-sample window.

Solar checks use Astral's actual solar elevation: day >10°, night <-6°.
A positive day/night peer-residual contrast requires at least 20 samples in each
regime over three dates. SOLAR_HEATING_SUSPECT is a heuristic, not a siting diagnosis;
clear-sky conditions and surface/microclimate differences are not resolved here.

## Quantization, calibration and evaluation

Reuse the existing METAR pipeline and Decimal ICAO rounding: nearest integer,
exact ties toward warmer, including negative halves. Integer n represents
`[n-.5,n+.5)`. Distance to this interval is not exact continuous-temperature error.
At the open upper boundary its infimum is zero, while exact integer prediction
still fails. Both metrics are therefore reported separately.

Rolling median/mean corrections fit signed interval-projection residuals, labelled
QUANTIZED_INTERVAL_PROJECTION. They are estimates with quantization uncertainty,
not exact thermometer bias or a guarantee of matching a boundary. Existing
DWD10min observations support a separate approximate0.1°C reference comparison:
PWS measurement times must be known and within300s of the reference event.
Past-only rolling mean/median point-bias correction is evaluated separately and
never substituted for METAR interval calibration. Reported precision does not
verify sensor parity or make DWD values exact continuous truth. Conflicting
reference revisions are excluded; no second official collector is introduced.

Exploratory retrospective pairs use a fixed ten-minute pre-target decision point,
metadata known at that point and the latest available eligible reading from a
stable sensor identity. Calibration labels must have been publicly received by
our collector strictly before the decision. Walk-forward evaluation uses no random
split. Raw and calibrated accuracy share the same evaluated targets; last-METAR
persistence is compared only when available on those targets. Integer performance,
interval error, incremental match rate and day/night subsets are separate outputs.
This fixed-lead replay is not a stored prospective prediction or timing-advantage
measurement; routine-slot/SPECI completeness needs additional source coverage.

## Ranking, selection and predictions

Provisional component weights are predictive 30%, temporal 20%, freshness 15%,
spatial 15%, geographic 10%, metadata confidence 10%. Store components separately;
missing components or fewer than 100 OOS samples on seven evaluation dates yields
a NULL score and UNVERIFIED status. No automatic TRUSTED promotion exists.
Scores/thresholds are experimental conventions, not a meteorological standard.
Automatic selection uses CANDIDATE rows only; new stations can be monitored by
manual selection with an explicit audit reason. Manual exclusion is also audited.

The estimator supports equal_weights, inverse_distance, inverse_historical_error
and quality_weighted. It uses selection events, metadata, receive times,
calibrations and quality snapshots available at its decision cutoff. Historical
error weights require sufficient prior OOS samples. Nearby contributors are
conservatively clustered, without changing stored station identities. Indoor,
mobile, stale, impossible, conflicting or confirmed-stuck inputs are excluded.

Predictions have a future target, input cutoff, completion timestamp, run-scoped
monotonic marker, immutable contributor IDs and configuration. SQLite rejects
updates, deletes and replacement of a prior prediction. No target result is used
to select its contributors. Replay does not insert historical predictions.

Accuracy is evaluated against later captured, unambiguous routine METARs. UTC
receive differences are reported separately from information-lead evidence.
The current bounded collector does **not** certify continuous capture coverage;
`capture_coverage_verified=false`, so it does not award a measured information
lead. More prospective collection, coverage audits, frozen station selection and
an untouched evaluation period are required before such a claim.

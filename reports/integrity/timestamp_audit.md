# Strict timestamp audit

As of 2026-10-24T17:33:27.747261+00:00

| Provider | Total | Valid at receipt | Valid measurement timestamps | Stale at receipt | Invalid/unknown | Quarantined | Eligible now |
|---|---:|---:|---:|---:|---:|---:|---:|
|sensor_community|2744|0|0|0|2744|2744|0|
|opensensemap|1265|325|328|3|937|940|5|

Valid at receipt describes historical captured observations, not freshness now. Stale means age exceeded the 300-second policy at first receipt; current age is checked separately. Unknown/server-ingest clocks never become measurement clocks. Raw and normalized evidence are retained; exclusions append without modifying predictions/settlements.

{
  "as_of": "2026-10-24T17:33:27.747261+00:00",
  "policy_version": "strict-measurement-time-1.0",
  "maximum_age_seconds": 300,
  "providers": {
    "sensor_community": {
      "total": 2744,
      "valid_at_receipt": 0,
      "valid_measurement_timestamps": 0,
      "stale_at_receipt": 0,
      "invalid_or_unknown": 2744,
      "invalid_timestamps": 0,
      "unknown_timestamp_provenance": 2744,
      "quarantined": 2744,
      "prediction_eligible_now": 0,
      "currently_stale": 0
    },
    "opensensemap": {
      "total": 1265,
      "valid_at_receipt": 325,
      "valid_measurement_timestamps": 328,
      "stale_at_receipt": 3,
      "invalid_or_unknown": 937,
      "invalid_timestamps": 2,
      "unknown_timestamp_provenance": 935,
      "quarantined": 940,
      "prediction_eligible_now": 5,
      "currently_stale": 323
    }
  },
  "rejections": {
    "sensor_community": {
      "MISSING_MEASUREMENT_TIME": 2744,
      "UNKNOWN_TIMESTAMP_PROVENANCE": 2744
    },
    "opensensemap": {
      "IMPLAUSIBLE_TEMPERATURE": 936,
      "INVALID_TEMPERATURE": 935,
      "MISSING_MEASUREMENT_TIME": 935,
      "UNKNOWN_TIMESTAMP_PROVENANCE": 935,
      "STALE_AT_DECISION": 3,
      "STALE_AT_RECEIPT": 3,
      "FUTURE_MEASUREMENT_AT_DECISION": 2,
      "FUTURE_MEASUREMENT_AT_RECEIPT": 2
    }
  },
  "predictions": {
    "total": 1249,
    "valid": 624,
    "excluded": 625,
    "pending_settlements": 0,
    "valid_matched_outcomes": 624,
    "distinct_target_cycles": 44,
    "exclusion_reasons": {
      "MISSING_MEASUREMENT_TIME": 1745,
      "UNKNOWN_TIMESTAMP_PROVENANCE": 1745,
      "STALE_AT_DECISION": 144,
      "TARGET_ALREADY_RECEIVED": 4,
      "UNVERIFIED_PARAMETER_TIMESTAMP_POLICY": 1886,
      "FUTURE_MEASUREMENT_AT_RECEIPT": 2
    }
  }
}

The old code used provider ingestion/publication as an effective-time fallback; it did not fill missing Sensor.Community observation_time with collector time. Sensor.Community has no verified measurement-time field in the audited API and is quarantined for analytical use. openSenseMap createdAt is the documented measurement timestamp; semantics are API-verified, not independent device-clock certification.

# EXP-0014 — EPWA forecast realization

Immutable metric cutoff: 2026-10-28T23:26:01.203986+00:00. No production model changes.

Current deterministic assessment (not a calibrated probability):

```json
{
  "adaptive_tmax": {
    "method": "DAMPED_PERSISTENT_INTERVAL_RESIDUAL_WITH_REMAINING_WARMING_v1",
    "status": "EXPERIMENTAL / INSUFFICIENT DATA",
    "temperature_c": null,
    "time": null,
    "validated": false
  },
  "cloud": {
    "caveat": "CATEGORY_AND_BASE_ONLY_NO_EXACT_AREA_FRACTION_OR_CLOUD_TOP; CAVOK_NSC_NCD_NOT_CLOUDLESS",
    "forecast_low_cloud_percent": 86.0,
    "low_layer_rule": "REPORTED_BASE_AT_OR_BELOW6500FT_NOT_EQUIVALENT_TO_MODEL_VOLUME",
    "no_exact_observed_percent": true,
    "observed_categories": [
      {
        "amount": "BKN",
        "amount_okta_range": [
          5,
          7
        ],
        "base_ft": 900,
        "kind": null
      },
      {
        "amount": "BKN",
        "amount_okta_range": [
          5,
          7
        ],
        "base_ft": 2300,
        "kind": null
      }
    ],
    "status": "BROADLY CONSISTENT"
  },
  "confidence": "INSUFFICIENT DATA",
  "created_at": "2026-10-28T23:25:32.558302+00:00",
  "eligible_pws_ids": [
    "d143f860db82f311dc30703a1cb247e55643a7594f5dcc255c462e542add56aa",
    "e8c4801abe9843320ebc91c187c1a8f02defa060b71a1053310e25d863939fdb"
  ],
  "empirical_predictive_confidence": "NOT_VALIDATED",
  "evidence": {
    "cloud_effect": "UNTESTED_ASSOCIATION_NOT_CAUSAL",
    "forecast_age_seconds": 1645.125233,
    "hours_to_tmax": 13.574289360555555,
    "independent_recent_cycles": 1,
    "latest_measurement_age_seconds": 1532.558302,
    "latest_reference_alignment_missing": false,
    "latest_residual_c": -0.0,
    "persistent_residual_c": null,
    "rates": {
      "actual_c_per_hour": null,
      "error_trend_c_per_hour": null,
      "forecast_c_per_hour": null,
      "forecasts_may_differ": false,
      "mismatch_c_per_hour": null,
      "quantization_uncertainty_c_per_hour": null
    },
    "rejected": {},
    "remaining_warming_c": 1.9425710639444453,
    "required_cycles": 3,
    "solar_elevation_degrees": -49.030472818522384
  },
  "explanation": "METAR 9°C; ICON 8.50°C (DIRECT_HOURLY_POINT); reszta względem przedziału METAR -0.00°C.",
  "forecast_at_metar": 8.5,
  "forecast_snapshot_id": "f293af0e12e51d8f2f7479d7803a5f98579824dda8c6988cd4c9e7639a840798",
  "forecast_tmax": {
    "complete": true,
    "hours": 24,
    "semantics": "MAX_OF_HOURLY_POINT_FORECASTS_NOT_DAILY_OR_HOURLY_MAXIMUM",
    "temperature_c": 10.4,
    "time": "2026-10-29T13:00:00+00:00",
    "times": [
      "2026-10-29T13:00:00+00:00"
    ]
  },
  "history": [
    {
      "alignment": "DIRECT_HOURLY_POINT",
      "cloud": {
        "caveat": "CATEGORY_AND_BASE_ONLY_NO_EXACT_AREA_FRACTION_OR_CLOUD_TOP; CAVOK_NSC_NCD_NOT_CLOUDLESS",
        "forecast_low_cloud_percent": 86.0,
        "low_layer_rule": "REPORTED_BASE_AT_OR_BELOW6500FT_NOT_EQUIVALENT_TO_MODEL_VOLUME",
        "no_exact_observed_percent": true,
        "observed_categories": [
          {
            "amount": "BKN",
            "amount_okta_range": [
              5,
              7
            ],
            "base_ft": 900,
            "kind": null
          },
          {
            "amount": "BKN",
            "amount_okta_range": [
              5,
              7
            ],
            "base_ft": 2300,
            "kind": null
          }
        ],
        "status": "BROADLY CONSISTENT"
      },
      "conditions": {
        "cloud_clear_codes": [],
        "cloud_layers": [
          {
            "amount": "BKN",
            "amount_okta_range": [
              5,
              7
            ],
            "base_ft": 900,
            "kind": null
          },
          {
            "amount": "BKN",
            "amount_okta_range": [
              5,
              7
            ],
            "base_ft": 2300,
            "kind": null
          }
        ],
        "cloud_status": "REPORTED",
        "cloud_uncertainty": "CATEGORY_AND_BASE_ONLY_NO_EXACT_AREA_FRACTION_OR_CLOUD_TOP; CAVOK_NSC_NCD_NOT_CLOUDLESS",
        "dew_point_c": 8.0,
        "malformed_cloud_tokens": [],
        "precipitation_indicated": false,
        "raw_text": "METAR EPWA 282300Z 29005KT 9999 BKN009 BKN023 09/08 Q1024 NOSIG",
        "significant_weather": [],
        "station": "EPWA",
        "temperature_c": 9.0,
        "visibility": {
          "qualifier": "AT_LEAST",
          "source": "BODY",
          "unit": "m",
          "value": 10000
        },
        "wind": {
          "direction_degrees": 290,
          "gust": null,
          "speed": 5,
          "unit": "KT",
          "variable": false
        }
      },
      "first_received": "2026-10-28T23:03:08.486749+00:00",
      "forecast_first_received": "2026-10-28T22:58:07.433069+00:00",
      "forecast_snapshot_id": "f293af0e12e51d8f2f7479d7803a5f98579824dda8c6988cd4c9e7639a840798",
      "forecast_temperature_c": 8.5,
      "metar_id": "190cdb7491f4834edbc76e42b16584709aef36d919b0349d28911234db688d95",
      "metar_interval_c": [
        8.5,
        9.5
      ],
      "midpoint_error_c": 0.5,
      "nominal_time": "2026-10-28T23:00:00+00:00",
      "signed_interval_residual_c": -0.0,
      "temperature_c": 9.0,
      "upper_interval_open": true
    }
  ],
  "latest_metar": {
    "alignment": "DIRECT_HOURLY_POINT",
    "cloud": {
      "caveat": "CATEGORY_AND_BASE_ONLY_NO_EXACT_AREA_FRACTION_OR_CLOUD_TOP; CAVOK_NSC_NCD_NOT_CLOUDLESS",
      "forecast_low_cloud_percent": 86.0,
      "low_layer_rule": "REPORTED_BASE_AT_OR_BELOW6500FT_NOT_EQUIVALENT_TO_MODEL_VOLUME",
      "no_exact_observed_percent": true,
      "observed_categories": [
        {
          "amount": "BKN",
          "amount_okta_range": [
            5,
            7
          ],
          "base_ft": 900,
          "kind": null
        },
        {
          "amount": "BKN",
          "amount_okta_range": [
            5,
            7
          ],
          "base_ft": 2300,
          "kind": null
        }
      ],
      "status": "BROADLY CONSISTENT"
    },
    "conditions": {
      "cloud_clear_codes": [],
      "cloud_layers": [
        {
          "amount": "BKN",
          "amount_okta_range": [
            5,
            7
          ],
          "base_ft": 900,
          "kind": null
        },
        {
          "amount": "BKN",
          "amount_okta_range": [
            5,
            7
          ],
          "base_ft": 2300,
          "kind": null
        }
      ],
      "cloud_status": "REPORTED",
      "cloud_uncertainty": "CATEGORY_AND_BASE_ONLY_NO_EXACT_AREA_FRACTION_OR_CLOUD_TOP; CAVOK_NSC_NCD_NOT_CLOUDLESS",
      "dew_point_c": 8.0,
      "malformed_cloud_tokens": [],
      "precipitation_indicated": false,
      "raw_text": "METAR EPWA 282300Z 29005KT 9999 BKN009 BKN023 09/08 Q1024 NOSIG",
      "significant_weather": [],
      "station": "EPWA",
      "temperature_c": 9.0,
      "visibility": {
        "qualifier": "AT_LEAST",
        "source": "BODY",
        "unit": "m",
        "value": 10000
      },
      "wind": {
        "direction_degrees": 290,
        "gust": null,
        "speed": 5,
        "unit": "KT",
        "variable": false
      }
    },
    "first_received": "2026-10-28T23:03:08.486749+00:00",
    "forecast_first_received": "2026-10-28T22:58:07.433069+00:00",
    "forecast_snapshot_id": "f293af0e12e51d8f2f7479d7803a5f98579824dda8c6988cd4c9e7639a840798",
    "forecast_temperature_c": 8.5,
    "metar_id": "190cdb7491f4834edbc76e42b16584709aef36d919b0349d28911234db688d95",
    "metar_interval_c": [
      8.5,
      9.5
    ],
    "midpoint_error_c": 0.5,
    "nominal_time": "2026-10-28T23:00:00+00:00",
    "signed_interval_residual_c": -0.0,
    "temperature_c": 9.0,
    "upper_interval_open": true
  },
  "midpoint_error_c": 0.5,
  "observed_maximum_semantics": "AVAILABLE_ROUTINE_INTEGER_REPORTS_NOT_FINAL_SETTLEMENT_TMAX",
  "observed_metar_maximum_c": 9.0,
  "quality": "AVAILABLE",
  "residual_c": -0.0,
  "rule_version": "EPWA-REALIZATION-v1.1",
  "state": "ON TRACK",
  "supporting_metar_ids": [
    "190cdb7491f4834edbc76e42b16584709aef36d919b0349d28911234db688d95"
  ],
  "temporal_policy": "LATEST_FORECAST_RECEIVED_STRICTLY_BEFORE_EACH_METAR_NOMINAL_TIME; BOTH_EVENT_AND_RECEIPT_LE_DECISION; NO_FUTURE_CORRECTION",
  "trading_instruction": false,
  "trend": "TREND UNCERTAIN",
  "validated_probability": null,
  "weather_gate": false
}
```

Forecast snapshot must predate nominal observation; midpoint error is not precise thermometer error. Interval residual, direct vs interpolated forecast, latest available corrections and first receipts are exported. Cloud association is untested; no solar/cloud causal claim. Adaptive Tmax is experimental; daily API aggregate and hourly-point peak are different targets.

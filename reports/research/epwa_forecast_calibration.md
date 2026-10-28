# EPWA — audited forward-only forecast calibration

No model promotion. Archive replay is APPROXIMATE: requested initialization is explicit, original API publication/availability is unknown. Decision scenario init+6h is not an observed public receipt. Prospective inputs remain separate.

## Model support — actual requests

- icon_global: {"status": "ARCHIVED_RUNS_VERIFIED_COORDINATE_RESPONSE", "runs": 7, "first_received": "2026-10-28T17:01:03.371744+00:00", "returned_coordinates": [52.125, 21.0], "publication_time": null}
- icon_eu: {"status": "ARCHIVED_RUNS_VERIFIED_COORDINATE_RESPONSE", "runs": 7, "first_received": "2026-10-28T17:01:07.137935+00:00", "returned_coordinates": [52.1875, 20.9375], "publication_time": null}
- icon_d2: {"status": "UNAVAILABLE_AT_REQUESTED_EPWA_COORDINATES", "http_status": 400, "reason": "No data is available for this location"}

## Cross-model comparison on identical target/decision pairs

Model | Method | Matched pairs | Independent targets | Days | Interval MAE C
--- | --- | ---: | ---: | ---: | ---:
icon_eu | RAW | 428 | 94 | 5 | 1.154206
icon_global | RAW | 428 | 94 | 5 | 1.082944
icon_eu | GLOBAL_MEDIAN | 428 | 94 | 5 | 1.163318
icon_global | GLOBAL_MEDIAN | 428 | 94 | 5 | 1.093458
icon_eu | HOUR_HORIZON_MEDIAN | 428 | 94 | 5 | 1.154206
icon_global | HOUR_HORIZON_MEDIAN | 428 | 94 | 5 | 1.082944
icon_eu | CAUSAL_NOWCAST | 428 | 94 | 5 | 1.164356
icon_global | CAUSAL_NOWCAST | 428 | 94 | 5 | 1.091437

These hourly approximate-replay pairs are not independent daily Tmax outcomes. No final daily targets or validated Tmax error exist.

## Matched walk-forward hourly results

```json
[
  {
    "model": "icon_eu",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "CAUSAL_NOWCAST",
    "N": 428,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1643560826718846,
    "midpoint_mae": 1.6078229820344776,
    "midpoint_bias": 1.0565246446611216,
    "exact_integer_accuracy": 0.2336448598130841,
    "raw_interval_mae_same_pairs": 1.1542056074766356,
    "raw_integer_accuracy_same_pairs": 0.2266355140186916,
    "incremental_correct": 6,
    "incremental_harm": 3,
    "mean_interval_improvement": -0.010150475195249191,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 264,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  },
  {
    "model": "icon_eu",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "GLOBAL_MEDIAN",
    "N": 428,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1633177570093458,
    "midpoint_mae": 1.6067757009345793,
    "midpoint_bias": 0.9922897196261682,
    "exact_integer_accuracy": 0.2219626168224299,
    "raw_interval_mae_same_pairs": 1.1542056074766356,
    "raw_integer_accuracy_same_pairs": 0.2266355140186916,
    "incremental_correct": 11,
    "incremental_harm": 13,
    "mean_interval_improvement": -0.009112149532710296,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 341,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  },
  {
    "model": "icon_eu",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "HOUR_HORIZON_MEDIAN",
    "N": 428,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1542056074766356,
    "midpoint_mae": 1.5985981308411215,
    "midpoint_bias": 1.0813084112149534,
    "exact_integer_accuracy": 0.2266355140186916,
    "raw_interval_mae_same_pairs": 1.1542056074766356,
    "raw_integer_accuracy_same_pairs": 0.2266355140186916,
    "incremental_correct": 0,
    "incremental_harm": 0,
    "mean_interval_improvement": 0.0,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 428,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  },
  {
    "model": "icon_eu",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "RAW",
    "N": 428,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1542056074766356,
    "midpoint_mae": 1.5985981308411215,
    "midpoint_bias": 1.0813084112149534,
    "exact_integer_accuracy": 0.2266355140186916,
    "raw_interval_mae_same_pairs": 1.1542056074766356,
    "raw_integer_accuracy_same_pairs": 0.2266355140186916,
    "incremental_correct": 0,
    "incremental_harm": 0,
    "mean_interval_improvement": 0.0,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 0,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  },
  {
    "model": "icon_global",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "CAUSAL_NOWCAST",
    "N": 524,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1649526369378234,
    "midpoint_mae": 1.6077606047036848,
    "midpoint_bias": 1.013540412139337,
    "exact_integer_accuracy": 0.22137404580152673,
    "raw_interval_mae_same_pairs": 1.1580152671755726,
    "raw_integer_accuracy_same_pairs": 0.21946564885496184,
    "incremental_correct": 5,
    "incremental_harm": 4,
    "mean_interval_improvement": -0.00693736976225083,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 360,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  },
  {
    "model": "icon_global",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "GLOBAL_MEDIAN",
    "N": 524,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1666030534351146,
    "midpoint_mae": 1.6095419847328245,
    "midpoint_bias": 0.984351145038168,
    "exact_integer_accuracy": 0.22137404580152673,
    "raw_interval_mae_same_pairs": 1.1580152671755726,
    "raw_integer_accuracy_same_pairs": 0.21946564885496184,
    "incremental_correct": 7,
    "incremental_harm": 6,
    "mean_interval_improvement": -0.008587786259542003,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 437,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  },
  {
    "model": "icon_global",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "HOUR_HORIZON_MEDIAN",
    "N": 524,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1580152671755726,
    "midpoint_mae": 1.6022900763358778,
    "midpoint_bias": 1.0301526717557252,
    "exact_integer_accuracy": 0.21946564885496184,
    "raw_interval_mae_same_pairs": 1.1580152671755726,
    "raw_integer_accuracy_same_pairs": 0.21946564885496184,
    "incremental_correct": 0,
    "incremental_harm": 0,
    "mean_interval_improvement": 0.0,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 524,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  },
  {
    "model": "icon_global",
    "availability_class": "APPROXIMATE_REPLAY",
    "method": "RAW",
    "N": 524,
    "independent_targets": 94,
    "days": 5,
    "interval_mae": 1.1580152671755726,
    "midpoint_mae": 1.6022900763358778,
    "midpoint_bias": 1.0301526717557252,
    "exact_integer_accuracy": 0.21946564885496184,
    "raw_interval_mae_same_pairs": 1.1580152671755726,
    "raw_integer_accuracy_same_pairs": 0.21946564885496184,
    "incremental_correct": 0,
    "incremental_harm": 0,
    "mean_interval_improvement": 0.0,
    "improvement_interval": {
      "days": 5,
      "lower": null,
      "upper": null,
      "status": "INSUFFICIENT_20_INDEPENDENT_DAYS"
    },
    "fallback_raw_count": 0,
    "continuous_error_semantics": "METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR"
  }
]
```

## Daily Tmax — separate target

```json
{
  "status": "CALIBRATION_PENDING",
  "calibrated_tmax": null,
  "selected_model": null,
  "verified_reference_days": 0,
  "records": [],
  "previews": [
    {
      "model": "icon_eu",
      "run_id": "ae42fcd0ef170d4da673c2b9045fed222e2213f8f69fe83c80beaa4e35204c39",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-22",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.7,
      "forecast_peak_times": [
        "2026-10-21T22:00:00+00:00",
        "2026-10-22T11:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "ae42fcd0ef170d4da673c2b9045fed222e2213f8f69fe83c80beaa4e35204c39",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-23",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.3,
      "forecast_peak_times": [
        "2026-10-23T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "ae42fcd0ef170d4da673c2b9045fed222e2213f8f69fe83c80beaa4e35204c39",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-24",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 14.3,
      "forecast_peak_times": [
        "2026-10-24T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "ae42fcd0ef170d4da673c2b9045fed222e2213f8f69fe83c80beaa4e35204c39",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.5,
      "forecast_peak_times": [
        "2026-10-25T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "6e04d6279730568af1dc4d9c7dd325529f83e6333c30496526a4c7f4d9e1eadc",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-22",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.8,
      "forecast_peak_times": [
        "2026-10-22T11:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "6e04d6279730568af1dc4d9c7dd325529f83e6333c30496526a4c7f4d9e1eadc",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-23",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.2,
      "forecast_peak_times": [
        "2026-10-23T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "6e04d6279730568af1dc4d9c7dd325529f83e6333c30496526a4c7f4d9e1eadc",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-24",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 14.2,
      "forecast_peak_times": [
        "2026-10-24T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "6e04d6279730568af1dc4d9c7dd325529f83e6333c30496526a4c7f4d9e1eadc",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.3,
      "forecast_peak_times": [
        "2026-10-25T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "6e04d6279730568af1dc4d9c7dd325529f83e6333c30496526a4c7f4d9e1eadc",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.3,
      "forecast_peak_times": [
        "2026-10-25T23:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "6e04d6279730568af1dc4d9c7dd325529f83e6333c30496526a4c7f4d9e1eadc",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-21T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.7,
      "forecast_peak_times": [
        "2026-10-27T12:00:00+00:00",
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "e26ddf30ee4aa2909fd25162c9b6c9f0f7458acb35383e90ce5282003a13fc85",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-23",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.8,
      "forecast_peak_times": [
        "2026-10-23T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "e26ddf30ee4aa2909fd25162c9b6c9f0f7458acb35383e90ce5282003a13fc85",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-24",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 14.3,
      "forecast_peak_times": [
        "2026-10-24T12:00:00+00:00",
        "2026-10-24T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "e26ddf30ee4aa2909fd25162c9b6c9f0f7458acb35383e90ce5282003a13fc85",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 14.0,
      "forecast_peak_times": [
        "2026-10-25T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "e26ddf30ee4aa2909fd25162c9b6c9f0f7458acb35383e90ce5282003a13fc85",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.0,
      "forecast_peak_times": [
        "2026-10-26T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3a6008c93373c897ac0f42ceafd7980cb0b4022c0100cee50e7ab6f9199543fd",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-23",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.7,
      "forecast_peak_times": [
        "2026-10-23T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3a6008c93373c897ac0f42ceafd7980cb0b4022c0100cee50e7ab6f9199543fd",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-24",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 14.3,
      "forecast_peak_times": [
        "2026-10-24T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3a6008c93373c897ac0f42ceafd7980cb0b4022c0100cee50e7ab6f9199543fd",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.8,
      "forecast_peak_times": [
        "2026-10-25T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3a6008c93373c897ac0f42ceafd7980cb0b4022c0100cee50e7ab6f9199543fd",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.9,
      "forecast_peak_times": [
        "2026-10-26T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3a6008c93373c897ac0f42ceafd7980cb0b4022c0100cee50e7ab6f9199543fd",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.4,
      "forecast_peak_times": [
        "2026-10-27T12:00:00+00:00",
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3a6008c93373c897ac0f42ceafd7980cb0b4022c0100cee50e7ab6f9199543fd",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-22T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.1,
      "forecast_peak_times": [
        "2026-10-28T12:00:00+00:00",
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "8d2216d1416c787ba85fb478a99c591dd1f47af00a00401ec3095be9f3c3e2c5",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-24",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.6,
      "forecast_peak_times": [
        "2026-10-24T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "8d2216d1416c787ba85fb478a99c591dd1f47af00a00401ec3095be9f3c3e2c5",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.3,
      "forecast_peak_times": [
        "2026-10-25T13:00:00+00:00",
        "2026-10-25T14:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "8d2216d1416c787ba85fb478a99c591dd1f47af00a00401ec3095be9f3c3e2c5",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.9,
      "forecast_peak_times": [
        "2026-10-26T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "8d2216d1416c787ba85fb478a99c591dd1f47af00a00401ec3095be9f3c3e2c5",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.7,
      "forecast_peak_times": [
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "2a56946acb2057bf326ed3264ee05125181360c25996ebafbdeb3ad08e89d645",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-24",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.6,
      "forecast_peak_times": [
        "2026-10-24T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "2a56946acb2057bf326ed3264ee05125181360c25996ebafbdeb3ad08e89d645",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.2,
      "forecast_peak_times": [
        "2026-10-25T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "2a56946acb2057bf326ed3264ee05125181360c25996ebafbdeb3ad08e89d645",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.7,
      "forecast_peak_times": [
        "2026-10-26T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "2a56946acb2057bf326ed3264ee05125181360c25996ebafbdeb3ad08e89d645",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.6,
      "forecast_peak_times": [
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "2a56946acb2057bf326ed3264ee05125181360c25996ebafbdeb3ad08e89d645",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.4,
      "forecast_peak_times": [
        "2026-10-28T12:00:00+00:00",
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "2a56946acb2057bf326ed3264ee05125181360c25996ebafbdeb3ad08e89d645",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-23T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.8,
      "forecast_peak_times": [
        "2026-10-29T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "f7a36da40739629b0b07eb5fc89bf2ab0c071af1cc6387f67f9c8f95e2ec145b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.4,
      "forecast_peak_times": [
        "2026-10-25T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "f7a36da40739629b0b07eb5fc89bf2ab0c071af1cc6387f67f9c8f95e2ec145b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.6,
      "forecast_peak_times": [
        "2026-10-26T12:00:00+00:00",
        "2026-10-26T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "f7a36da40739629b0b07eb5fc89bf2ab0c071af1cc6387f67f9c8f95e2ec145b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.5,
      "forecast_peak_times": [
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "f7a36da40739629b0b07eb5fc89bf2ab0c071af1cc6387f67f9c8f95e2ec145b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.0,
      "forecast_peak_times": [
        "2026-10-28T15:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "1eb9b310308ddc700063dffb9f3ca14ee206b3a7948d92b94c6c3c882a6a0a96",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-25",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 13.2,
      "forecast_peak_times": [
        "2026-10-25T12:00:00+00:00",
        "2026-10-25T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "1eb9b310308ddc700063dffb9f3ca14ee206b3a7948d92b94c6c3c882a6a0a96",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.6,
      "forecast_peak_times": [
        "2026-10-26T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "1eb9b310308ddc700063dffb9f3ca14ee206b3a7948d92b94c6c3c882a6a0a96",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.4,
      "forecast_peak_times": [
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "1eb9b310308ddc700063dffb9f3ca14ee206b3a7948d92b94c6c3c882a6a0a96",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.9,
      "forecast_peak_times": [
        "2026-10-28T15:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "1eb9b310308ddc700063dffb9f3ca14ee206b3a7948d92b94c6c3c882a6a0a96",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 9.2,
      "forecast_peak_times": [
        "2026-10-29T15:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "1eb9b310308ddc700063dffb9f3ca14ee206b3a7948d92b94c6c3c882a6a0a96",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-30",
      "decision_time": "2026-10-24T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.9,
      "forecast_peak_times": [
        "2026-10-30T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "bbc47ab79018efef311d63d7af16f23c5623fcc980b4926ff04c72a5b848efa1",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.3,
      "forecast_peak_times": [
        "2026-10-26T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "bbc47ab79018efef311d63d7af16f23c5623fcc980b4926ff04c72a5b848efa1",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.3,
      "forecast_peak_times": [
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "bbc47ab79018efef311d63d7af16f23c5623fcc980b4926ff04c72a5b848efa1",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.2,
      "forecast_peak_times": [
        "2026-10-28T12:00:00+00:00",
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "bbc47ab79018efef311d63d7af16f23c5623fcc980b4926ff04c72a5b848efa1",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.1,
      "forecast_peak_times": [
        "2026-10-29T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "0932372f6980778b10ed2fa81bc9a6ae520e4046de1e68ca1dfd7cff9f8483fa",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-26",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.3,
      "forecast_peak_times": [
        "2026-10-26T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "0932372f6980778b10ed2fa81bc9a6ae520e4046de1e68ca1dfd7cff9f8483fa",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.2,
      "forecast_peak_times": [
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "0932372f6980778b10ed2fa81bc9a6ae520e4046de1e68ca1dfd7cff9f8483fa",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.1,
      "forecast_peak_times": [
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "0932372f6980778b10ed2fa81bc9a6ae520e4046de1e68ca1dfd7cff9f8483fa",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.2,
      "forecast_peak_times": [
        "2026-10-29T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "0932372f6980778b10ed2fa81bc9a6ae520e4046de1e68ca1dfd7cff9f8483fa",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-30",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.2,
      "forecast_peak_times": [
        "2026-10-30T12:00:00+00:00",
        "2026-10-30T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "0932372f6980778b10ed2fa81bc9a6ae520e4046de1e68ca1dfd7cff9f8483fa",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-31",
      "decision_time": "2026-10-25T06:00:00+00:00",
      "raw_sampled_hourly_max": 8.2,
      "forecast_peak_times": [
        "2026-10-31T12:00:00+00:00",
        "2026-10-31T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "1cef8bbee8831234af57c9e17a1eace6026199aa78ba283f16075a0785025d7b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.2,
      "forecast_peak_times": [
        "2026-10-27T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "1cef8bbee8831234af57c9e17a1eace6026199aa78ba283f16075a0785025d7b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.8,
      "forecast_peak_times": [
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "1cef8bbee8831234af57c9e17a1eace6026199aa78ba283f16075a0785025d7b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.2,
      "forecast_peak_times": [
        "2026-10-29T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "1cef8bbee8831234af57c9e17a1eace6026199aa78ba283f16075a0785025d7b",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-30",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.6,
      "forecast_peak_times": [
        "2026-10-30T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "77c2cd7d309fd9f84df7c58b0d90b851a92965043bea44598711de7a4f2de90e",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-27",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 12.0,
      "forecast_peak_times": [
        "2026-10-27T12:00:00+00:00",
        "2026-10-27T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "77c2cd7d309fd9f84df7c58b0d90b851a92965043bea44598711de7a4f2de90e",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.7,
      "forecast_peak_times": [
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "77c2cd7d309fd9f84df7c58b0d90b851a92965043bea44598711de7a4f2de90e",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.1,
      "forecast_peak_times": [
        "2026-10-29T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "77c2cd7d309fd9f84df7c58b0d90b851a92965043bea44598711de7a4f2de90e",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-30",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 10.4,
      "forecast_peak_times": [
        "2026-10-30T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "77c2cd7d309fd9f84df7c58b0d90b851a92965043bea44598711de7a4f2de90e",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-31",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 8.3,
      "forecast_peak_times": [
        "2026-10-31T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "77c2cd7d309fd9f84df7c58b0d90b851a92965043bea44598711de7a4f2de90e",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-11-01",
      "decision_time": "2026-10-26T06:00:00+00:00",
      "raw_sampled_hourly_max": 9.1,
      "forecast_peak_times": [
        "2026-11-01T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "489409234667fc00b58ba47e93f224d8e1b8a94506ab324f28c1a70f1947726d",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.5,
      "forecast_peak_times": [
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "489409234667fc00b58ba47e93f224d8e1b8a94506ab324f28c1a70f1947726d",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 9.6,
      "forecast_peak_times": [
        "2026-10-29T16:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "489409234667fc00b58ba47e93f224d8e1b8a94506ab324f28c1a70f1947726d",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-30",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 9.9,
      "forecast_peak_times": [
        "2026-10-30T12:00:00+00:00",
        "2026-10-30T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_eu",
      "run_id": "489409234667fc00b58ba47e93f224d8e1b8a94506ab324f28c1a70f1947726d",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-31",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.5,
      "forecast_peak_times": [
        "2026-10-31T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3d2c64e421e7e91d5437c1893db56ecf02e2ebdab5b8163cb9fb5abe9a625401",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-28",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.5,
      "forecast_peak_times": [
        "2026-10-28T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3d2c64e421e7e91d5437c1893db56ecf02e2ebdab5b8163cb9fb5abe9a625401",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-29",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 9.5,
      "forecast_peak_times": [
        "2026-10-29T11:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3d2c64e421e7e91d5437c1893db56ecf02e2ebdab5b8163cb9fb5abe9a625401",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-30",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 9.8,
      "forecast_peak_times": [
        "2026-10-30T12:00:00+00:00",
        "2026-10-30T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3d2c64e421e7e91d5437c1893db56ecf02e2ebdab5b8163cb9fb5abe9a625401",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-10-31",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 11.2,
      "forecast_peak_times": [
        "2026-10-31T12:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3d2c64e421e7e91d5437c1893db56ecf02e2ebdab5b8163cb9fb5abe9a625401",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-11-01",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 8.3,
      "forecast_peak_times": [
        "2026-11-01T12:00:00+00:00",
        "2026-11-01T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    },
    {
      "model": "icon_global",
      "run_id": "3d2c64e421e7e91d5437c1893db56ecf02e2ebdab5b8163cb9fb5abe9a625401",
      "availability_class": "APPROXIMATE_REPLAY",
      "day": "2026-11-02",
      "decision_time": "2026-10-27T06:00:00+00:00",
      "raw_sampled_hourly_max": 7.7,
      "forecast_peak_times": [
        "2026-11-02T13:00:00+00:00"
      ],
      "training_days": 0,
      "correction_c": 0.0,
      "experimental_corrected_tmax": null,
      "semantics": "SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE"
    }
  ],
  "summary": [],
  "minimum_training_days": 14,
  "minimum_out_of_sample_days": 7,
  "minimum_uncertainty_days": 20,
  "reason": "REQUIRES_VERIFIED_FINAL_DAILY_HISTORY_14_TRAINING_AND_7_PROSPECTIVE_OOS_DAYS_WITH_PAIRED_IMPROVEMENT",
  "hourly_metar_max_used_as_daily_truth": false,
  "approximate_replay_can_promote": false,
  "uncertainty_note": "No confidence interval before20independent local days; descriptive blocks do not establish significance or guaranteed Tmax."
}
```

CALIBRATION PENDING: no verified final settlement targets. Current Warsaw contract rules prefer routine METAR precise T-group, else body integer; exclude SPECI and use the station local date and frozen corrections cutoff. This is not permission to substitute our incomplete routine-integer maximum as final truth. No sample/MAE/Tmax timing confidence is fabricated.

Sources: [Single Runs](https://open-meteo.com/en/docs/single-runs-api), [model clocks](https://open-meteo.com/en/docs/model-updates). Raw responses precede normalization in ignored archive.sqlite3. Every run/receipt/hash is retained.

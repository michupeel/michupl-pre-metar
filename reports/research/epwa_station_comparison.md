# EPWA station comparison — Milestone1.7

Snapshot: 2026-10-26T12:26:35.238222+00:00; SHA256 706dd79d7f8a7fe6e689cc61489abadd3851523864a07e09b5966082356a4c1c.

Protocol: docs/research/EPWA_M17_PROTOCOL.md. Collector rules unchanged; analysis is offline read-only. As-of replays below are retrospective, never live forecast claims. Uncertainty: INSUFFICIENT DATA for robust information edge.

## Operational inventory

| Station | Instrument | Valid | Excluded | Update s | Receipt age s | Max gap s | Range °C |
|---|---|---:|---:|---:|---:|---:|---|
| Cybernetyki 7 (opensensemap:61c1f4ff80a739001cda08bb) | BMP180 | 252 | 1 | 327.148 | 51.9730095 | 1008.957 | 9.8–14.6 |
| Czerniakowska (opensensemap:5c6e9151154515001982e4da) | DHT11 | 246 | 1 | 342.729 | 81.6473155 | 1051.861 | 9.5–16.7 |
| SaveDnipro (opensensemap:6941429cfdfe0700083492f4) | BME280 | 253 | 0 | 333.48249999999996 | 113.428922 | 665.501 | 8.23–14.92 |
| Przekorna (opensensemap:5d6145ec953683001a6b7fdb) | BME280 | 280 | 0 | 298.007 | 61.5426545 | 607.486 | 9.31–16.33 |

## Walk-forward results against matched persistence

H1 raw; H2 rolling48h minimum12 past interval-residual median correction; H3 previous METAR plus same-instrument change from previous cycle anchor. No outcome-based station selection. Training outcome receipt must precede decision. T−60 and T+60 experiments remain separate.

| Phase / station / model | N | Exact | Matched persistence | METAR trend exact/N | Difference pp | Changed exact / Nchanges | False alarms | Interval error °C |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| POST_OBSERVATION_PRE_RECEIPT|ENSEMBLE|pws_equal_ensemble | 37 | 0.000 | 0.811 | 0.6486486486486487/37 | -81.08 | 0/7 | 30 | 1.099 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5c6e9151154515001982e4da|pws_calibrated | 15 | 0.467 | 0.933 | 0.8666666666666667/15 | -46.67 | 1/1 | 8 | 0.257 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5c6e9151154515001982e4da|pws_change | 20 | 0.750 | 0.750 | 0.65/20 | 0.00 | 1/5 | 1 | 0.035 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5c6e9151154515001982e4da|pws_raw | 27 | 0.000 | 0.778 | 0.6666666666666666/27 | -77.78 | 0/6 | 21 | 1.407 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5d6145ec953683001a6b7fdb|pws_calibrated | 26 | 0.154 | 0.885 | 0.6923076923076923/26 | -73.08 | 0/3 | 19 | 0.463 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5d6145ec953683001a6b7fdb|pws_change | 28 | 0.643 | 0.821 | 0.6428571428571429/28 | -17.86 | 0/5 | 5 | 0.123 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5d6145ec953683001a6b7fdb|pws_raw | 38 | 0.000 | 0.816 | 0.6578947368421053/38 | -81.58 | 0/7 | 31 | 1.342 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:61c1f4ff80a739001cda08bb|pws_calibrated | 14 | 0.714 | 0.857 | 0.7857142857142857/14 | -14.29 | 0/2 | 2 | 0.046 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:61c1f4ff80a739001cda08bb|pws_change | 21 | 0.810 | 0.810 | 0.6666666666666666/21 | 0.00 | 0/4 | 0 | 0.067 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:61c1f4ff80a739001cda08bb|pws_raw | 26 | 0.038 | 0.808 | 0.6923076923076923/26 | -76.92 | 0/5 | 20 | 1.238 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:6941429cfdfe0700083492f4|pws_calibrated | 14 | 0.357 | 0.857 | 0.7857142857142857/14 | -50.00 | 1/2 | 8 | 0.225 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:6941429cfdfe0700083492f4|pws_change | 17 | 0.706 | 0.824 | 0.7058823529411765/17 | -11.76 | 0/3 | 2 | 0.066 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:6941429cfdfe0700083492f4|pws_raw | 26 | 0.308 | 0.731 | 0.6538461538461539/26 | -42.31 | 1/7 | 12 | 0.263 |
| PRE_OBSERVATION|ENSEMBLE|pws_equal_ensemble | 36 | 0.000 | 0.806 | 0.6666666666666666/36 | -80.56 | 0/7 | 29 | 1.118 |
| PRE_OBSERVATION|opensensemap:5c6e9151154515001982e4da|pws_calibrated | 18 | 0.333 | 0.944 | 0.8333333333333334/18 | -61.11 | 0/1 | 11 | 0.411 |
| PRE_OBSERVATION|opensensemap:5c6e9151154515001982e4da|pws_change | 14 | 0.786 | 0.857 | 0.7142857142857143/14 | -7.14 | 2/2 | 3 | 0.014 |
| PRE_OBSERVATION|opensensemap:5c6e9151154515001982e4da|pws_raw | 30 | 0.000 | 0.867 | 0.7/30 | -86.67 | 0/4 | 26 | 1.523 |
| PRE_OBSERVATION|opensensemap:5d6145ec953683001a6b7fdb|pws_calibrated | 13 | 0.077 | 0.846 | 0.6923076923076923/13 | -76.92 | 1/2 | 11 | 0.475 |
| PRE_OBSERVATION|opensensemap:5d6145ec953683001a6b7fdb|pws_change | 18 | 0.722 | 0.833 | 0.7222222222222222/18 | -11.11 | 1/3 | 3 | 0.064 |
| PRE_OBSERVATION|opensensemap:5d6145ec953683001a6b7fdb|pws_raw | 25 | 0.000 | 0.800 | 0.68/25 | -80.00 | 0/5 | 20 | 1.405 |
| PRE_OBSERVATION|opensensemap:61c1f4ff80a739001cda08bb|pws_calibrated | 17 | 0.765 | 0.941 | 0.8823529411764706/17 | -17.65 | 0/1 | 3 | 0.051 |
| PRE_OBSERVATION|opensensemap:61c1f4ff80a739001cda08bb|pws_change | 20 | 0.900 | 0.850 | 0.8/20 | 5.00 | 1/3 | 0 | 0.035 |
| PRE_OBSERVATION|opensensemap:61c1f4ff80a739001cda08bb|pws_raw | 29 | 0.000 | 0.793 | 0.6896551724137931/29 | -79.31 | 0/6 | 23 | 1.306 |
| PRE_OBSERVATION|opensensemap:6941429cfdfe0700083492f4|pws_calibrated | 13 | 0.385 | 0.923 | 0.7692307692307693/13 | -53.85 | 1/1 | 8 | 0.130 |
| PRE_OBSERVATION|opensensemap:6941429cfdfe0700083492f4|pws_change | 13 | 0.692 | 0.692 | 0.46153846153846156/13 | 0.00 | 0/4 | 0 | 0.095 |
| PRE_OBSERVATION|opensensemap:6941429cfdfe0700083492f4|pws_raw | 25 | 0.280 | 0.760 | 0.56/25 | -48.00 | 2/6 | 14 | 0.217 |

## Operational ranking (no predictive score)

Ordering fixed in protocol: valid receipt fraction, fresh checkpoint coverage, median age, largest gap. Coverage denominator: selected T−60 windows with an uncensored target and available baseline, not HTTP poll count. A valid historical receipt may be stale now.

| Rank | Station | Valid fraction | Eligible/selected checkpoints | Median age s |
|---|---|---:|---:|---:|
| 1 | opensensemap:5d6145ec953683001a6b7fdb | 1.0000 | 25/43 | 61.54 |
| 2 | opensensemap:6941429cfdfe0700083492f4 | 1.0000 | 25/43 | 113.43 |
| 3 | opensensemap:61c1f4ff80a739001cda08bb | 0.9960 | 29/43 | 51.97 |
| 4 | opensensemap:5c6e9151154515001982e4da | 0.9960 | 30/43 | 81.65 |

## Predictive ranking on identical targets

Separate fixed-model comparisons. Descriptive ordering below is NOT approved future station selection. All-station intersections with <30 cycles are INSUFFICIENT DATA for ranking. Candidate results outside these intersections above must not be compared directly across stations.

| Phase/model | Common N | Station | Exact | Same-target persistence | Status |
|---|---:|---|---:|---:|---|
| PRE_OBSERVATION|pws_raw | 9 | opensensemap:6941429cfdfe0700083492f4 | 0.222 | 0.778 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_raw | 9 | opensensemap:5d6145ec953683001a6b7fdb | 0.000 | 0.778 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_raw | 9 | opensensemap:61c1f4ff80a739001cda08bb | 0.000 | 0.778 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_raw | 9 | opensensemap:5c6e9151154515001982e4da | 0.000 | 0.778 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_calibrated | 5 | opensensemap:61c1f4ff80a739001cda08bb | 0.600 | 1.000 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_calibrated | 5 | opensensemap:6941429cfdfe0700083492f4 | 0.400 | 1.000 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_calibrated | 5 | opensensemap:5d6145ec953683001a6b7fdb | 0.000 | 1.000 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_calibrated | 5 | opensensemap:5c6e9151154515001982e4da | 0.000 | 1.000 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_change | 1 | opensensemap:5d6145ec953683001a6b7fdb | 1.000 | 1.000 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_change | 1 | opensensemap:61c1f4ff80a739001cda08bb | 1.000 | 1.000 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_change | 1 | opensensemap:6941429cfdfe0700083492f4 | 1.000 | 1.000 | INSUFFICIENT DATA |
| PRE_OBSERVATION|pws_change | 1 | opensensemap:5c6e9151154515001982e4da | 0.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_raw | 9 | opensensemap:6941429cfdfe0700083492f4 | 0.333 | 0.667 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_raw | 9 | opensensemap:61c1f4ff80a739001cda08bb | 0.111 | 0.667 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_raw | 9 | opensensemap:5d6145ec953683001a6b7fdb | 0.000 | 0.667 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_raw | 9 | opensensemap:5c6e9151154515001982e4da | 0.000 | 0.667 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_calibrated | 2 | opensensemap:61c1f4ff80a739001cda08bb | 1.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_calibrated | 2 | opensensemap:6941429cfdfe0700083492f4 | 0.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_calibrated | 2 | opensensemap:5d6145ec953683001a6b7fdb | 0.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_calibrated | 2 | opensensemap:5c6e9151154515001982e4da | 0.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_change | 3 | opensensemap:5c6e9151154515001982e4da | 1.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_change | 3 | opensensemap:5d6145ec953683001a6b7fdb | 1.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_change | 3 | opensensemap:61c1f4ff80a739001cda08bb | 1.000 | 1.000 | INSUFFICIENT DATA |
| POST_OBSERVATION_PRE_RECEIPT|pws_change | 3 | opensensemap:6941429cfdfe0700083492f4 | 1.000 | 1.000 | INSUFFICIENT DATA |

## Absolute vs calibration vs change on matched within-station cycles

| Station | N | Raw exact | Calibrated exact | Change exact | Persistence |
|---|---:|---:|---:|---:|---:|
| opensensemap:61c1f4ff80a739001cda08bb | 12 | 0 | 0.8333333333333334 | 1 | 1 |
| opensensemap:5c6e9151154515001982e4da | 9 | 0 | 0.3333333333333333 | 0.7777777777777778 | 1 |
| opensensemap:6941429cfdfe0700083492f4 | 7 | 0.14285714285714285 | 0.2857142857142857 | 0.8571428571428571 | 0.8571428571428571 |
| opensensemap:5d6145ec953683001a6b7fdb | 11 | 0 | 0.09090909090909091 | 0.8181818181818182 | 0.9090909090909091 |

## Meteorological agreement (not forecasting)

Every eligible source measurement is paired with its nearest initial routine METAR within±5min. Multiple sensor readings for one target are not independent outcomes. Signed interval residual >0 means warmer than the METAR rounding interval.

| Station | Readings / distinct cycles | Mean signed interval residual °C | Mean absolute interval distance °C |
|---|---:|---:|---:|
| Cybernetyki 7 | 81/47 | 1.2454320987654321 | 1.2454320987654321 |
| Czerniakowska | 83/48 | 1.5228915662650602 | 1.5228915662650602 |
| SaveDnipro | 82/47 | 0.21804878048780493 | 0.21804878048780493 |
| Przekorna | 94/48 | 1.3384042553191489 | 1.3384042553191489 |

For a FAIR between-station agreement comparison, choose one nearest measurement per station/cycle and intersect cycles: common N=46. The broader reading-level rows above have unequal coverage and must not be directly ranked.

| Station | Matched mean signed interval residual °C | Matched absolute interval distance °C |
|---|---:|---:|
| opensensemap:61c1f4ff80a739001cda08bb | 1.2334782608695654 | 1.2334782608695654 |
| opensensemap:5c6e9151154515001982e4da | 1.5130434782608695 | 1.5130434782608695 |
| opensensemap:6941429cfdfe0700083492f4 | 0.21521739130434783 | 0.21521739130434783 |
| opensensemap:5d6145ec953683001a6b7fdb | 1.3202173913043478 | 1.3202173913043478 |

## Actual immutable prospective forecasts

Valid forecasts: 2345; distinct target cycles: 90; excluded/unsettled rows: 324. Each checkpoint/model group below has one row per cycle; do not sum groups as independent events.

| Checkpoint/model | N | Exact | Same-target persistence |
|---|---:|---:|---:|
| T-120s|inverse_distance | 67 | 0.254 | 0.687 |
| T-120s|median | 68 | 0.191 | 0.676 |
| T-120s|nearest | 68 | 0.250 | 0.676 |
| T-120s|previous_metar | 90 | 0.633 | 0.633 |
| T-120s|simple_recent_metar_trend | 89 | 0.551 | 0.629 |
| T-120s|temperature_persistence | 90 | 0.633 | 0.633 |
| T-180s|inverse_distance | 63 | 0.238 | 0.667 |
| T-180s|median | 63 | 0.206 | 0.667 |
| T-180s|nearest | 65 | 0.231 | 0.662 |
| T-180s|previous_metar | 89 | 0.640 | 0.640 |
| T-180s|simple_recent_metar_trend | 88 | 0.557 | 0.636 |
| T-180s|temperature_persistence | 89 | 0.640 | 0.640 |
| T-300s|inverse_distance | 68 | 0.265 | 0.647 |
| T-300s|median | 68 | 0.235 | 0.647 |
| T-300s|nearest | 68 | 0.235 | 0.647 |
| T-300s|previous_metar | 89 | 0.640 | 0.640 |
| T-300s|simple_recent_metar_trend | 88 | 0.557 | 0.636 |
| T-300s|temperature_persistence | 89 | 0.640 | 0.640 |
| T-600s|inverse_distance | 69 | 0.246 | 0.623 |
| T-600s|median | 69 | 0.188 | 0.623 |
| T-600s|nearest | 69 | 0.217 | 0.623 |
| T-600s|previous_metar | 88 | 0.625 | 0.625 |
| T-600s|simple_recent_metar_trend | 87 | 0.552 | 0.621 |
| T-600s|temperature_persistence | 88 | 0.625 | 0.625 |
| T-60s|inverse_distance | 69 | 0.203 | 0.667 |
| T-60s|median | 69 | 0.145 | 0.667 |
| T-60s|nearest | 69 | 0.188 | 0.667 |
| T-60s|previous_metar | 90 | 0.633 | 0.633 |
| T-60s|simple_recent_metar_trend | 89 | 0.551 | 0.629 |
| T-60s|temperature_persistence | 90 | 0.633 | 0.633 |

### Requested four-station cohort: recorded matched baselines

Cohort starts 2026-10-25T12:36:22.192969+00:00; 1255 eligible forecasts over 43 distinct cycles. Earlier all-history groups include the previous cohort and must not be attributed to these four sensors. Recorded production model definitions differ from the new research change model.

| Checkpoint/model | Matched N | Candidate exact | Recorded previous-METAR exact |
|---|---:|---:|---:|
| T-120s|inverse_distance | 40 | 0.15 | 0.85 |
| T-120s|median | 40 | 0.05 | 0.85 |
| T-120s|nearest | 40 | 0.15 | 0.85 |
| T-120s|previous_metar | 43 | 0.813953488372093 | 0.813953488372093 |
| T-120s|simple_recent_metar_trend | 43 | 0.6744186046511628 | 0.813953488372093 |
| T-120s|temperature_persistence | 43 | 0.813953488372093 | 0.813953488372093 |
| T-180s|inverse_distance | 40 | 0.125 | 0.825 |
| T-180s|median | 40 | 0.075 | 0.825 |
| T-180s|nearest | 41 | 0.12195121951219512 | 0.8292682926829268 |
| T-180s|previous_metar | 42 | 0.8333333333333334 | 0.8333333333333334 |
| T-180s|simple_recent_metar_trend | 42 | 0.6904761904761905 | 0.8333333333333334 |
| T-180s|temperature_persistence | 42 | 0.8333333333333334 | 0.8333333333333334 |
| T-300s|inverse_distance | 42 | 0.16666666666666666 | 0.8333333333333334 |
| T-300s|median | 42 | 0.11904761904761904 | 0.8333333333333334 |
| T-300s|nearest | 42 | 0.11904761904761904 | 0.8333333333333334 |
| T-300s|previous_metar | 42 | 0.8333333333333334 | 0.8333333333333334 |
| T-300s|simple_recent_metar_trend | 42 | 0.6904761904761905 | 0.8333333333333334 |
| T-300s|temperature_persistence | 42 | 0.8333333333333334 | 0.8333333333333334 |
| T-600s|inverse_distance | 42 | 0.14285714285714285 | 0.8095238095238095 |
| T-600s|median | 42 | 0.047619047619047616 | 0.8095238095238095 |
| T-600s|nearest | 42 | 0.09523809523809523 | 0.8095238095238095 |
| T-600s|previous_metar | 42 | 0.8095238095238095 | 0.8095238095238095 |
| T-600s|simple_recent_metar_trend | 42 | 0.6666666666666666 | 0.8095238095238095 |
| T-600s|temperature_persistence | 42 | 0.8095238095238095 | 0.8095238095238095 |
| T-60s|inverse_distance | 42 | 0.14285714285714285 | 0.8333333333333334 |
| T-60s|median | 42 | 0.047619047619047616 | 0.8333333333333334 |
| T-60s|nearest | 42 | 0.11904761904761904 | 0.8333333333333334 |
| T-60s|previous_metar | 43 | 0.813953488372093 | 0.813953488372093 |
| T-60s|simple_recent_metar_trend | 43 | 0.6744186046511628 | 0.813953488372093 |
| T-60s|temperature_persistence | 43 | 0.813953488372093 | 0.813953488372093 |

## Transition counts (one target per station/method/phase)

| Phase/station/model | Up/down/unchanged targets | Correct changed integer | False-alarm cycles |
|---|---:|---:|---:|
| POST_OBSERVATION_PRE_RECEIPT|ENSEMBLE|pws_equal_ensemble | 2/5/30 | 0 | 30 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5c6e9151154515001982e4da|pws_calibrated | 1/0/14 | 1 | 8 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5c6e9151154515001982e4da|pws_change | 1/4/15 | 1 | 1 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5c6e9151154515001982e4da|pws_raw | 1/5/21 | 0 | 21 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5d6145ec953683001a6b7fdb|pws_calibrated | 1/2/23 | 0 | 19 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5d6145ec953683001a6b7fdb|pws_change | 0/5/23 | 0 | 5 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:5d6145ec953683001a6b7fdb|pws_raw | 1/6/31 | 0 | 31 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:61c1f4ff80a739001cda08bb|pws_calibrated | 2/0/12 | 0 | 2 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:61c1f4ff80a739001cda08bb|pws_change | 1/3/17 | 0 | 0 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:61c1f4ff80a739001cda08bb|pws_raw | 2/3/21 | 0 | 20 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:6941429cfdfe0700083492f4|pws_calibrated | 2/0/12 | 1 | 8 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:6941429cfdfe0700083492f4|pws_change | 1/2/14 | 0 | 2 |
| POST_OBSERVATION_PRE_RECEIPT|opensensemap:6941429cfdfe0700083492f4|pws_raw | 2/5/19 | 1 | 12 |
| PRE_OBSERVATION|ENSEMBLE|pws_equal_ensemble | 2/5/29 | 0 | 29 |
| PRE_OBSERVATION|opensensemap:5c6e9151154515001982e4da|pws_calibrated | 1/0/17 | 0 | 11 |
| PRE_OBSERVATION|opensensemap:5c6e9151154515001982e4da|pws_change | 0/2/12 | 2 | 3 |
| PRE_OBSERVATION|opensensemap:5c6e9151154515001982e4da|pws_raw | 1/3/26 | 0 | 26 |
| PRE_OBSERVATION|opensensemap:5d6145ec953683001a6b7fdb|pws_calibrated | 2/0/11 | 1 | 11 |
| PRE_OBSERVATION|opensensemap:5d6145ec953683001a6b7fdb|pws_change | 1/2/15 | 1 | 3 |
| PRE_OBSERVATION|opensensemap:5d6145ec953683001a6b7fdb|pws_raw | 2/3/20 | 0 | 20 |
| PRE_OBSERVATION|opensensemap:61c1f4ff80a739001cda08bb|pws_calibrated | 1/0/16 | 0 | 3 |
| PRE_OBSERVATION|opensensemap:61c1f4ff80a739001cda08bb|pws_change | 0/3/17 | 1 | 0 |
| PRE_OBSERVATION|opensensemap:61c1f4ff80a739001cda08bb|pws_raw | 1/5/23 | 0 | 23 |
| PRE_OBSERVATION|opensensemap:6941429cfdfe0700083492f4|pws_calibrated | 1/0/12 | 1 | 8 |
| PRE_OBSERVATION|opensensemap:6941429cfdfe0700083492f4|pws_change | 1/3/9 | 0 | 0 |
| PRE_OBSERVATION|opensensemap:6941429cfdfe0700083492f4|pws_raw | 1/5/19 | 2 | 14 |

Transition CSV preserves latest input IDs, measurement/receipt/decision clocks, PWS delta, exact outcome and genuine immutable forecast IDs. Correct replay change signals are exploratory, not prospective successes; no future measurements enter replay. Same-target persistence never predicts a change. Checkpoint-diagnostics findings and full station metadata/QC histories: epwa_checkpoint_diagnostics.md/json.

## Hardware, precision and mounting

See docs/research/EPWA_HARDWARE.md for verified manufacturer documents and uncertainty. All four instruments publish two decimal places; observed minimum distinct steps are empirical, not hardware resolution. Declared BMP180 produces observed 0.02°C differences although the documented reference conversion uses0.1°C: firmware averaging or declaration mismatch remain hypotheses. No installed hardware is authenticated. Current QC remains UNVERIFIED; historical aggregate MISSING_INTERVALS flags do not invalidate every otherwise fresh receipt.

## Limitations

Short observational period, no random split, no robust confidence claim. METAR integer is a rounding interval; residual correction is a quantized-reference estimate, not precise airport calibration. Provider identities do not establish physical independence; one thermometer per provider station is represented. Metadata declarations do not verify actual mounting or shielding. Historical startup/coverage-censored inputs are excluded from replay. Current calibration/model comparisons are research replays only; actual immutable forecasts are evaluated separately. Clock synchronization uncertainty limits lead interpretation.

## Reproduce

```powershell
uv run python -m scripts.research.epwa_comparison --snapshot data/research/m17/snapshot.sqlite3
```

Snapshot and raw payloads are intentionally ignored; CSV contains actual normalized measurements. Export includes first receipts and raw reported precision; no interpolation or forward fill. Chart lines stop at gaps>15min.

## Practical findings

Absolute meteorological agreement and incremental prediction are different questions. SaveDnipro has the smallest mean absolute interval distance on 46 common meteorological cycles in this snapshot; that does not establish a forecasting advantage.

| Station change model, T−60 | Exact | Same-target persistence | Correct changed integer / actual changes | False alarms on unchanged cycles |
|---|---:|---:|---:|---:|
| Cybernetyki 7 | 18/20 | 17/20 | 1/3 | 0/17 |
| Czerniakowska | 11/14 | 12/14 | 2/2 | 3/12 |
| SaveDnipro | 9/13 | 9/13 | 0/4 | 0/9 |
| Przekorna | 13/18 | 15/18 | 1/3 | 3/15 |

These rows each compare with persistence on identical targets, but DIFFERENT STATIONS have different target sets. Do not rank these raw percentages across stations. The all-four trend intersection is reported above; insufficient overlap prevents a defensible predictive trend ranking. Any apparent single-station improvement remains a hypothesis, not a validated edge.

### Correct retrospective change signals

| Local target | Station | METAR previous→actual | PWS delta °C | Latest measurement UTC | First received UTC | Replay decision UTC | METAR received UTC |
|---|---|---|---:|---|---|---|---|
| 2026-10-25T16:00:00+01:00 | Czerniakowska | 13→12 | -0.600 | 2026-10-25T14:57:17.721000+00:00 | 2026-10-25T14:58:15.977547+00:00 | 2026-10-25T14:59:00+00:00 | 2026-10-25T15:02:10.989722+00:00 |
| 2026-10-25T21:30:00+01:00 | Czerniakowska | 10→9 | -0.600 | 2026-10-25T20:25:48.806000+00:00 | 2026-10-25T20:26:49.060643+00:00 | 2026-10-25T20:29:00+00:00 | 2026-10-25T20:32:30.133145+00:00 |
| 2026-10-25T21:30:00+01:00 | Cybernetyki 7 | 10→9 | -0.600 | 2026-10-25T20:24:36.491000+00:00 | 2026-10-25T20:26:02.536376+00:00 | 2026-10-25T20:29:00+00:00 | 2026-10-25T20:32:30.133145+00:00 |
| 2026-10-26T09:00:00+01:00 | Przekorna | 8→9 | 0.540 | 2026-10-26T07:55:54.979000+00:00 | 2026-10-26T07:56:19.038567+00:00 | 2026-10-26T07:59:00+00:00 | 2026-10-26T08:02:58.550390+00:00 |

These are reconstructed signals using inputs available at the fixed decision. The new pws_change rule was NOT running as an immutable live model. Actual earlier forecasts are linked in the transition CSV, with separate IDs available by decision versus by first receipt. A genuine prospective claim cannot be created retrospectively.

### Actual production outcomes, current cohort, T−60

| Model | Candidate exact | Recorded persistence on SAME targets |
|---|---:|---:|
| inverse_distance | 6/42 | 35/42 |
| median | 2/42 | 35/42 |
| nearest | 5/42 | 35/42 |
| previous_metar | 35/43 | 35/43 |
| simple_recent_metar_trend | 29/43 | 35/43 |
| temperature_persistence | 35/43 | 35/43 |

The original production PWS methods do not outperform recorded persistence in this cohort. At T−60 calibration improves several raw models but does not beat persistence on their matched windows. The equal raw ensemble also fails to improve on its matched baseline. Retain all four for research; no production cohort or scoring rules were changed. Further prospective, multi-day validation is required before adopting any change rule.

### Unavailable checkpoints

The prior ten UNAVAILABLE rows reconstruct to six quality_weighted cases with fresh observations but NULL quality scores, and four EGLL T−180 methods with no selected input≤300s old. EDDM:3; EGLL:6; EHAM:1; EPWA:0. Scores are deliberately UNVERIFIED; no scheduler defect demonstrated. The stored generic reason discarded original exceptions/transient gate state; attribution is a durable-state reconstruction, not recovered original exceptions. Full details in epwa_checkpoint_diagnostics.md.

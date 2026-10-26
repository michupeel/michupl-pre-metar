# EXP-0010 — Early METAR temperature reconstruction

Frozen database cutoff: 2026-10-26T19:06:15.753046+00:00; SHA256 666b06cad15c99b9fe8442dca27b67a180187dfbf9b03c398790860a158fb99f. Baseline a473f6c.

**Exploratory retrospective reconstructions are NOT actual immutable live forecasts.** A positive lead is relative to our earliest configured-provider receipt, not global publication or a trading advantage. Clock synchronization remains unverified. No collector, selection, QC, calibration or prediction writes/restarts.

Protocol: docs/research/EXP0010_PROTOCOL.md. CAL-0 raw; CAL-1 all-prior median midpoint offset; CAL-2 trailing12h median midpoint offset, >=12 earlier received distinct nominal cycles. Offset±0.5°C is a quantization identification interval, not a confidence interval. Initial-version outcomes, all-version first-receipt closure; SPECI/COR-only/ambiguous targets excluded from primary scoring. No affine or tuned model search.

## Search scope

| Airport | Targets | Audited sensors | Valid timestamp sensors | >=12 pair cycles |
|---|---:|---:|---:|---:|
| EDDM | 106 | 24 | 10 | 5 |
| EHAM | 107 | 21 | 3 | 3 |
| EPWA | 104 | 64 | 30 | 8 |
| EGLL | 106 | 11 | 3 | 3 |

Methods3; fixed checkpoints (-600, -300, -180, -120, -60, 30, 60, 90); latest actual receipt separately for EXP-A and EXP-B; every actual receipt plus parameter/expiry boundaries from T−10min to first receipt. Summary groups=3600; valid fixed/latest candidates=11859; these are repeated evaluations, NOT independent weather events. All sensors/methods/statuses appear in CSV, including no eligible input and insufficient history. Historic station selection annotates but never filters offline candidates.

## Fixed T−60 and latest-receipt calibrated results

| Airport / sensor | Method | Decision | Window | N | Correct | Raw SAME cycles | Persistence | Gain | Harm | Net | Correct changed | False changes | Median lead all/correct s |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| EDDM / opensensemap:5bce161fbb15b700196e256d:5bce161fbb15b700196e256f | CAL-1 | LATEST_RECEIPT | EXP_A | 41 | 19 | 20 | 24 | 5 | 10 | -5 | 5 | 10 | 409.36/464.371078 |
| EDDM / opensensemap:5bce161fbb15b700196e256d:5bce161fbb15b700196e256f | CAL-1 | LATEST_RECEIPT | EXP_B | 29 | 15 | 14 | 16 | 5 | 6 | -1 | 5 | 6 | 125.16/136.041828 |
| EDDM / opensensemap:5bce161fbb15b700196e256d:5bce161fbb15b700196e256f | CAL-1 | T-60s | EXP_A | 20 | 10 | 11 | 16 | 1 | 7 | -6 | 1 | 7 | 313.67/312.3930555 |
| EDDM / opensensemap:5bce161fbb15b700196e256d:5bce161fbb15b700196e256f | CAL-2 | LATEST_RECEIPT | EXP_A | 31 | 16 | 16 | 17 | 5 | 6 | -1 | 5 | 6 | 435.90/465.98184200000003 |
| EDDM / opensensemap:5bce161fbb15b700196e256d:5bce161fbb15b700196e256f | CAL-2 | LATEST_RECEIPT | EXP_B | 19 | 11 | 12 | 10 | 3 | 2 | 1 | 3 | 2 | 144.98/136.041828 |
| EDDM / opensensemap:5bce161fbb15b700196e256d:5bce161fbb15b700196e256f | CAL-2 | T-60s | EXP_A | 12 | 7 | 7 | 10 | 1 | 4 | -3 | 1 | 4 | 315.11/309.076846 |
| EDDM / opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7 | CAL-1 | LATEST_RECEIPT | EXP_A | 42 | 24 | 24 | 24 | 7 | 7 | 0 | 7 | 7 | 417.94/429.89187200000003 |
| EDDM / opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7 | CAL-1 | LATEST_RECEIPT | EXP_B | 33 | 17 | 20 | 18 | 5 | 6 | -1 | 5 | 6 | 165.52/153.262817 |
| EDDM / opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7 | CAL-1 | T-60s | EXP_A | 38 | 21 | 21 | 21 | 7 | 7 | 0 | 7 | 7 | 312.46/310.842855 |
| EDDM / opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7 | CAL-2 | LATEST_RECEIPT | EXP_A | 42 | 25 | 24 | 24 | 8 | 7 | 1 | 8 | 7 | 417.94/424.722924 |
| EDDM / opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7 | CAL-2 | LATEST_RECEIPT | EXP_B | 33 | 19 | 20 | 18 | 6 | 5 | 1 | 6 | 5 | 165.52/165.594094 |
| EDDM / opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7 | CAL-2 | T-60s | EXP_A | 38 | 22 | 21 | 21 | 8 | 7 | 1 | 8 | 7 | 312.46/306.971865 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c755e5d7dea1400190366ea | CAL-1 | LATEST_RECEIPT | EXP_A | 83 | 37 | 7 | 51 | 13 | 27 | -14 | 13 | 27 | 390.22/332.462327 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c755e5d7dea1400190366ea | CAL-1 | LATEST_RECEIPT | EXP_B | 63 | 23 | 4 | 38 | 8 | 23 | -15 | 8 | 23 | 118.28/89.590223 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c755e5d7dea1400190366ea | CAL-1 | T-60s | EXP_A | 58 | 23 | 3 | 37 | 7 | 21 | -14 | 7 | 21 | 304.06/310.026962 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c755e5d7dea1400190366ea | CAL-2 | LATEST_RECEIPT | EXP_A | 77 | 30 | 6 | 47 | 10 | 27 | -17 | 10 | 27 | 390.22/334.1014745 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c755e5d7dea1400190366ea | CAL-2 | LATEST_RECEIPT | EXP_B | 58 | 17 | 4 | 35 | 6 | 24 | -18 | 6 | 24 | 114.50/85.533284 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c755e5d7dea1400190366ea | CAL-2 | T-60s | EXP_A | 52 | 18 | 2 | 33 | 4 | 19 | -15 | 4 | 19 | 301.37/297.46664699999997 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c75620e7dea140019045cad | CAL-1 | LATEST_RECEIPT | EXP_A | 23 | 7 | 0 | 17 | 2 | 12 | -10 | 2 | 12 | 435.56/324.338972 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c75620e7dea140019045cad | CAL-1 | LATEST_RECEIPT | EXP_B | 21 | 7 | 0 | 16 | 3 | 12 | -9 | 3 | 12 | 128.81/89.590223 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c75620e7dea140019045cad | CAL-1 | T-60s | EXP_A | 18 | 5 | 0 | 15 | 1 | 11 | -10 | 1 | 11 | 294.80/293.641066 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c75620e7dea140019045cad | CAL-2 | LATEST_RECEIPT | EXP_A | 23 | 7 | 0 | 17 | 2 | 12 | -10 | 2 | 12 | 435.56/324.338972 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c75620e7dea140019045cad | CAL-2 | LATEST_RECEIPT | EXP_B | 21 | 8 | 0 | 16 | 4 | 12 | -8 | 4 | 12 | 128.81/74.600839 |
| EDDM / opensensemap:5c755e5d7dea1400190366e8:5c75620e7dea140019045cad | CAL-2 | T-60s | EXP_A | 18 | 5 | 0 | 15 | 1 | 11 | -10 | 1 | 11 | 294.80/293.641066 |
| EDDM / opensensemap:65c13f99e9153000077c4d83:65c13f99e9153000077c4d86 | CAL-1 | LATEST_RECEIPT | EXP_A | 44 | 21 | 20 | 25 | 8 | 12 | -4 | 8 | 12 | 403.75/402.8865 |
| EDDM / opensensemap:65c13f99e9153000077c4d83:65c13f99e9153000077c4d86 | CAL-1 | LATEST_RECEIPT | EXP_B | 35 | 15 | 16 | 20 | 5 | 10 | -5 | 5 | 10 | 138.54/143.238239 |
| EDDM / opensensemap:65c13f99e9153000077c4d83:65c13f99e9153000077c4d86 | CAL-1 | T-60s | EXP_A | 34 | 17 | 12 | 17 | 7 | 7 | 0 | 7 | 7 | 309.96/303.457236 |
| EDDM / opensensemap:65c13f99e9153000077c4d83:65c13f99e9153000077c4d86 | CAL-2 | LATEST_RECEIPT | EXP_A | 44 | 21 | 20 | 25 | 8 | 12 | -4 | 8 | 12 | 403.75/402.8865 |
| EDDM / opensensemap:65c13f99e9153000077c4d83:65c13f99e9153000077c4d86 | CAL-2 | LATEST_RECEIPT | EXP_B | 35 | 14 | 16 | 20 | 5 | 11 | -6 | 5 | 11 | 138.54/145.0546775 |
| EDDM / opensensemap:65c13f99e9153000077c4d83:65c13f99e9153000077c4d86 | CAL-2 | T-60s | EXP_A | 34 | 17 | 12 | 17 | 7 | 7 | 0 | 7 | 7 | 309.96/303.457236 |
| EGLL / opensensemap:5e61c1cc6cc61f001c6e4086:5e61c1cc6cc61f001c6e4089 | CAL-1 | LATEST_RECEIPT | EXP_A | 43 | 11 | 4 | 30 | 4 | 23 | -19 | 4 | 23 | 510.55/503.505572 |
| EGLL / opensensemap:5e61c1cc6cc61f001c6e4086:5e61c1cc6cc61f001c6e4089 | CAL-1 | LATEST_RECEIPT | EXP_B | 37 | 11 | 3 | 24 | 4 | 17 | -13 | 4 | 17 | 161.92/161.923102 |
| EGLL / opensensemap:5e61c1cc6cc61f001c6e4086:5e61c1cc6cc61f001c6e4089 | CAL-1 | T-60s | EXP_A | 26 | 6 | 2 | 16 | 2 | 12 | -10 | 2 | 12 | 362.67/363.566399 |
| EGLL / opensensemap:5e61c1cc6cc61f001c6e4086:5e61c1cc6cc61f001c6e4089 | CAL-2 | LATEST_RECEIPT | EXP_A | 43 | 18 | 4 | 30 | 4 | 16 | -12 | 4 | 16 | 510.55/507.0280695 |
| EGLL / opensensemap:5e61c1cc6cc61f001c6e4086:5e61c1cc6cc61f001c6e4089 | CAL-2 | LATEST_RECEIPT | EXP_B | 37 | 18 | 3 | 24 | 4 | 10 | -6 | 4 | 10 | 161.92/152.3083225 |
| EGLL / opensensemap:5e61c1cc6cc61f001c6e4086:5e61c1cc6cc61f001c6e4089 | CAL-2 | T-60s | EXP_A | 26 | 9 | 2 | 16 | 2 | 9 | -7 | 2 | 9 | 362.67/349.885789 |
| EGLL / opensensemap:623f6e24c4de74001c66f4cb:623f6e24c4de74001c66f4ce | CAL-1 | LATEST_RECEIPT | EXP_A | 45 | 18 | 22 | 30 | 3 | 15 | -12 | 3 | 15 | 470.16/493.86036249999995 |
| EGLL / opensensemap:623f6e24c4de74001c66f4cb:623f6e24c4de74001c66f4ce | CAL-1 | LATEST_RECEIPT | EXP_B | 40 | 15 | 16 | 26 | 3 | 14 | -11 | 3 | 14 | 120.03/156.976053 |
| EGLL / opensensemap:623f6e24c4de74001c66f4cb:623f6e24c4de74001c66f4ce | CAL-1 | T-60s | EXP_A | 21 | 8 | 11 | 14 | 1 | 7 | -6 | 1 | 7 | 352.11/355.23193200000003 |
| EGLL / opensensemap:623f6e24c4de74001c66f4cb:623f6e24c4de74001c66f4ce | CAL-2 | LATEST_RECEIPT | EXP_A | 25 | 8 | 10 | 15 | 1 | 8 | -7 | 1 | 8 | 438.67/429.3217225 |
| EGLL / opensensemap:623f6e24c4de74001c66f4cb:623f6e24c4de74001c66f4ce | CAL-2 | LATEST_RECEIPT | EXP_B | 23 | 11 | 7 | 15 | 3 | 7 | -4 | 3 | 7 | 126.76/131.528928 |
| EGLL / opensensemap:623f6e24c4de74001c66f4cb:623f6e24c4de74001c66f4ce | CAL-2 | T-60s | EXP_A | 11 | 5 | 4 | 7 | 1 | 3 | -2 | 1 | 3 | 353.17/357.292312 |
| EGLL / opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243 | CAL-1 | LATEST_RECEIPT | EXP_A | 43 | 24 | 16 | 30 | 7 | 13 | -6 | 7 | 13 | 442.51/437.752548 |
| EGLL / opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243 | CAL-1 | LATEST_RECEIPT | EXP_B | 38 | 20 | 14 | 26 | 7 | 13 | -6 | 7 | 13 | 134.40/127.45094549999999 |
| EGLL / opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243 | CAL-1 | T-60s | EXP_A | 27 | 14 | 11 | 19 | 3 | 8 | -5 | 3 | 8 | 362.89/356.38874450000003 |
| EGLL / opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243 | CAL-2 | LATEST_RECEIPT | EXP_A | 42 | 26 | 16 | 30 | 7 | 11 | -4 | 7 | 11 | 448.02/440.450135 |
| EGLL / opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243 | CAL-2 | LATEST_RECEIPT | EXP_B | 35 | 22 | 12 | 24 | 6 | 8 | -2 | 6 | 8 | 137.24/127.45094549999999 |
| EGLL / opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243 | CAL-2 | T-60s | EXP_A | 26 | 17 | 11 | 19 | 3 | 5 | -2 | 3 | 5 | 364.24/362.8917 |
| EHAM / opensensemap:5fa3fc2867d8a1001b5f9d6d:5fa3fc2867d8a1001b5f9d70 | CAL-1 | LATEST_RECEIPT | EXP_A | 27 | 11 | 7 | 19 | 4 | 12 | -8 | 4 | 12 | 187.66/199.060599 |
| EHAM / opensensemap:5fa3fc2867d8a1001b5f9d6d:5fa3fc2867d8a1001b5f9d70 | CAL-1 | T-60s | EXP_A | 1 | 0 | 0 | 1 | 0 | 1 | -1 | 0 | 1 | 19.50/None |
| EHAM / opensensemap:6137877084c610001cae82e1:6137877084c610001cae82e5 | CAL-1 | LATEST_RECEIPT | EXP_A | 19 | 4 | 0 | 13 | 2 | 11 | -9 | 2 | 11 | 157.35/131.2490905 |
| EHAM / opensensemap:6137877084c610001cae82e1:6137877084c610001cae82e5 | CAL-1 | T-60s | EXP_A | 1 | 0 | 0 | 1 | 0 | 1 | -1 | 0 | 1 | 19.50/None |
| EHAM / opensensemap:640b68626b84850007762702:640b68626b84850007762705 | CAL-1 | LATEST_RECEIPT | EXP_A | 20 | 7 | 10 | 14 | 0 | 7 | -7 | 0 | 7 | 193.00/190.230147 |
| EPWA / opensensemap:5bc03a20bc400c001b2451e2:5bc03a20bc400c001b2451e4 | CAL-1 | LATEST_RECEIPT | EXP_B | 11 | 9 | 0 | 9 | 1 | 1 | 0 | 1 | 1 | 66.58/81.568601 |
| EPWA / opensensemap:5bfd032e3e34fc001982867c:5bfd032e3e34fc001982867e | CAL-1 | LATEST_RECEIPT | EXP_B | 11 | 7 | 7 | 9 | 0 | 2 | -2 | 0 | 2 | 55.04/54.613947 |
| EPWA / opensensemap:5c6e9151154515001982e4da:5c6e9151154515001982e4dc | CAL-1 | LATEST_RECEIPT | EXP_A | 36 | 20 | 0 | 28 | 1 | 9 | -8 | 1 | 9 | 382.05/381.6751315 |
| EPWA / opensensemap:5c6e9151154515001982e4da:5c6e9151154515001982e4dc | CAL-1 | LATEST_RECEIPT | EXP_B | 23 | 12 | 0 | 18 | 0 | 6 | -6 | 0 | 6 | 95.24/122.89596800000001 |
| EPWA / opensensemap:5c6e9151154515001982e4da:5c6e9151154515001982e4dc | CAL-1 | T-60s | EXP_A | 21 | 12 | 0 | 16 | 1 | 5 | -4 | 1 | 5 | 238.66/236.4622105 |
| EPWA / opensensemap:5c6e9151154515001982e4da:5c6e9151154515001982e4dc | CAL-2 | LATEST_RECEIPT | EXP_A | 36 | 24 | 0 | 28 | 3 | 7 | -4 | 3 | 7 | 382.05/380.0292095 |
| EPWA / opensensemap:5c6e9151154515001982e4da:5c6e9151154515001982e4dc | CAL-2 | LATEST_RECEIPT | EXP_B | 23 | 14 | 0 | 18 | 1 | 5 | -4 | 1 | 5 | 95.24/106.67094850000001 |
| EPWA / opensensemap:5c6e9151154515001982e4da:5c6e9151154515001982e4dc | CAL-2 | T-60s | EXP_A | 21 | 13 | 0 | 16 | 2 | 5 | -3 | 2 | 5 | 238.66/237.487771 |
| EPWA / opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde | CAL-1 | LATEST_RECEIPT | EXP_A | 41 | 24 | 0 | 33 | 4 | 13 | -9 | 4 | 13 | 327.93/361.07183399999997 |
| EPWA / opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde | CAL-1 | LATEST_RECEIPT | EXP_B | 22 | 13 | 0 | 18 | 1 | 6 | -5 | 1 | 6 | 70.47/93.174956 |
| EPWA / opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde | CAL-1 | T-60s | EXP_A | 26 | 14 | 0 | 19 | 3 | 8 | -5 | 3 | 8 | 235.43/236.99352 |
| EPWA / opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde | CAL-2 | LATEST_RECEIPT | EXP_A | 41 | 29 | 0 | 33 | 6 | 10 | -4 | 6 | 10 | 327.93/342.934473 |
| EPWA / opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde | CAL-2 | LATEST_RECEIPT | EXP_B | 22 | 11 | 0 | 18 | 0 | 7 | -7 | 0 | 7 | 70.47/97.269424 |
| EPWA / opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde | CAL-2 | T-60s | EXP_A | 26 | 17 | 0 | 19 | 5 | 7 | -2 | 5 | 7 | 235.43/238.55039 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbe7aa68df4001a7aca4f | CAL-1 | LATEST_RECEIPT | EXP_A | 26 | 5 | 6 | 13 | 2 | 10 | -8 | 2 | 10 | 372.84/374.565711 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbe7aa68df4001a7aca4f | CAL-1 | LATEST_RECEIPT | EXP_B | 14 | 4 | 2 | 6 | 1 | 3 | -2 | 1 | 3 | 69.46/54.3471105 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbe7aa68df4001a7aca4f | CAL-1 | T-60s | EXP_A | 16 | 4 | 4 | 7 | 1 | 4 | -3 | 1 | 4 | 235.28/236.25840449999998 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbe7aa68df4001a7aca4f | CAL-2 | LATEST_RECEIPT | EXP_A | 18 | 4 | 4 | 8 | 1 | 5 | -4 | 1 | 5 | 351.94/355.40184250000004 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbe7aa68df4001a7aca4f | CAL-2 | LATEST_RECEIPT | EXP_B | 14 | 4 | 2 | 6 | 1 | 3 | -2 | 1 | 3 | 69.46/54.3471105 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbe7aa68df4001a7aca4f | CAL-2 | T-60s | EXP_A | 16 | 4 | 4 | 7 | 1 | 4 | -3 | 1 | 4 | 235.28/236.25840449999998 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbffca68df4001a7b3be9 | CAL-1 | LATEST_RECEIPT | EXP_A | 26 | 8 | 2 | 13 | 3 | 8 | -5 | 3 | 8 | 372.84/397.49480500000004 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbffca68df4001a7b3be9 | CAL-1 | LATEST_RECEIPT | EXP_B | 14 | 4 | 1 | 6 | 1 | 3 | -2 | 1 | 3 | 69.46/54.3471105 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbffca68df4001a7b3be9 | CAL-1 | T-60s | EXP_A | 16 | 5 | 1 | 7 | 2 | 4 | -2 | 2 | 4 | 235.28/228.6032 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbffca68df4001a7b3be9 | CAL-2 | LATEST_RECEIPT | EXP_A | 18 | 5 | 1 | 8 | 2 | 5 | -3 | 2 | 5 | 351.94/336.237974 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbffca68df4001a7b3be9 | CAL-2 | LATEST_RECEIPT | EXP_B | 14 | 4 | 1 | 6 | 1 | 3 | -2 | 1 | 3 | 69.46/54.3471105 |
| EPWA / opensensemap:5dbdbe79a68df4001a7aca4c:5dbdbffca68df4001a7b3be9 | CAL-2 | T-60s | EXP_A | 16 | 5 | 1 | 7 | 2 | 4 | -2 | 2 | 4 | 235.28/228.6032 |
| EPWA / opensensemap:61c1f4ff80a739001cda08bb:61c1f4ff80a739001cda08bd | CAL-1 | LATEST_RECEIPT | EXP_A | 40 | 20 | 0 | 32 | 0 | 12 | -12 | 0 | 12 | 356.46/375.92242999999996 |
| EPWA / opensensemap:61c1f4ff80a739001cda08bb:61c1f4ff80a739001cda08bd | CAL-1 | LATEST_RECEIPT | EXP_B | 22 | 12 | 0 | 20 | 0 | 8 | -8 | 0 | 8 | 90.15/98.798475 |
| EPWA / opensensemap:61c1f4ff80a739001cda08bb:61c1f4ff80a739001cda08bd | CAL-1 | T-60s | EXP_A | 28 | 14 | 0 | 23 | 0 | 9 | -9 | 0 | 9 | 236.46/233.732382 |
| EPWA / opensensemap:61c1f4ff80a739001cda08bb:61c1f4ff80a739001cda08bd | CAL-2 | LATEST_RECEIPT | EXP_A | 40 | 19 | 0 | 32 | 0 | 13 | -13 | 0 | 13 | 356.46/361.97673 |
| EPWA / opensensemap:61c1f4ff80a739001cda08bb:61c1f4ff80a739001cda08bd | CAL-2 | LATEST_RECEIPT | EXP_B | 22 | 12 | 0 | 20 | 0 | 8 | -8 | 0 | 8 | 90.15/98.798475 |
| EPWA / opensensemap:61c1f4ff80a739001cda08bb:61c1f4ff80a739001cda08bd | CAL-2 | T-60s | EXP_A | 28 | 13 | 0 | 23 | 0 | 10 | -10 | 0 | 10 | 236.46/237.487771 |
| EPWA / opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7 | CAL-1 | LATEST_RECEIPT | EXP_A | 35 | 25 | 9 | 27 | 4 | 6 | -2 | 4 | 6 | 324.76/324.763063 |
| EPWA / opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7 | CAL-1 | LATEST_RECEIPT | EXP_B | 17 | 13 | 3 | 13 | 3 | 3 | 0 | 3 | 3 | 80.11/59.775249 |
| EPWA / opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7 | CAL-1 | T-60s | EXP_A | 24 | 16 | 8 | 17 | 4 | 5 | -1 | 4 | 5 | 238.02/241.41777050000002 |
| EPWA / opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7 | CAL-2 | LATEST_RECEIPT | EXP_A | 24 | 16 | 7 | 16 | 5 | 5 | 0 | 5 | 5 | 299.75/296.837457 |
| EPWA / opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7 | CAL-2 | LATEST_RECEIPT | EXP_B | 5 | 2 | 1 | 3 | 2 | 3 | -1 | 2 | 3 | 134.63/107.072197 |
| EPWA / opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7 | CAL-2 | T-60s | EXP_A | 17 | 11 | 6 | 10 | 5 | 4 | 1 | 5 | 4 | 235.44/235.43665 |

## Actual examples — outcome-conditioned illustrations

Examples favor stable incremental cases, airport representation, then lead. This is hindsight example selection, NOT an unbiased success rate. Complete failures and search scope are retained.
Earlier-correct companion rows show the ACTUAL DIFFERENT inputs/offsets at the first correct state of the same cycle; do not count these as extra events. A first correct point at T−10 is left-censored by the search window, not proof the signal first began there.

### Example1: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EDDM; station opensensemap:5beb063756a15500193139f0; sensor opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7; distance 16.398km.
Previous METAR 7°C, nominal 2026-10-25T20:50:00+00:00, received 2026-10-25T20:53:49.796613+00:00.
PWS measured 2026-10-25T21:18:50.650000+00:00; first received 2026-10-25T21:18:52.483280+00:00; raw 7.3°C; age 1.833s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.4300°C, quantization bounds [-0.9300,0.0700]°C; 12 earlier cycles; latest calibration outcome received 2026-10-25T20:53:49.796613+00:00.
Calibrated 7.7300°C → integer 8; RAW integer 7 (raw correct=False); decision 2026-10-25T21:18:52.483280+00:00; target nominal 2026-10-25T21:20:00+00:00; first METAR received 2026-10-25T21:23:45.573496+00:00; actual 8°C.
Lead 293.090s (4.885min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-25T21:10:00+00:00; first stable correct 2026-10-25T21:18:52.483280+00:00; correct→wrong reversals 0; eligibility failures 2. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example2: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EHAM; station opensensemap:5fa3fc2867d8a1001b5f9d6d; sensor opensensemap:5fa3fc2867d8a1001b5f9d6d:5fa3fc2867d8a1001b5f9d70; distance 11.996km.
Previous METAR 12°C, nominal 2026-10-26T08:25:00+00:00, received 2026-10-26T08:21:59.720777+00:00.
PWS measured 2026-10-26T08:47:48.189000+00:00; first received 2026-10-26T08:47:57.380751+00:00; raw 12.13°C; age 9.192s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset 0.7750°C, quantization bounds [0.2750,1.2750]°C; 16 earlier cycles; latest calibration outcome received 2026-10-26T08:21:59.720777+00:00.
Calibrated 11.3550°C → integer 11; RAW integer 12 (raw correct=False); decision 2026-10-26T08:47:57.380751+00:00; target nominal 2026-10-26T08:55:00+00:00; first METAR received 2026-10-26T08:52:11.841493+00:00; actual 11°C.
Lead 254.461s (4.241min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T08:45:00+00:00; first stable correct 2026-10-26T08:47:57.380751+00:00; correct→wrong reversals 0; eligibility failures 1. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example3: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EPWA; station opensensemap:6941429cfdfe0700083492f4; sensor opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7; distance 9.762km.
Previous METAR 11°C, nominal 2026-10-26T14:30:00+00:00, received 2026-10-26T14:32:33.885610+00:00.
PWS measured 2026-10-26T14:57:30.142000+00:00; first received 2026-10-26T14:57:51.117474+00:00; raw 10.49°C; age 20.975s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset 0.6400°C, quantization bounds [0.1400,1.1400]°C; 26 earlier cycles; latest calibration outcome received 2026-10-26T14:32:33.885610+00:00.
Calibrated 9.8500°C → integer 10; RAW integer 10 (raw correct=True); decision 2026-10-26T14:57:51.117474+00:00; target nominal 2026-10-26T15:00:00+00:00; first METAR received 2026-10-26T15:02:28.137003+00:00; actual 10°C.
Lead 277.020s (4.617min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T14:50:00+00:00; first stable correct 2026-10-26T14:57:51.117474+00:00; correct→wrong reversals 0; eligibility failures 2. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example4: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EGLL; station opensensemap:626030a418aca4001ca27240; sensor opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243; distance 19.692km.
Previous METAR 12°C, nominal 2026-10-26T11:20:00+00:00, received 2026-10-26T11:24:24.114362+00:00.
PWS measured 2026-10-26T11:50:47.621000+00:00; first received 2026-10-26T11:51:07.438879+00:00; raw 12.39°C; age 19.818s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.6800°C, quantization bounds [-1.1800,-0.1800]°C; 29 earlier cycles; latest calibration outcome received 2026-10-26T11:24:24.114362+00:00.
Calibrated 13.0700°C → integer 13; RAW integer 12 (raw correct=False); decision 2026-10-26T11:51:07.438879+00:00; target nominal 2026-10-26T11:50:00+00:00; first METAR received 2026-10-26T11:54:59.753264+00:00; actual 13°C.
Lead 232.314s (3.872min); EXP_B; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T11:40:00+00:00; first stable correct 2026-10-26T11:51:07.438879+00:00; correct→wrong reversals 0; eligibility failures 9. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example5: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EPWA; station opensensemap:5d6145ec953683001a6b7fdb; sensor opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde; distance 10.445km.
Previous METAR 10°C, nominal 2026-10-26T12:00:00+00:00, received 2026-10-26T12:02:15.015575+00:00.
PWS measured 2026-10-26T12:27:33.610000+00:00; first received 2026-10-26T12:28:17.371673+00:00; raw 13.6°C; age 43.762s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-2: offset 2.2600°C, quantization bounds [1.7600,2.7600]°C; 19 earlier cycles; latest calibration outcome received 2026-10-26T12:02:15.015575+00:00.
Calibrated 11.3400°C → integer 11; RAW integer 14 (raw correct=False); decision 2026-10-26T12:28:17.371673+00:00; target nominal 2026-10-26T12:30:00+00:00; first METAR received 2026-10-26T12:32:18.779950+00:00; actual 11°C.
Lead 241.408s (4.023min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T12:23:11.243603+00:00; first stable correct 2026-10-26T12:28:17.371673+00:00; correct→wrong reversals 0; eligibility failures 3. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example6: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EGLL; station opensensemap:626030a418aca4001ca27240; sensor opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243; distance 19.692km.
Previous METAR 13°C, nominal 2026-10-26T12:20:00+00:00, received 2026-10-26T12:25:54.224344+00:00.
PWS measured 2026-10-26T12:51:12.867000+00:00; first received 2026-10-26T12:51:27.249548+00:00; raw 13.52°C; age 14.383s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.6200°C, quantization bounds [-1.1200,-0.1200]°C; 31 earlier cycles; latest calibration outcome received 2026-10-26T12:25:54.224344+00:00.
Calibrated 14.1400°C → integer 14; RAW integer 14 (raw correct=True); decision 2026-10-26T12:51:27.249548+00:00; target nominal 2026-10-26T12:50:00+00:00; first METAR received 2026-10-26T12:55:16.771878+00:00; actual 14°C.
Lead 229.522s (3.825min); EXP_B; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T12:40:30.280740+00:00; first stable correct 2026-10-26T12:51:27.249548+00:00; correct→wrong reversals 0; eligibility failures 4. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example7: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EDDM; station opensensemap:5beb063756a15500193139f0; sensor opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7; distance 16.398km.
Previous METAR 11°C, nominal 2026-10-26T09:50:00+00:00, received 2026-10-26T09:53:57.207068+00:00.
PWS measured 2026-10-26T10:21:12.175000+00:00; first received 2026-10-26T10:21:19.550364+00:00; raw 11.9°C; age 7.375s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.2900°C, quantization bounds [-0.7900,0.2100]°C; 31 earlier cycles; latest calibration outcome received 2026-10-26T09:53:57.207068+00:00.
Calibrated 12.1900°C → integer 12; RAW integer 12 (raw correct=True); decision 2026-10-26T10:21:19.550364+00:00; target nominal 2026-10-26T10:20:00+00:00; first METAR received 2026-10-26T10:24:42.870943+00:00; actual 12°C.
Lead 203.321s (3.389min); EXP_B; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T10:10:00+00:00; first stable correct 2026-10-26T10:21:19.550364+00:00; correct→wrong reversals 0; eligibility failures 3. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example8: EXPLORATORY_INCREMENTAL_SUCCESS

Airport EDDM; station opensensemap:5beb063756a15500193139f0; sensor opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7; distance 16.398km.
Previous METAR 6°C, nominal 2026-10-26T00:50:00+00:00, received 2026-10-26T00:54:14.118605+00:00.
PWS measured 2026-10-26T01:20:47.879000+00:00; first received 2026-10-26T01:21:25.524104+00:00; raw 6.61°C; age 37.645s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.3900°C, quantization bounds [-0.8900,0.1100]°C; 18 earlier cycles; latest calibration outcome received 2026-10-26T00:54:14.118605+00:00.
Calibrated 7.0000°C → integer 7; RAW integer 7 (raw correct=True); decision 2026-10-26T01:21:25.524104+00:00; target nominal 2026-10-26T01:20:00+00:00; first METAR received 2026-10-26T01:24:44.364247+00:00; actual 7°C.
Lead 198.840s (3.314min); EXP_B; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T01:10:00+00:00; first stable correct 2026-10-26T01:21:25.524104+00:00; correct→wrong reversals 0; eligibility failures 4. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example9: PERSISTENCE_CORRECT_PWS_FALSE_ALARM

Airport EDDM; station opensensemap:5beb063756a15500193139f0; sensor opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7; distance 16.398km.
Previous METAR 6°C, nominal 2026-10-26T04:50:00+00:00, received 2026-10-26T04:54:19.118949+00:00.
PWS measured 2026-10-26T05:19:03.952000+00:00; first received 2026-10-26T05:19:26.364573+00:00; raw 6.37°C; age 22.413s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.3250°C, quantization bounds [-0.8250,0.1750]°C; 24 earlier cycles; latest calibration outcome received 2026-10-26T04:24:53.341065+00:00.
Calibrated 6.6950°C → integer 7; RAW integer 6 (raw correct=True); decision 2026-10-26T05:19:26.364573+00:00; target nominal 2026-10-26T05:20:00+00:00; first METAR received 2026-10-26T05:23:42.832205+00:00; actual 6°C.
Lead 256.468s (4.274min); EXP_A; persistence correct=True; PWS correct=False; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct None; first stable correct None; correct→wrong reversals None; eligibility failures None. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example10: PERSISTENCE_CORRECT_PWS_FALSE_ALARM

Airport EHAM; station opensensemap:5fa3fc2867d8a1001b5f9d6d; sensor opensensemap:5fa3fc2867d8a1001b5f9d6d:5fa3fc2867d8a1001b5f9d70; distance 11.996km.
Previous METAR 11°C, nominal 2026-10-26T05:25:00+00:00, received 2026-10-26T05:22:27.098378+00:00.
PWS measured 2026-10-26T05:49:29.623000+00:00; first received 2026-10-26T05:49:36.633983+00:00; raw 12.73°C; age 7.011s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset 0.7750°C, quantization bounds [0.2750,1.2750]°C; 12 earlier cycles; latest calibration outcome received 2026-10-26T05:22:27.098378+00:00.
Calibrated 11.9550°C → integer 12; RAW integer 13 (raw correct=False); decision 2026-10-26T05:49:36.633983+00:00; target nominal 2026-10-26T05:55:00+00:00; first METAR received 2026-10-26T05:52:37.455317+00:00; actual 11°C.
Lead 180.821s (3.014min); EXP_A; persistence correct=True; PWS correct=False; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct None; first stable correct None; correct→wrong reversals None; eligibility failures None. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example11: PERSISTENCE_CORRECT_PWS_FALSE_ALARM

Airport EPWA; station opensensemap:6941429cfdfe0700083492f4; sensor opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7; distance 9.762km.
Previous METAR 9°C, nominal 2026-10-26T10:00:00+00:00, received 2026-10-26T10:03:07.134480+00:00.
PWS measured 2026-10-26T10:28:07.323000+00:00; first received 2026-10-26T10:29:38.334406+00:00; raw 10.37°C; age 91.011s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset 0.6400°C, quantization bounds [0.1400,1.1400]°C; 21 earlier cycles; latest calibration outcome received 2026-10-26T10:03:07.134480+00:00.
Calibrated 9.7300°C → integer 10; RAW integer 10 (raw correct=False); decision 2026-10-26T10:29:38.334406+00:00; target nominal 2026-10-26T10:30:00+00:00; first METAR received 2026-10-26T10:33:01.104904+00:00; actual 9°C.
Lead 202.770s (3.380min); EXP_A; persistence correct=True; PWS correct=False; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct None; first stable correct None; correct→wrong reversals None; eligibility failures None. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example12: PERSISTENCE_CORRECT_PWS_FALSE_ALARM

Airport EGLL; station opensensemap:626030a418aca4001ca27240; sensor opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243; distance 19.692km.
Previous METAR 9°C, nominal 2026-10-25T20:50:00+00:00, received 2026-10-25T20:54:50.590570+00:00.
PWS measured 2026-10-25T21:13:11.856000+00:00; first received 2026-10-25T21:15:36.391719+00:00; raw 8.77°C; age 144.536s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.9250°C, quantization bounds [-1.4250,-0.4250]°C; 12 earlier cycles; latest calibration outcome received 2026-10-25T20:54:50.590570+00:00.
Calibrated 9.6950°C → integer 10; RAW integer 9 (raw correct=True); decision 2026-10-25T21:15:36.391719+00:00; target nominal 2026-10-25T21:20:00+00:00; first METAR received 2026-10-25T21:24:46.533879+00:00; actual 9°C.
Lead 550.142s (9.169min); EXP_A; persistence correct=True; PWS correct=False; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct None; first stable correct None; correct→wrong reversals None; eligibility failures None. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example13: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EDDM; station opensensemap:5beb063756a15500193139f0; sensor opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7; distance 16.398km.
Previous METAR 7°C, nominal 2026-10-25T20:50:00+00:00, received 2026-10-25T20:53:49.796613+00:00.
PWS measured 2026-10-25T21:08:50.689000+00:00; first received 2026-10-25T21:08:50.957640+00:00; raw 7.32°C; age 0.269s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.4300°C, quantization bounds [-0.9300,0.0700]°C; 12 earlier cycles; latest calibration outcome received 2026-10-25T20:53:49.796613+00:00.
Calibrated 7.7500°C → integer 8; RAW integer 7 (raw correct=False); decision 2026-10-25T21:10:00+00:00; target nominal 2026-10-25T21:20:00+00:00; first METAR received 2026-10-25T21:23:45.573496+00:00; actual 8°C.
Lead 825.573s (13.760min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-25T21:10:00+00:00; first stable correct 2026-10-25T21:18:52.483280+00:00; correct→wrong reversals 0; eligibility failures 2. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example14: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EHAM; station opensensemap:5fa3fc2867d8a1001b5f9d6d; sensor opensensemap:5fa3fc2867d8a1001b5f9d6d:5fa3fc2867d8a1001b5f9d70; distance 11.996km.
Previous METAR 12°C, nominal 2026-10-26T08:25:00+00:00, received 2026-10-26T08:21:59.720777+00:00.
PWS measured 2026-10-26T08:42:16.283000+00:00; first received 2026-10-26T08:42:24.997308+00:00; raw 12.14°C; age 8.714s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset 0.7750°C, quantization bounds [0.2750,1.2750]°C; 16 earlier cycles; latest calibration outcome received 2026-10-26T08:21:59.720777+00:00.
Calibrated 11.3650°C → integer 11; RAW integer 12 (raw correct=False); decision 2026-10-26T08:45:00+00:00; target nominal 2026-10-26T08:55:00+00:00; first METAR received 2026-10-26T08:52:11.841493+00:00; actual 11°C.
Lead 431.841s (7.197min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T08:45:00+00:00; first stable correct 2026-10-26T08:47:57.380751+00:00; correct→wrong reversals 0; eligibility failures 1. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example15: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EPWA; station opensensemap:6941429cfdfe0700083492f4; sensor opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7; distance 9.762km.
Previous METAR 11°C, nominal 2026-10-26T14:30:00+00:00, received 2026-10-26T14:32:33.885610+00:00.
PWS measured 2026-10-26T14:46:31.752000+00:00; first received 2026-10-26T14:46:50.831865+00:00; raw 10.65°C; age 19.080s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset 0.6400°C, quantization bounds [0.1400,1.1400]°C; 26 earlier cycles; latest calibration outcome received 2026-10-26T14:32:33.885610+00:00.
Calibrated 10.0100°C → integer 10; RAW integer 11 (raw correct=False); decision 2026-10-26T14:50:00+00:00; target nominal 2026-10-26T15:00:00+00:00; first METAR received 2026-10-26T15:02:28.137003+00:00; actual 10°C.
Lead 748.137s (12.469min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T14:50:00+00:00; first stable correct 2026-10-26T14:57:51.117474+00:00; correct→wrong reversals 0; eligibility failures 2. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example16: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EGLL; station opensensemap:626030a418aca4001ca27240; sensor opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243; distance 19.692km.
Previous METAR 12°C, nominal 2026-10-26T11:20:00+00:00, received 2026-10-26T11:24:24.114362+00:00.
PWS measured 2026-10-26T11:39:24.752000+00:00; first received 2026-10-26T11:39:46.745392+00:00; raw 12.22°C; age 21.993s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.6800°C, quantization bounds [-1.1800,-0.1800]°C; 29 earlier cycles; latest calibration outcome received 2026-10-26T11:24:24.114362+00:00.
Calibrated 12.9000°C → integer 13; RAW integer 12 (raw correct=False); decision 2026-10-26T11:40:00+00:00; target nominal 2026-10-26T11:50:00+00:00; first METAR received 2026-10-26T11:54:59.753264+00:00; actual 13°C.
Lead 899.753s (14.996min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T11:40:00+00:00; first stable correct 2026-10-26T11:51:07.438879+00:00; correct→wrong reversals 0; eligibility failures 9. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example17: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EPWA; station opensensemap:5d6145ec953683001a6b7fdb; sensor opensensemap:5d6145ec953683001a6b7fdb:5d6145ec953683001a6b7fde; distance 10.445km.
Previous METAR 10°C, nominal 2026-10-26T12:00:00+00:00, received 2026-10-26T12:02:15.015575+00:00.
PWS measured 2026-10-26T12:22:35.622000+00:00; first received 2026-10-26T12:23:11.243603+00:00; raw 13.4°C; age 35.622s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-2: offset 2.2600°C, quantization bounds [1.7600,2.7600]°C; 19 earlier cycles; latest calibration outcome received 2026-10-26T12:02:15.015575+00:00.
Calibrated 11.1400°C → integer 11; RAW integer 13 (raw correct=False); decision 2026-10-26T12:23:11.243603+00:00; target nominal 2026-10-26T12:30:00+00:00; first METAR received 2026-10-26T12:32:18.779950+00:00; actual 11°C.
Lead 547.536s (9.126min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T12:23:11.243603+00:00; first stable correct 2026-10-26T12:28:17.371673+00:00; correct→wrong reversals 0; eligibility failures 3. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example18: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EGLL; station opensensemap:626030a418aca4001ca27240; sensor opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243; distance 19.692km.
Previous METAR 13°C, nominal 2026-10-26T12:20:00+00:00, received 2026-10-26T12:25:54.224344+00:00.
PWS measured 2026-10-26T12:40:17.480000+00:00; first received 2026-10-26T12:40:30.280740+00:00; raw 13.23°C; age 12.801s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.6200°C, quantization bounds [-1.1200,-0.1200]°C; 31 earlier cycles; latest calibration outcome received 2026-10-26T12:25:54.224344+00:00.
Calibrated 13.8500°C → integer 14; RAW integer 13 (raw correct=False); decision 2026-10-26T12:40:30.280740+00:00; target nominal 2026-10-26T12:50:00+00:00; first METAR received 2026-10-26T12:55:16.771878+00:00; actual 14°C.
Lead 886.491s (14.775min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T12:40:30.280740+00:00; first stable correct 2026-10-26T12:51:27.249548+00:00; correct→wrong reversals 0; eligibility failures 4. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example19: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EDDM; station opensensemap:5beb063756a15500193139f0; sensor opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7; distance 16.398km.
Previous METAR 11°C, nominal 2026-10-26T09:50:00+00:00, received 2026-10-26T09:53:57.207068+00:00.
PWS measured 2026-10-26T10:06:12.333000+00:00; first received 2026-10-26T10:06:13.378272+00:00; raw 11.55°C; age 1.045s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.2900°C, quantization bounds [-0.7900,0.2100]°C; 31 earlier cycles; latest calibration outcome received 2026-10-26T09:53:57.207068+00:00.
Calibrated 11.8400°C → integer 12; RAW integer 12 (raw correct=True); decision 2026-10-26T10:10:00+00:00; target nominal 2026-10-26T10:20:00+00:00; first METAR received 2026-10-26T10:24:42.870943+00:00; actual 12°C.
Lead 882.871s (14.715min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T10:10:00+00:00; first stable correct 2026-10-26T10:21:19.550364+00:00; correct→wrong reversals 0; eligibility failures 3. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

### Example20: EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT

Airport EDDM; station opensensemap:5beb063756a15500193139f0; sensor opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7; distance 16.398km.
Previous METAR 6°C, nominal 2026-10-26T00:50:00+00:00, received 2026-10-26T00:54:14.118605+00:00.
PWS measured 2026-10-26T01:05:48.092000+00:00; first received 2026-10-26T01:06:21.591543+00:00; raw 7.02°C; age 33.500s; provenance SENSOR_MEASUREMENT_TIME; QC VALID.
CAL-1: offset -0.3900°C, quantization bounds [-0.8900,0.1100]°C; 18 earlier cycles; latest calibration outcome received 2026-10-26T00:54:14.118605+00:00.
Calibrated 7.4100°C → integer 7; RAW integer 7 (raw correct=True); decision 2026-10-26T01:10:00+00:00; target nominal 2026-10-26T01:20:00+00:00; first METAR received 2026-10-26T01:24:44.364247+00:00; actual 7°C.
Lead 884.364s (14.739min); EXP_A; persistence correct=False; PWS correct=True; selected then=True; RETROSPECTIVE_AS_OF_RECONSTRUCTION.
First correct 2026-10-26T01:10:00+00:00; first stable correct 2026-10-26T01:21:25.524104+00:00; correct→wrong reversals 0; eligibility failures 4. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.

## Real prospective forecasts

Original immutable production forecasts retain their original methods/parameters; none is relabeled CAL-1/CAL-2. A PWS contribution is association, not causal proof of sensor benefit. Same-airport/checkpoint/target recorded persistence comparisons below.

```json
{
  "EDDM": {
    "total_predictions": 3044,
    "valid_forecasts": 2808,
    "excluded_forecasts": 236,
    "pending_forecasts": 0,
    "distinct_valid_cycles": 106,
    "exclusion_flags": {
      "CENSORED_REFERENCE_RECEIPT": 101,
      "SETTLEMENT_NOT_UNCENSORED_PROSPECTIVE": 101,
      "MISSING_MEASUREMENT_TIME": 162,
      "UNKNOWN_TIMESTAMP_PROVENANCE": 162,
      "STALE_AT_DECISION": 28,
      "UNVERIFIED_PARAMETER_TIMESTAMP_POLICY": 147,
      "FUTURE_MEASUREMENT_AT_RECEIPT": 2
    }
  },
  "EHAM": {
    "total_predictions": 1835,
    "valid_forecasts": 1639,
    "excluded_forecasts": 154,
    "pending_forecasts": 42,
    "distinct_valid_cycles": 107,
    "exclusion_flags": {
      "MISSING_MEASUREMENT_TIME": 141,
      "UNKNOWN_TIMESTAMP_PROVENANCE": 141,
      "SETTLEMENT_NOT_UNCENSORED_PROSPECTIVE": 13,
      "TARGET_ALREADY_RECEIVED": 4,
      "UNVERIFIED_PARAMETER_TIMESTAMP_POLICY": 135,
      "CENSORED_REFERENCE_RECEIPT": 9
    }
  },
  "EPWA": {
    "total_predictions": 3069,
    "valid_forecasts": 2757,
    "excluded_forecasts": 312,
    "pending_forecasts": 0,
    "distinct_valid_cycles": 104,
    "exclusion_flags": {
      "MISSING_MEASUREMENT_TIME": 156,
      "UNKNOWN_TIMESTAMP_PROVENANCE": 156,
      "UNVERIFIED_PARAMETER_TIMESTAMP_POLICY": 141,
      "STALE_AT_DECISION": 38,
      "SETTLEMENT_NOT_UNCENSORED_PROSPECTIVE": 162,
      "CENSORED_REFERENCE_RECEIPT": 156
    }
  },
  "EGLL": {
    "total_predictions": 2897,
    "valid_forecasts": 2649,
    "excluded_forecasts": 248,
    "pending_forecasts": 0,
    "distinct_valid_cycles": 106,
    "exclusion_flags": {
      "CENSORED_REFERENCE_RECEIPT": 98,
      "SETTLEMENT_NOT_UNCENSORED_PROSPECTIVE": 98,
      "MISSING_MEASUREMENT_TIME": 162,
      "UNKNOWN_TIMESTAMP_PROVENANCE": 162,
      "STALE_AT_DECISION": 78,
      "UNVERIFIED_PARAMETER_TIMESTAMP_POLICY": 147
    }
  }
}
```

| Actual T−60 model | Matched cycles | Correct | Recorded persistence | Incremental correct | Harm | Net |
|---|---:|---:|---:|---:|---:|---:|
| EDDM|T-60s|inverse_distance | 82 | 32 | 52 | 9 | 29 | -20 |
| EDDM|T-60s|median | 82 | 34 | 52 | 9 | 27 | -18 |
| EDDM|T-60s|nearest | 82 | 22 | 52 | 7 | 37 | -30 |
| EGLL|T-60s|inverse_distance | 75 | 18 | 48 | 6 | 36 | -30 |
| EGLL|T-60s|median | 75 | 17 | 48 | 5 | 36 | -31 |
| EGLL|T-60s|nearest | 75 | 25 | 48 | 8 | 31 | -23 |
| EHAM|T-60s|inverse_distance | 7 | 1 | 4 | 0 | 3 | -3 |
| EHAM|T-60s|median | 7 | 2 | 4 | 0 | 2 | -2 |
| EHAM|T-60s|nearest | 7 | 2 | 4 | 0 | 2 | -2 |
| EPWA|T-60s|inverse_distance | 81 | 15 | 52 | 6 | 43 | -37 |
| EPWA|T-60s|median | 82 | 12 | 53 | 5 | 46 | -41 |
| EPWA|T-60s|nearest | 82 | 14 | 53 | 5 | 44 | -39 |

## Interpretation and limitations

Per-sensor results must be compared against persistence on their SAME eligible cycles. Do not rank raw percentages with unequal coverage; ranking CSV orders the predefined CAL-2/T−60 endpoint and marks N<30 insufficient. Search is exploratory across airports, sensors,3methods and many decision times; isolated wins are expected by chance. Earliest correct and first stable are outcome-conditioned diagnostics within the searched T−10min window. Stability checks expiry and calibration/reference/metadata events; pre-observation inputs carried past nominal do not count as new EXP-B data. Fixed EXP-B checkpoints require a first PWS receipt>=nominal. No confidence/significance claim from this short correlated sample. Offsets are estimated from integer-reference midpoint intervals, not precise airport truth. Installation/microclimate, provider update delays, gaps and unknown clock offset remain confounders.

## Reproduce

```powershell
uv run python -m scripts.research.early_metar_reconstruction --snapshot data/research/exp0010/snapshot.sqlite3
```

Local snapshot/raw payloads remain ignored. Manifest and sanitized summaries/examples are committed; full candidate diagnostics remain in ignored data/research/exp0010. Never write reconstructed candidates to production prediction tables.

## Direct answers and candidate for future shadow test

YES: calibrated PWS data recorded before our earliest METAR receipt can reconstruct changed integers that persistence misses. This is retrospective, exploratory information-availability evidence, NOT proof a rule was chosen or executed prospectively.

The illustrated calibrated wins also disclose RAW integer correctness; calibration is not credited when raw data already gave the same integer. Eight selected success examples are outcome-conditioned, not a denominator. All inferior groups/failures remain in the full summary CSV. Sensor.Community timestamp proxies do not become measurement clocks; unknown timestamps stay excluded.

### Predefined endpoint: CAL-2 at T−60, descriptive leaders

| Airport | Sensor | N | Calibrated | Raw SAME cycles | Persistence | Gain | Harm | Net | Correct changes / actual changes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EDDM | opensensemap:5beb063756a15500193139f0:5beb063756a15500193139f7 | 38 | 22 | 21 | 21 | 8 | 7 | 1 | 8/17 |
| EHAM | INSUFFICIENT DATA / already-received targets | 0 | — | — | — | — | — | — | — |
| EPWA | opensensemap:6941429cfdfe0700083492f4:6941429cfdfe0700083492f7 | 17 | 11 | 6 | 10 | 5 | 4 | 1 | 5/7 |
| EGLL | opensensemap:626030a418aca4001ca27240:626030a418aca4001ca27243 | 26 | 17 | 11 | 19 | 3 | 5 | -2 | 3/7 |

EDDM esride_krb1 (station5beb063756a15500193139f0, instrument5beb063756a15500193139f7,16.398km) is the most useful *candidate to investigate next*, not a validated winner. On its38 T−60/CAL-2 cycles calibrated22,raw21,persistence21: gain8,harm7,net+1. Its latest actual EXP-B receipt endpoint has33cycles,19correct vs18persistence, gain6,harm5,net+1. Thus repeated successes coexist with almost as many harms. Do not interpret the more favorable exploratory T+90 subset (17cycles,+4net) as an independently selected validated rule.

EPWA SaveDnipro is relatively good in absolute agreement after calibration: T−60/CAL-2 eleven of17 vsraw6 andpersistence10, gain5/harm4. This is too small for ranking. EGLL wd3-5 improves raw agreement after calibration but still underperforms persistence. EHAM's early KNMI receipts close most late/pre-publication opportunities; CAL-1/T−300 for Diemen has9/21 vs14/21persistence (gain4/harm9). There is no calibrated EXP-B sample there. Original production PWS forecasts remain separate and mostly lose to recorded persistence; this does not invalidate the recorded candidate examples, but prevents a live-edge claim.

### Frozen future rule proposal — NOT DEPLOYED

Use ONLY the fixed EDDM instrument above, CAL-2. At EVERY new unique trustworthy source measurement receipt between nominal T−10min and the first recorded target METAR receipt, compute b=median(PWS_aligned−initial_METAR_integer) over earlier nominal cycles in the trailing12hours, with>=12distinct earlier cycles. All outcomes must have been received strictly before computation, all pair sensor data frozen as of their earlier outcome receipt. Estimate=raw_PWS−b; integer=ICAO nearest Celsius with exact ties toward warmer. Report b±0.5°C quantization bounds, not confidence. Require valid accepted measurement provenance, event<=creation, receipt<=creation, age<=300s, physical/exposure checks. Close on ANY provider/COR target receipt, including early KNMI. Persist actual calculation completion time and original input/calibration IDs; never timestamp the result as if computation were instantaneous.

Emit every shadow revision (do NOT choose the retrospectively latest receipt); label EXP-A and EXP-B separately, with no old pre-nominal receipt relabeled as new EXP-B data. Freeze station/method/window/thresholds before future collection, keep all misses/gaps/reversals, and evaluate once per target/checkpoint with matched persistence. Suggested evaluation horizon>=7future local days,>=200matched cycles and>=30temperature transitions; report day-block uncertainty and no repeated peeking/threshold tuning. This experiment does not authorize activating or changing any production rule.

Earliest-correct and first-stable results are in early_metar_stability.csv. An unchanged correct integer is not incremental information; gains require PWS correct AND previous METAR wrong. Temperatures at multiple instruments of one provider station are not independent physical weather stations. Cross-airport/sensor/model/time search creates substantial multiplicity; apparent+1nets are INSUFFICIENT DATA for a reliable actionable edge.

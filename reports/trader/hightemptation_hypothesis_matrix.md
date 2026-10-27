# EXP-0011 public trader research

Generated UTC: 2026-10-27T09:34:30.053034+00:00

Historical/bootstrap trades are not prospective detections. Source trade time is not order placement time.

Recorded event counts: `{"ACTIVITY": 45, "BACKFILL_STATE": 12, "BOOK": 2356, "COPY_COMPLETE": 12, "COPY_REQUEST": 12, "DATA_SERVICE_STATUS": 33, "DISCOVERY": 8, "ENDPOINT_RECEIPT": 641, "ERROR": 2, "EXECUTION_GROUP": 597, "HEALTH": 183, "MARKET": 3657, "PROFILE_VERIFIED": 7, "RAW": 1282, "ROLE_EVIDENCE": 104, "RUN": 7, "SHADOW": 72, "STOP": 6, "STREAMHEALTH": 86, "TRADE": 11865, "WEATHER": 2, "WS_DELTA": 56670, "WS_RAW": 57371, "WS_TRADE": 148}`.

| Hypothesis | Discriminating observation | Missing evidence | Conclusion |
|---|---|---|---|
| H1 Early official information | Official original receipt precedes wallet execution | Unobserved faster feeds and order placement time | UNVERIFIED |
| H2 PWS information | Fresh causal PWS signal precedes execution | Trader access to same station; confounding signals | UNVERIFIED |
| H3 Probabilistic Tmax | Frozen forecasts explain entries and comparable no-trades | Original forecast versions and probability model | UNVERIFIED |
| H4 Known-information mispricing | Exact verified rules and already public irreversible bound | Rules, corrections, source precision | UNVERIFIED |
| H5 Microstructure | Independent book movement precedes execution | Wallet attribution and queue position | UNVERIFIED |
| H6 Resting limits | Verified maker role supports earlier resting instruction | Order creation/cancellation history | UNVERIFIED |
| H7 Hybrid | Different predeclared regimes explain out-of-sample entries | Independent days and negative controls | UNVERIFIED |

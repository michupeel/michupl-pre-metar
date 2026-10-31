# EXP0018 — acceptance and research findings

31 October2026, branch `research/hightemptation-entry-reconstruction`.
Plan `fc3d7e2`, implementation `e6a598b`; baseline `6d2c9e8` preserved.
Additional capture configuration/health commits: `711b698`, `c14f765`.

1. Plan/task queue committed before broad implementation; no existing collector
   process or Windows task changed. No production DB migration/write.
2. Ten identified local-eligible tasks, all10 delegated through existing MCPs.
   This is task coverage, not percentage of code authored locally.
3. Eight actual patch proposals; six partially adapted (75% proposals); six/seven
   unique implementation tasks yielded usable parts. Two I1 proposals rejected.
4. Unmodified first-pass acceptance0/7; raw-patch test-pass rate unmeasured.
   Accepted code reviewed/adapted and covered by1111 passing tests.
5. Local task inference/research209.162s plus health0.690s; known25,448tokens,
   research tokens unknown. Review/correction/end-to-end timingNULL. No measured
   speed/token benefit; local review quality poor, correction overhead substantial.
6. Implemented bounded paired snapshot/delta ring, explicit gaps/epochs and as-of
   price/depth features; no server sequence or executable queue certification.
7. Independent public socket uses frozen16market/32token manifest from existing
   metadata, raw-first isolated storage, no new HTTP polls or source subscriptions.
   Implemented and bounded-smoked, NOT persistently deployed.
8. Replay1.5million original source IDs,~22h56m,12NO entries0.90–0.99. Eleven lack
   ANY earlier original NO full snapshot; one has paired one-sided information.
   No full five-minute pre-entry window. Zero fresh paired two-sided midpoints.
9. Wellington NZWN, NO on lowest temperature10°C31Oct: BUY207.78 at VWAP
   0.9434998556; Data API source08:58:33UTC, detection08:58:35.148661UTC.
   Recorded NO bid0.10→0.99 at08:58:29.863130UTC (3.136870s before source time).
   Latest prior NO bid0.99/1312shares, askEMPTY; YES bidEMPTY/ask0.01. One-sided
   information is real; midpoint/spread NULL is correct, not missing measurement.
10. This does NOT establish a trigger before the trader's decision or matching.
    Repricing may be caused by the same trade before later Data API/on-chain
    timestamping. Placement time unknown; API_ATTRIBUTED_TAKER evidence joined
    later, exact taker_only=true row, not independent chain-role verification.
11. No matched controls satisfied all available constraints (N0). Other required
    confounders (verified publication, forecast realization, market age and exact
    settlement-window timing) remain missing. Momentum superiority unidentified.
12. Actual official publication clocks aren't inferred from nominal times. Global
    official/PWS/forecast as-of evidence unavailable stays UNKNOWN; four configured
    airport schedules aren't generalized to global stations or old schedules.
13. Conditional FIFO sample11closed/oneopen, gross sum53.821370006658USD before
    unknown costs; this is the trader's conditional gross, NOT our shadow PnL.
    Opening inventory and all non-trade history before replay cutoff unverified.
    NZWN BUY was matched to SELL08:58:39 at0.99, gross9.661800003432USD conditional.
14. Copy/independent-entry execution, fees, net ROI and maker queue profitability
    NOT IDENTIFIABLE. Empty NO asks at detection do not support a direct BUY fill.
    No optimistic fills, new trading strategy or frozen trigger promoted.
15. Bounded public smoke61.032s:209WS_RAW/192BOOK/203delta,16contracts32tokens,
    zero new wallet entries. Five abrupt connection closures: DEGRADED. All203
    delta packets had valid seeds and reported-BBO consistency in that run.
    Additional4contract/8token bounded run31.032s:8BOOK/6delta, one connection,
    no reconnect. Callback max16ms/coarse timer; no long-soak or causal fix claim.
16. Restart/local-feed smoke10s:2BOOK/70delta, no future-clock rejects. Fixed an
    EXP0018-only cycle-start race by deferring just-appended rows; no timestamp
    policy weakened. Existing timestamp/first-receipt records untouched.
17. Verification: `uv sync --locked`53packages;1111pytestPASS32.84s; RuffcheckPASS,
    Ruffformat249filesPASS; strictmypy92filesPASS including new analysis script.
    New raw/journal integrityPASS, weather quick_checkPASS. No long25GB trader
    integrity scan or long snapshot transaction. Source indexed reads only.
18. Dashboard root/static JS/catalog HTTP200, JS syntax and synthetic DOM/replay
    checksPASS. Real rendered-browser verification BLOCKED by MXC invalidI:volume
    /trustedNode runtime exit. No screenshot or visual-pass fabrication.
19. Existing weather PID11236, trader11748, dashboard32732, EXP0017observer36160
    remained running with original creation times. D1 task Ready/notRunning;
    not restarted. EXP0018 bounded runs completed; no persistent task installed.
20. EXP0019 next: resolve public socket disconnects, approve persistent isolated
    capture, measure paired coverage across future independent settlement days,
    then freeze a small predeclared trigger family and controls. No actionable
    independent entry rule or robust copy-trading edge established by EXP0018.

The smaller-cohort diagnostic is configured explicitly with `--max-contracts4`;
it is not a retrospective trading-rule optimization. Default16 wasn't changed.

## Reproducibility and metric definitions

See `EXP0018_OPERATIONS.md` for exact commands/limits and original instruction
requiring approval before permanent activation. Source cutoff7437602, lower
exclusive5937602; first30Oct23:07:30.216628UTC, last31Oct22:03:33.150905UTC.
Original IDs preserve append-only evidence without a long live read transaction.
Reports were generated later and clearly labeled retrospective replay.

`paired_pre_execution` in the current report counts fresh recorded pairs even
when one-sided. `paired_two_sided_pre_execution` separately requires both mids.
The initial snapshot baseline's old metric was midpoint-based; do NOT interpret
0→1 across those differently defined fields as an economic performance gain.
The independent RAW coverage audit bypasses the ring/parser:11/12truly have no
earlier NO full snapshot; the remaining instrument has7earlier snapshots, latest
3.162896s before source time. Delta replay exposes its pre-source0.99bid movement.
Default full-snapshot validation and optional reconstruction share zero complete
five-minute windows and zero usable matched-control comparisons.

Machine-readable artifacts: `exp0018_entry_features.csv`, `exp0018_controls.csv`,
`exp0018_fifo_matches.csv`, `exp0018_raw_book_coverage.json`,
`exp0018_operational_validation.json`, `exp0018_socket_diagnostic.json` and full
`exp0018_entry_trigger_reconstruction.json` under `reports/trader`.
Raw captures remain ignored under `data/research/exp0018`; no credentials/raw DBs
are committed. This research remains OPEN/INCONCLUSIVE.

# Milestone 1.7 frozen protocol

Baseline source:59c377c. Snapshot data/research/m17/snapshot.sqlite3, captured
2026-10-26T12:26:35Z, SHA256706dd79d7f8a7fe6e689cc61489abadd3851523864a07e09b5966082356a4c1c.
No production rules or cohort changes. Four requested station identities fixed
before evaluation. All stored genuine readings included in inventory; strict
existing eligibility at first receipt and at each decision remains mandatory.

H1: raw PWS integer improves on previous routine METAR. H2: trailing causal
interval-residual median correction improves H1. H3: last-METAR plus PWS change
since that last-METAR observation improves persistence. No ML/hyperparameter search.
Primary endpoint: exact integer accuracy versus persistence on matched targets,
with interval-distance error and transition direction/false alarms secondary.

Decision checkpoint fixed T-60s before nominal routine observation, only if the
target has not already been received. Also report T+60s distribution-window
experiment separately only if target not received. These are retrospective
as-of replays, NEVER immutable prospective predictions. Evaluate actual stored
forecasts separately by recorded checkpoint/model. First initial routine report
is primary; COR/SPECI retained in exports and excluded from routine target series;
ambiguous conflicting initial outcomes excluded. Startup/coverage censoring stated.

Only measurements received by decision, event<=decision, age<=300s and valid
provenance, physical/exposure checks pass. Avoid duplicate instrument counts.
Use fixed station set, per-sensor metrics and pairwise/all-station matched targets.
Calibration: latest48h of earlier causal target pairs, minimum12; outcome first
receipt<decision; interval residual (quantized reference), not exact-temperature
bias. Training pairs freeze original decision inputs. Trend requires valid
measurement received by previous METAR first receipt and near that event (5min);
new PWS minus anchor PWS is added to previous METAR. METAR trend uses previous
2 timely available routine reports. Ensemble equal weights over >=2 distinct
provider stations; no outcome-driven station selection. Insufficient cases explicit.

Operational ranking: lexicographic valid receipt fraction, fresh checkpoint
coverage, median receipt age, largest gap; separate predictive ranking on identical
eligible targets. At least30 target cycles for preliminary ranking; fewer means
INSUFFICIENT DATA. Even30 is provisional. No robust edge claim without multi-day
out-of-sample evidence. Report paired day-block uncertainty only with >=5 local
days; otherwise INSUFFICIENT DATA (no independent-observation confidence interval).
Confounders: short history, station entry times, quantization, spatial microclimate,
unknown shielding, clock uncertainty, provider timing and gaps. Do not tune rules
after results or conflate operational and predictive ranking.

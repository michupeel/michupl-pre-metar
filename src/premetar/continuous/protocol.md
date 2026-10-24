# Continuous prospective protocol v1

Question: can selected open PWS improve the next routine METAR integer forecast
over matched persistence targets before our first configured reference receipt?

Freeze candidate identities, configuration, source hashes and schedule at startup.
EDDM/EGLL20,50; EHAM25,55; EPWA00,30 UTC are empirical schedule assumptions.
Preserve SPECI/COR/AUTO and full TAC identities; do not settle SPECI or off-slot reports.

EXP-A only: create predictions at real completion times, strictly before nominal
target. Do not recreate expired slots. Block targets already received, even when
their nominal times are ahead. Use receive<=input cutoff, measurement<=input cutoff,
prior selection/metadata/QC/calibration only. Unknown measurement time on
Sensor.Community remains NULL; its labelled server-ingest proxy is not sensor latency.

Freeze forecast inputs and estimator IDs in the existing immutable prediction table.
QC/calibration is published after computation, never as if it existed at its input cutoff.
Settlements append immutable report versions; compare initial outcomes by default.
Conflicting initial reports invalidate that target; corrections remain separate views.

Score exact integer/within1C accuracy and integer errors separately from continuous
distance to the WMO quantization interval. Compare models only on matched
airport/target/checkpoint samples. Persistence alias is not an independent model.
Day-block intervals require100 matched targets and7 UTC days; cross-day dependence
and station selection remain limitations. No edge conclusion from small samples.

Information lead is first receive among our configured sources minus actual prediction
creation, not global publication lead. Use run-scoped monotonic clocks only within a run.
Retain UTC offset uncertainty and reference startup/gap censoring. EXP-B disabled.
No paid sources, unauthorized scraping, trading or runtime LLM dependency.

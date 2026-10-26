# Interpreting EPWA sensor comparisons

Raw temperature is the uncorrected PWS reading. Causal correction subtracts a
rolling median residual against METAR rounding intervals, using only earlier
outcomes actually received before the decision (48-hour window, minimum12
samples). This is not calibration against a precise airport thermometer.

The PWS-change model adds the same instrument's temperature change since the
previous METAR anchor to the previous reported integer. It tests whether changes
carry information even when absolute values have an offset. It does not mean
firmware changes, instrument replacement or retrospective calibration changes.

Compare each candidate with persistence on exactly the same eligible target
cycles. Compare stations on their common target intersection; separately show
coverage lost through freshness or calibration requirements. Do not select the
best observed model and present its evaluation period as an independent test.

A false alarm is a predicted change when the METAR integer actually remains
unchanged. A correct direction is weaker than predicting the correct new integer.
Repeated checkpoints for one target are not independent weather events.

As-of replay can reconstruct what inputs were available, but it is a retrospective
analysis, not a genuine immutable forecast created at that time. Actual stored
forecasts are a separate evidence class. Measurement time is not receipt time;
T−60 pre-observation and T+60 pre-receipt experiments must remain separate.

Zero distance to a rounding interval at its boundary does not necessarily mean
the predicted integer matches. Resolution, decimal formatting and accuracy are
different quantities. Chip metadata does not verify installed hardware, mounting,
radiation shielding or ambient-air representativeness. Small correlated samples
cannot establish a robust information edge.

Local Qwen proposed general caution paragraphs; Codex corrected the model
definitions and sample threshold, reviewed this text and owns the methodology.

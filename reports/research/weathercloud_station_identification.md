# EXP-0013 — Weathercloud EPWA candidates

Investigated28October2026; no scraping, undocumented endpoint or invented reading.

|Candidate|User coordinates|User elevation|Computed horizontal distance from stored EPWA52.163,20.961|Identity/access|
|---|---|---|---|---|
|A|52.180556,20.943611|120m(unverified)|2.284km|UNKNOWN|
|B|52.158056,20.924722|114m(unverified)|2.535km|UNKNOWN|

Coordinates/elevations identify user-suggested locations, not verified hardware. Indexed coordinate and locality searches did not establish station URL, owner, model, exact cadence, timestamp provenance or cross-provider hardware identity. Approximate coordinates alone cannot prove the same physical station.

Official [Weathercloud FAQ](https://weathercloud.net/en/faq) states no API for retrieving weather data. Its documented upload API cannot be reused as a read API. Platform upload cadences do not establish measurement cadence for either instrument. No automated values were collected from these candidates.

Possible legitimate next step: identify the public station link and owner, then inspect a documented owner-supported export or authorized alternate feed with actual measurement timestamps. No owner was contacted and no access or subscription purchased. Machine-readable availability remains UNKNOWN. Existing openSenseMap collection continues independently.

Full primary-source audit:docs/research/EXP0013_SOURCES.md.

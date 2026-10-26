# EPWA hardware evidence — checked26October2026

These are provider-declared instrument names, not authenticated physical hardware.
No photographs, mounting survey or shielding evidence are present. Station-level
manufacturer/model/elevation fields remain NULL. Model-family makers below are
documented, not proof of the particular installed part's provenance.

| Station | Coordinates lat/lon | Temperature sensor ID | Declared type | Model-family maker |
|---|---|---|---|---|
| Cybernetyki7 /61c1f4ff80a739001cda08bb |52.173951/20.995753|61c1f4ff80a739001cda08bd|BMP180|Bosch Sensortec|
| Czerniakowska /5c6e9151154515001982e4da |52.209862/21.047177|5c6e9151154515001982e4dc|DHT11|Aosong/ASAIR|
| SaveDnipro /6941429cfdfe0700083492f4 |52.098348/21.057759|6941429cfdfe0700083492f7|BME280|Bosch Sensortec|
| Przekorna /5d6145ec953683001a6b7fdb |52.125257/21.101173|5d6145ec953683001a6b7fde|BME280|Bosch Sensortec|

Coordinates/instrument identities verified against the frozen local database;
all declare outdoor/fixed exposure. These are four distinct provider stations,
each with one stored temperature instrument. Geographical separation does not
prove independent ownership, firmware or calibration; no cross-platform physical
identity is asserted and no automatic identity merging is performed.

## BMP180 — confirmed documentation, uncertain installation

Bosch-authored [BMP180 datasheet revision2.5, hosted by Oracle](https://www.oracle.com/webfolder/technetwork/tutorials/obe/java/RaspberryPi_I2C/files/BST-BMP180-DS000-09.pdf),
page6 and temperature/pressure calculation section: this is a digital pressure
sensor with integrated temperature measurement used in the pressure calculation.
Documented temperature output resolution is0.1°C. At3.3V/25°C the table gives
typical±0.5°C and bounds−1.5/+1.5°C; over0–65°C typical±1°C and bounds±2°C.
These laboratory part specifications do not establish shielded ambient-air
accuracy at Cybernetyki7. Thermal coupling to its board/enclosure is a plausible
installation concern, not a confirmed diagnosis of this station.

All252 accepted local records have two decimal places; the smallest distinct
observed value difference is0.02°C. Formatting/averaging/firmware processing or
incorrect declared model could explain this mismatch with the reference0.1°C
conversion; the database does not identify which explanation is true. Two
decimal places must not be described as0.01°C calibrated accuracy.

## BME280 — an integrated temperature measurement also needs care

The [official Bosch BME280 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)
describes an internal sensor for humidity/pressure compensation and ambient
temperature estimation. Its table lists0.01°C output resolution; a footnote
explicitly states that PCB temperature and self-heating affect the result.
Thus a BME280 label alone does not establish a better exposed meteorological
installation. The two Warsaw instruments show0.01°C minimum distinct steps in
stored values; this is observable reporting precision, not measured accuracy.

## DHT11 — documentation scope

[Aosong's official DHT11 product page](https://www.aosong.com/en/Products/info.aspx?itemid=2257)
confirms the product family but exposed no numeric specification table. Its
datasheet is offered by inquiry; no request/account was made. Numeric accuracy
and revision-specific resolution therefore remain PARTIALLY_VERIFIED rather
than copying inconsistent third-party specifications. Local readings have two
decimal places but0.1°C minimum distinct steps. Installed manufacturer and model
remain provider declarations, not independently verified evidence.

## Interpretation

All stations can sample a different urban microclimate from the airport. One
short interval cannot distinguish a fixed calibration offset, enclosure heating,
radiation, ventilation or actual site temperature differences. Do not declare a
sensor defective or professionally calibrated, assign TRUSTED, or automatically
change the monitoring cohort from these observations.

---
title: "MODIS MOD11A2: land-surface temperature is not air temperature"
organization: "NASA LP DAAC (product identity and URL); interpretation by Terra Twin LLM workstream"
url: "https://lpdaac.usgs.gov/products/mod11a2v061/"
publication_date: null
licence: "NASA open data; see provider terms"
document_type: "dataset_note"
---

# What MOD11A2 provides

MODIS MOD11A2 Version 6.1 is an 8-day composite land-surface temperature (LST) product at 1 km resolution. LST is an estimate of the temperature of the land surface, often described as a skin temperature. It is not near-surface air temperature.

# Why the distinction matters

Air temperature is measured in the atmosphere above the surface. Land-surface temperature responds to solar heating, surface material, moisture, vegetation, emissivity and atmospheric conditions. The two quantities can differ substantially, especially under strong daytime heating or at night.

A platform field named `mean_land_surface_temperature` must therefore be described as land-surface temperature. It must not be relabelled as air temperature, near-surface air temperature or ambient temperature.

# Appropriate wording

- Correct: "The supplied MODIS land-surface temperature value is ..."
- Correct: "This is a surface skin-temperature estimate, not air temperature."
- Incorrect: "The air temperature at the candidate is ..." when the source is MODIS LST.

# Provenance fields

Dataset name, product version, spatial resolution, temporal compositing, acquisition period, coordinate reference system and processing method must come from stored metadata. If any of those fields is absent, the assistant says it is not available rather than filling it in.

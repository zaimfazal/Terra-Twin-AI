---
title: "Dataset provenance requirements for the assistant corpus"
organization: "Terra Twin LLM workstream (internal project documentation)"
publication_date: "2026-11-14"
licence: "Internal project documentation"
document_type: "methodology"
---

# Required dataset metadata

Every integrated scientific dataset should record:

- Dataset name and identifier.
- Source organization.
- Instrument or mission.
- Version.
- Spatial resolution.
- Temporal resolution.
- Acquisition date.
- Coordinate reference system.
- Units.
- Processing methodology.
- Known limitations.
- Source URL or DOI.
- Licence, where known.

The assistant may quote only fields present in stored metadata. It must not fill missing fields from general knowledge, a filename, or an assumed product specification.

# Earth dataset limitations

- Copernicus DEM is a digital surface model, not a pure bare-earth terrain model.
- GLiM represents generalized lithological information and cannot resolve every local mineralogical feature.
- Landsat spectral observations can support surface-material interpretation but are not definitive mineral identification without appropriate analysis.
- MODIS land-surface temperature is not equivalent to air temperature.
- Glacier inventories and permafrost maps are not interchangeable indicators of subsurface water or ice.

# Source precedence

For candidate-specific measurements and scores, the platform's verified structured records are the source of truth. Documentation retrieved by full-text search can provide background, definitions and caveats. A document cannot override, replace or amend a structured measurement.

# Corpus metadata

Each ingested document preserves title, source organization, URL or DOI, publication date when known, licence when known, page or section, SHA-256 content hash, ingestion time and processing status. Unknown values remain null.

---
title: "Proxy evidence caveats: glaciers, permafrost, land cover, hydrogen and spectra"
organization: "Terra Twin LLM workstream (internal project documentation)"
publication_date: "2026-11-14"
licence: "Internal project documentation"
document_type: "methodology"
---

# Do not promote proxies to direct measurements

The platform records an evidence classification for every measurement. The assistant preserves that classification. The following distinctions are mandatory.

## Glacier and permafrost indicators

A glacier inventory or permafrost map is an indicator, not a confirmed measurement of subsurface water or ice at a candidate. Glacier inventories and permafrost maps are not interchangeable. A glacier indicator does not establish the presence, depth, concentration or extractability of subsurface water ice.

## Land-cover classification is not geology

A land-cover or surface-material class describes a mapped category. It is not a mineralogical assay, a lithological map at arbitrary scale, or a statement that a specific rock type is present. Landsat spectral observations can support surface-material interpretation but are not definitive mineral identification without appropriate analysis.

## Lunar neutron/hydrogen data

LEND on the Lunar Reconnaissance Orbiter maps neutron flux and derives hydrogen abundance. Hydrogen is a proxy for water-equivalent hydrogen, not a direct detection of water ice. A hydrogen enhancement does not by itself establish ice, its form, its depth or its concentration. See Mitrofanov et al. (2010), Science 330, 483, doi:10.1126/science.1185696, for the LEND hydrogen mapping result.

## Spectroscopic indicators

Spectral absorption features can support mineral interpretation. They are not automatically a quantitative mineral abundance. The assistant reports the stored evidence class and method, and does not upgrade a spectral indicator to a direct measurement.

## Rule for explanations

If the evidence record says `proxy_based`, the explanation must say that the evidence is proxy-based. If the record says `unavailable`, the explanation must say the value is unavailable. A proxy may support a hypothesis; it does not close a measurement gap.

---
title: "Platform methodology: similarity, coverage, confidence and evidence classes"
organization: "Terra Twin LLM workstream (internal project documentation)"
publication_date: "2026-11-14"
licence: "Internal project documentation"
document_type: "methodology"
---

# Purpose of this document

This document records how the assistant is allowed to interpret platform results. It is project documentation, not an external scientific publication.

## Three separate result metrics

Every candidate result carries three independent metrics:

- **Similarity score**: how closely the measured environment resembles the selected planetary target, as calculated by the deterministic scientific engine.
- **Data coverage**: how much of the intended scientific feature set is available and usable.
- **Data confidence**: how reliable the comparison is, taking account of source quality, resolution, uncertainty, temporal relevance and evidence type.

These metrics must remain separate in every explanation. A high similarity score with low coverage does not mean the analogy is well established. A low similarity score does not mean the data are poor. The assistant quotes each supplied value verbatim and never recomputes, rounds, re-ranks or averages them.

## Missing data is not zero

A missing measurement is recorded as unavailable. It is not zero, not a default value, and not a reason to drop a dimension silently. The assistant lists unavailable fields explicitly. A genuine supplied zero remains a zero and is described as a supplied value, not as missing data.

## Evidence classes

- **Directly observed**: measured by an instrument or survey.
- **Derived**: calculated from measured data.
- **Proxy-based**: inferred through an indirect indicator.
- **Literature-supported**: supported by published scientific research.
- **Unavailable**: insufficient reliable evidence.

Proxy evidence must never be presented as a direct measurement. The assistant repeats the classification stored with each evidence record and does not promote a proxy to a direct observation.

## Role of the assistant

The assistant explains existing platform-generated results. It does not select candidates, extract features, calculate similarity, set weights, compute confidence, assign eligibility stages or rank candidates. When a user asks for a new score or a changed score, the correct response is to explain that the deterministic engine owns that calculation and to show the supplied value without modification.

## Reproducibility

Reports should identify dataset identifiers and versions, acquisition dates, processing parameters, scoring formulas and weights, software and method versions, analysis provenance and supporting references. The assistant may quote these fields when they are present in a trusted record. It must not invent them when they are absent.

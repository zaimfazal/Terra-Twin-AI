"""Server-side validation of model output against the exact evidence pack.

The model never supplies scores, source URLs, classifications or candidate
identities that are accepted on trust. Everything candidate-specific is
checked against stored records. Rejected claims are removed from the public
response and recorded in the validation report.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from assistant.contracts import (
    AssistantAnswer,
    BackgroundStatement,
    Claim,
    Contradiction,
    DataProvenanceMode,
    EvidenceClassification,
    EvidencePack,
    GenerationMode,
    MatchStatement,
    MissingEvidence,
    ModelDraft,
    SourceReference,
    ValidationReport,
    ValidationStatus,
)
from assistant.ingestion.loaders import scan_untrusted

INSUFFICIENT_EVIDENCE_SENTENCE = "The available evidence does not establish this."

ID_TOKEN_RE = re.compile(r"\b(?:CAND|REPORT|EV|SRC|PACK|FB)-[A-Za-z0-9_-]+\b")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s<>\"')\]]+")
NUMBER_UNIT_RE = re.compile(
    r"(?<![\d.])"
    r"(-?\d+(?:\.\d+)?)"
    r"\s*"
    r"(°\s*C|degC|degrees?\s+Celsius|percent|%|km²|km2|km|m/s|mm|cm|hours?|hrs?|h|K|"
    r"deg(?:rees)?|°|index|m)\b",
    re.IGNORECASE,
)
SCORE_CONTEXT_RE = re.compile(
    r"(?:similarity|score|coverage|confidence)[^.\n;]{0,50}?(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

OVERCLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("perfect_replica", re.compile(r"perfect\s+(replica|analog|counterpart)", re.I)),
    ("safe_landing_claim", re.compile(r"(safe|guaranteed)\s+landing\s+site", re.I)),
    ("proven_reserve", re.compile(r"proven\s+(water\s+)?(reserve|resource)", re.I)),
    ("global_novelty", re.compile(r"(first[- ]ever|world'?s\s+first|globally\s+novel)", re.I)),
    ("proof_language", re.compile(r"\b(proves?|proven|confirms?|guarantees?)\b", re.I)),
    (
        "modis_as_air_temperature",
        re.compile(r"modis.{0,80}(air|ambient)\s+temperature|(air|ambient)\s+temperature.{0,80}modis", re.I),
    ),
    (
        "landcover_as_geology",
        re.compile(r"land[-\s]?cover.{0,80}(is|as)\s+geolog", re.I),
    ),
    (
        "glacier_as_confirmed_water",
        re.compile(
            r"(glacier|permafrost).{0,100}(confirmed|proves?|proof|guarantee).{0,60}"
            r"(subsurface\s+)?(water|ice)",
            re.I,
        ),
    ),
    (
        "lend_as_direct_ice",
        re.compile(r"lend.{0,100}(direct|directly).{0,40}(water|ice)", re.I),
    ),
    (
        "direct_proxy_claim",
        re.compile(r"proxy.{0,60}(directly\s+measured|direct\s+measurement)", re.I),
    ),
)


class ModelOutputError(ValueError):
    """Raised when the model did not return a schema-valid JSON object."""


def parse_model_json(raw: str) -> dict:
    """Extract and parse JSON without executing or trusting surrounding text."""
    if not isinstance(raw, str) or not raw.strip():
        raise ModelOutputError("empty model output")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ModelOutputError("no JSON object found in model output")
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ModelOutputError(f"malformed model JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ModelOutputError("model JSON is not an object")
    return parsed


def parse_draft(raw: str) -> ModelDraft:
    try:
        return ModelDraft.model_validate(parse_model_json(raw))
    except ModelOutputError:
        raise
    except Exception as exc:  # pydantic ValidationError
        raise ModelOutputError(f"model output failed schema validation: {exc}") from exc


def _dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def normalize_unit(unit: str | None) -> str:
    if not unit:
        return "unitless"
    value = unit.strip().lower().replace(" ", "")
    if value in {"°c", "degc", "celsius", "degreecelsius", "degreescelsius"}:
        return "degC"
    if value in {"%", "percent", "percentage"}:
        return "percent"
    if value in {"km²", "km2", "squarekilometres", "squarekilometers"}:
        return "km2"
    if value in {"m", "meter", "meters", "metre", "metres"}:
        return "m"
    if value in {"km", "kilometre", "kilometers", "kilometres"}:
        return "km"
    if value in {"mm", "millimetre", "millimeter", "millimetres", "millimeters"}:
        return "mm"
    if value in {"cm", "centimetre", "centimeter", "centimetres", "centimeters"}:
        return "cm"
    if value in {"m/s", "mps", "metrespersecond", "meterspersecond"}:
        return "m/s"
    if value in {"h", "hr", "hrs", "hour", "hours"}:
        return "h"
    if value in {"k", "kelvin"}:
        return "K"
    if value in {"deg", "degree", "degrees", "°"}:
        return "deg"
    if value in {"index", "unitless"}:
        return "index"
    return value


def _unit_group(match: str) -> str:
    return normalize_unit(match)


class NumericAllowlist:
    def __init__(self) -> None:
        self.by_unit: dict[str, set[Decimal]] = {}
        self.score_values: set[Decimal] = set()
        self.years: set[str] = set()

    def add(self, value: object, unit: str | None = None) -> None:
        number = _dec(value)
        if number is None:
            return
        self.by_unit.setdefault(normalize_unit(unit), set()).add(number)

    def add_score(self, value: object) -> None:
        number = _dec(value)
        if number is None:
            return
        self.score_values.add(number)
        self.by_unit.setdefault("unitless", set()).add(number)

    def add_text(self, text: str | None) -> None:
        if not text:
            return
        for match in NUMBER_UNIT_RE.finditer(text):
            self.add(match.group(1), _unit_group(match.group(2)))
        for year in YEAR_RE.findall(text):
            self.years.add(year)

    def contains(self, value: Decimal, unit: str | None) -> bool:
        group = normalize_unit(unit)
        if value in self.by_unit.get(group, set()):
            return True
        # A temperature in degC may be described with the generic degree unit
        # only if the exact value is also stored with that unit; do not convert.
        return False


def _build_allowlist(pack: EvidencePack) -> NumericAllowlist:
    allow = NumericAllowlist()
    for item in list(pack.evidence) + list(pack.missing_evidence):
        if item.value is not None:
            allow.add(item.value, item.unit)
        allow.add_text(item.spatial_resolution)
        allow.add_text(item.temporal_coverage)
        allow.add_text(item.observed_at)
    for score in pack.scores:
        if score.value is not None:
            allow.add_score(score.value)
        allow.add_text(score.scale)
        allow.add_text(score.value_text)
    for source in pack.dataset_sources:
        allow.add_text(source.spatial_resolution)
        allow.add_text(source.temporal_resolution)
        allow.add_text(source.acquisition_date)
        allow.add_text(source.version)
    for document in pack.document_sources:
        allow.add_text(document.publication_date)
        allow.add_text(document.section)
    if pack.report is not None:
        allow.add_text(pack.report.generated_at)
    return allow


def _build_background_allowlist(pack: EvidencePack) -> NumericAllowlist:
    allow = NumericAllowlist()
    for document in pack.documents:
        allow.add_text(document.snippet)
    for source in pack.document_sources:
        allow.add_text(source.publication_date)
    return allow


def _strip_ids(text: str) -> str:
    return ID_TOKEN_RE.sub(" ", text)


def numeric_mismatches(
    text: str,
    allow: NumericAllowlist,
    *,
    strict_years: bool = True,
) -> list[str]:
    clean = _strip_ids(text)
    problems: list[str] = []
    for match in NUMBER_UNIT_RE.finditer(clean):
        number = _dec(match.group(1))
        unit = _unit_group(match.group(2))
        if number is None:
            continue
        if not allow.contains(number, unit):
            problems.append(
                f"numeric value {match.group(1)} {match.group(2)} is not present "
                "verbatim in the supplied records"
            )
    for match in SCORE_CONTEXT_RE.finditer(clean):
        number = _dec(match.group(1))
        if number is None:
            continue
        if number not in allow.score_values:
            problems.append(
                f"score/coverage/confidence value {match.group(1)} is not a supplied "
                "value (values may not be recalculated or rounded)"
            )
    if strict_years:
        for year in YEAR_RE.findall(clean):
            if year not in allow.years:
                problems.append(f"year {year} is not present in supplied metadata")
    # De-duplicate while preserving order.
    return list(dict.fromkeys(problems))


def _guardrail_flags(text: str) -> list[str]:
    flags: list[str] = []
    for name, pattern in OVERCLAIM_PATTERNS:
        for match in pattern.finditer(text):
            if _match_is_negated(text, match.start(), match.end()):
                continue
            flags.append(name)
            break
    return flags


NEGATION_RE = re.compile(
    r"(?:"
    r"\b(?:does|do|is|are|was|were|can|could|would|should|did)\s+not\s+(?:(?:a|an|the)\s+)?"
    r"|\bnot\s+(?:(?:a|an|the)\s+)?"
    r"|\bnever\s+(?:(?:a|an|the)\s+)?"
    r"|\bcannot\s+(?:(?:a|an|the)\s+)?"
    r"|\bwithout\s+(?:(?:a|an|the)\s+)?"
    r"|\bno\s+(?:evidence|proof|indication|confirmation|sign|direct)\b[^.;]{0,30}"
    r")$",
    re.I,
)


def _is_negated(text: str, start: int) -> bool:
    """True when the matched phrase is explicitly negated just before it.

    Prevents statements such as "does not prove" or "not a perfect replica"
    from being treated as overclaims. It is a narrow, local check; it does not
    attempt general natural-language inference.
    """
    window = text[max(0, start - 48) : start]
    return bool(NEGATION_RE.search(window))


def _match_is_negated(text: str, start: int, end: int) -> bool:
    """Check negation before the match and before an in-match trigger verb.

    Patterns such as "glacier ... proves ... water" start at "glacier", while
    the negation sits before "proves". Scanning word boundaries in the first
    part of the match catches "does not prove" without suppressing a genuine
    claim merely because a later clause contains "not".
    """
    if _is_negated(text, start):
        return True
    limit = min(end, start + 60)
    for boundary in re.finditer(r"\b", text[start:limit]):
        if _is_negated(text, start + boundary.start()):
            return True
    return False


def _proxy_used_as_direct(text: str, evidence: list) -> bool:
    if not any(
        item.evidence_classification == EvidenceClassification.PROXY_BASED
        for item in evidence
    ):
        return False
    for match in re.finditer(
        r"(directly\s+(measure|observe|detect)\w*|direct\s+(measurement|observation|detection))",
        text,
        re.I,
    ):
        if not _is_negated(text, match.start()):
            return True
    return False


def _missing_described_as_zero(text: str, evidence: list) -> bool:
    missing = [item for item in evidence if item.is_missing]
    if not missing:
        return False
    has_real_zero = any(
        item.value is not None and _dec(item.value) == Decimal("0") for item in evidence
    )
    if has_real_zero:
        return False
    for match in re.finditer(r"\b(zero|0(\.0+)?)\b", text, re.I):
        if not _is_negated(text, match.start()):
            return True
    return False


def _sanitize_refs(text: str, pack: EvidencePack) -> tuple[str, list[str], list[str]]:
    allowed_urls = {
        source.url.rstrip(".,;:)")
        for source in list(pack.dataset_sources) + list(pack.document_sources)
        if source.url
    }
    allowed_dois = {
        source.doi.rstrip(".,;)")
        for source in list(pack.dataset_sources) + list(pack.document_sources)
        if source.doi
    }
    bad_urls: list[str] = []
    bad_dois: list[str] = []

    def url_repl(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:)")
        if url in allowed_urls:
            return url
        bad_urls.append(url)
        return "[unverified URL removed]"

    def doi_repl(match: re.Match[str]) -> str:
        doi = match.group(0).rstrip(".,;)")
        if doi in allowed_dois:
            return doi
        bad_dois.append(doi)
        return "[unverified DOI removed]"

    text = URL_RE.sub(url_repl, text)
    text = DOI_RE.sub(doi_repl, text)
    return text, bad_urls, bad_dois


def _derive_classification(evidence: list) -> tuple[EvidenceClassification | None, list]:
    classes = list(dict.fromkeys(item.evidence_classification for item in evidence))
    return (classes[0] if len(classes) == 1 else None), classes


def engine_label_matches(pack: EvidencePack, which: str) -> list[MatchStatement]:
    ids = (
        pack.engine_strong_match_evidence_ids
        if which == "strong"
        else pack.engine_weak_match_evidence_ids
    )
    by_id = {item.evidence_id: item for item in pack.evidence}
    result: list[MatchStatement] = []
    for evidence_id in ids:
        item = by_id.get(evidence_id)
        if item is None:
            continue
        label = "strong-match" if which == "strong" else "weak-match"
        value = item.value_text if item.value_text is not None else item.value
        unit = f" {item.unit}" if item.unit else ""
        result.append(
            MatchStatement(
                statement=(
                    f"The stored report labels {evidence_id} as {label} evidence: "
                    f"{item.feature} = {value}{unit} ({item.evidence_classification.value})."
                ),
                evidence_ids=[evidence_id],
                dimension=item.dimension,
                validation_status=ValidationStatus.VALIDATED,
            )
        )
    return result


def planetary_limitations(pack: EvidencePack) -> list[str]:
    planet = pack.target.planet if pack.target else None
    common = (
        "An Earth site is an analogy, not a replica: planetary gravity, "
        "atmospheric pressure, radiation, vacuum, thermal behaviour, solar "
        "exposure and aeolian processes differ."
    )
    if planet == "Moon":
        return [
            common,
            "The Moon has essentially no atmosphere, about one-sixth of Earth's "
            "surface gravity, no appreciable aeolian transport, and a harsh "
            "vacuum/radiation environment.",
            "Lunar polar illumination and permanently shadowed terrain cannot be "
            "reproduced geometrically at an arbitrary Earth site.",
        ]
    if planet == "Mars":
        return [
            common,
            "Mars has a thin carbon-dioxide-dominated atmosphere, about 38 percent "
            "of Earth's surface gravity, active dust/aeolian processes, and much "
            "less atmospheric radiation shielding.",
            "Liquid water is not stable at the present Martian surface; aqueous "
            "history and present-day ice are different questions.",
        ]
    return [common]


def validate_draft(
    draft: ModelDraft,
    pack: EvidencePack,
    *,
    question: str,
    score_notice: str | None = None,
    candidate_requested: bool | None = None,
) -> AssistantAnswer:
    allow = _build_allowlist(pack)
    background_allow = _build_background_allowlist(pack)
    allowed_evidence = {item.evidence_id: item for item in pack.evidence}
    allowed_missing = {item.evidence_id: item for item in pack.missing_evidence}
    allowed_primary_sources = {s.source_id for s in pack.dataset_sources}
    allowed_doc_sources = {s.source_id for s in pack.document_sources}

    report = ValidationReport(
        schema_valid=True,
        evidence_ids_valid=True,
        sources_valid=True,
        numeric_claims_valid=True,
        score_immutability_valid=True,
    )
    rejected_claims = 0
    overclaims: list[str] = []
    unknown_refs: list[str] = []

    def check_text(
        text: str, *, background: bool = False, evidence: list = ()
    ) -> tuple[list[str], str]:
        notes: list[str] = []
        problems = numeric_mismatches(
            text,
            background_allow if background else allow,
            strict_years=not background,
        )
        if problems:
            report.numeric_claims_valid = False
            report.numeric_mismatches.extend(problems)
            notes.extend(problems)
        sanitized, bad_urls, bad_dois = _sanitize_refs(text, pack)
        for ref in bad_urls + bad_dois:
            unknown_refs.append(ref)
            report.sources_valid = False
            report.errors.append(f"unverified source reference removed: {ref}")
            notes.append(f"unverified source reference removed: {ref}")
        flags = _guardrail_flags(sanitized)
        if evidence and _proxy_used_as_direct(sanitized, evidence):
            flags.append("proxy_presented_as_direct")
        if evidence and _missing_described_as_zero(sanitized, evidence):
            flags.append("missing_described_as_zero")
        if scan_untrusted(sanitized):
            flags.append("untrusted_instruction_in_output")
        if flags:
            overclaims.extend(flags)
            notes.extend(flags)
        return notes, sanitized

    claims: list[Claim] = []
    background: list[BackgroundStatement] = []

    for model_claim in draft.claims:
        text = model_claim.claim.strip()
        if not text:
            continue
        if model_claim.is_background:
            invalid_sources = [
                sid for sid in model_claim.source_ids if sid not in allowed_doc_sources
            ]
            if invalid_sources:
                report.rejected_source_ids.extend(invalid_sources)
                report.sources_valid = False
                report.errors.append(
                    "background claim referenced unknown document source(s): "
                    + ", ".join(invalid_sources)
                )
                rejected_claims += 1
                continue
            if not model_claim.source_ids:
                report.errors.append(
                    "background claim had no stored document source and was rejected"
                )
                rejected_claims += 1
                continue
            notes, sanitized = check_text(text, background=True)
            background.append(
                BackgroundStatement(
                    statement=sanitized,
                    source_ids=list(dict.fromkeys(model_claim.source_ids)),
                )
            )
            if notes:
                # Background may still be shown, but flagged in validation.
                report.errors.extend(f"background claim: {note}" for note in notes)
            continue

        ids = list(dict.fromkeys(model_claim.evidence_ids))
        invalid_ids = [
            eid for eid in ids if eid not in allowed_evidence and eid not in allowed_missing
        ]
        if invalid_ids:
            report.rejected_evidence_ids.extend(invalid_ids)
            report.evidence_ids_valid = False
            report.errors.append(
                "claim referenced evidence IDs absent from this evidence pack: "
                + ", ".join(invalid_ids)
            )
            rejected_claims += 1
            continue
        if not ids:
            report.evidence_ids_valid = False
            report.errors.append("candidate-specific claim had no evidence IDs and was rejected")
            rejected_claims += 1
            continue

        invalid_sources = [
            sid
            for sid in model_claim.source_ids
            if sid not in allowed_primary_sources and sid not in allowed_doc_sources
        ]
        if invalid_sources:
            report.rejected_source_ids.extend(invalid_sources)
            report.sources_valid = False
            report.errors.append(
                "claim referenced source IDs absent from this evidence pack: "
                + ", ".join(invalid_sources)
            )
            rejected_claims += 1
            continue

        evidence = [allowed_evidence[eid] for eid in ids if eid in allowed_evidence]
        evidence += [allowed_missing[eid] for eid in ids if eid in allowed_missing]
        notes, sanitized = check_text(text, evidence=evidence)
        if any("not present verbatim" in note for note in notes) or any(
            "not a supplied value" in note for note in notes
        ):
            rejected_claims += 1
            report.rejected_claim_count += 1
            continue

        classification, classes = _derive_classification(evidence)
        status = ValidationStatus.VALIDATED
        if notes:
            if any("unverified source reference" in note for note in notes):
                status = ValidationStatus.REJECTED_INVALID_SOURCE
            elif any(flag in notes for flag in ("untrusted_instruction_in_output",)):
                status = ValidationStatus.FLAGGED_UNTRUSTED_INSTRUCTION
            else:
                status = ValidationStatus.FLAGGED_OVERCLAIM
        claims.append(
            Claim(
                claim=sanitized,
                evidence_ids=ids,
                evidence_classification=classification,
                evidence_classifications=list(classes),
                validation_status=status,
                validation_notes=notes,
            )
        )

    strong = engine_label_matches(pack, "strong")
    weak = engine_label_matches(pack, "weak")

    def merge_matches(model_matches, base: list[MatchStatement]) -> list[MatchStatement]:
        merged = list(base)
        seen = {tuple(sorted(m.evidence_ids)) for m in base}
        for model_match in model_matches:
            text = model_match.statement.strip()
            if not text:
                continue
            ids = list(dict.fromkeys(model_match.evidence_ids))
            invalid = [
                eid for eid in ids if eid not in allowed_evidence and eid not in allowed_missing
            ]
            if invalid:
                report.rejected_evidence_ids.extend(invalid)
                report.evidence_ids_valid = False
                report.errors.append(
                    "match statement referenced evidence IDs absent from this pack: "
                    + ", ".join(invalid)
                )
                continue
            if not ids:
                report.errors.append("match statement had no evidence IDs and was rejected")
                continue
            key = tuple(sorted(ids))
            if key in seen:
                continue
            notes, sanitized = check_text(
                text, evidence=[allowed_evidence[i] for i in ids if i in allowed_evidence]
            )
            if any("not present verbatim" in note for note in notes):
                continue
            seen.add(key)
            merged.append(
                MatchStatement(
                    statement=sanitized,
                    evidence_ids=ids,
                    dimension=model_match.dimension,
                    validation_status=(
                        ValidationStatus.FLAGGED_OVERCLAIM if notes else ValidationStatus.VALIDATED
                    ),
                    validation_notes=notes,
                )
            )
        return merged

    strong = merge_matches(draft.strong_matches, strong)
    weak = merge_matches(draft.weak_matches, weak)

    contradictions = [
        Contradiction(
            contradiction_id=c.contradiction_id,
            topic=c.topic,
            evidence_ids=c.evidence_ids,
            description=c.description,
            documented_differences=c.documented_differences,
            resolution_status=c.resolution_status,
        )
        for c in pack.contradictions
    ]

    missing = [
        MissingEvidence(
            evidence_id=item.evidence_id,
            dimension=item.dimension,
            feature=item.feature,
            reason=item.missing_reason or item.note,
        )
        for item in pack.missing_evidence
    ]

    # Model contradiction/missing statements are not used to replace stored
    # records. They may add an interpretation only if the stored IDs are valid.
    def validate_supplementary(matches, label: str) -> None:
        for model_match in matches:
            text = model_match.statement.strip()
            if not text:
                continue
            ids = list(dict.fromkeys(model_match.evidence_ids))
            if not ids or any(
                eid not in allowed_evidence and eid not in allowed_missing for eid in ids
            ):
                report.evidence_ids_valid = False
                report.errors.append(
                    f"{label} statement had missing/invalid evidence IDs and was discarded"
                )
                continue
            check_text(text, evidence=[allowed_evidence[i] for i in ids if i in allowed_evidence])

    validate_supplementary(draft.contradictory_evidence, "contradiction")
    validate_supplementary(draft.missing_evidence, "missing-evidence")

    # Candidate identity is server-resolved, never model-trusted.
    candidate_id = pack.candidate.candidate_id if pack.candidate else None
    if draft.earth_candidate_id and draft.earth_candidate_id != candidate_id:
        report.errors.append(
            f"model supplied candidate ID '{draft.earth_candidate_id}' does not match "
            "the evidence pack; it was ignored"
        )
        report.evidence_ids_valid = False
    target_name = pack.target.name if pack.target else None
    if draft.planetary_target and target_name and draft.planetary_target not in {
        target_name,
        pack.target.target_id if pack.target else "",
    }:
        report.errors.append(
            f"model supplied target '{draft.planetary_target}' does not match the "
            "evidence pack; it was ignored"
        )
        report.evidence_ids_valid = False
    if draft.planetary_target and target_name is None:
        report.errors.append("model supplied a planetary target but none is in the evidence pack")
        report.evidence_ids_valid = False

    # Summary: validate numbers, remove unverified links, flag rather than rewrite.
    summary, bad_urls, bad_dois = _sanitize_refs(draft.answer_summary, pack)
    if bad_urls or bad_dois:
        unknown_refs.extend(bad_urls + bad_dois)
        report.sources_valid = False
        for ref in bad_urls + bad_dois:
            report.errors.append(f"unverified source reference removed from summary: {ref}")
    summary_problems = numeric_mismatches(summary, allow)
    if summary_problems:
        report.numeric_claims_valid = False
        report.numeric_mismatches.extend(summary_problems)
    summary_flags = _guardrail_flags(summary)
    if summary_flags:
        overclaims.extend(summary_flags)

    if candidate_requested is None:
        candidate_requested = bool(
            pack.candidate
            or pack.report
            or re.search(r"\b(?:CAND|REPORT)-[A-Za-z0-9_-]+\b", question)
            or any("not found" in note for note in pack.lookup_notes)
            or draft.earth_candidate_id
        )

    insufficient = bool(draft.insufficient_evidence)
    if candidate_requested and pack.candidate is None:
        insufficient = True
        report.errors.append("no stored candidate record matched the request")
    if candidate_requested and not claims:
        insufficient = True
    if pack.candidate is not None and pack.report is None:
        report.errors.append("no stored report was available for this candidate")

    if insufficient:
        if not summary.startswith(INSUFFICIENT_EVIDENCE_SENTENCE):
            summary = f"{INSUFFICIENT_EVIDENCE_SENTENCE} {summary}".strip()
    if pack.data_provenance_mode == DataProvenanceMode.FIXTURE_TEST_ONLY:
        prefix = (
            "TEST-ONLY FIXTURE DATA: these synthetic values are not platform "
            "measurements. "
        )
        if not summary.startswith(prefix):
            summary = prefix + summary

    uncertainties = list(dict.fromkeys(draft.uncertainties))
    uncertainties.extend(pack.lookup_notes)
    if pack.data_provenance_mode == DataProvenanceMode.FIXTURE_TEST_ONLY:
        uncertainties.insert(
            0,
            "All structured values in this response come from synthetic test-only "
            "fixtures, not the scientific engine.",
        )
    if overclaims:
        uncertainties.append(
            "Some statements used overclaiming or proxy-promoting language and are "
            "flagged in the validation record."
        )
    if not report.evidence_ids_valid:
        uncertainties.append(
            "One or more model statements referenced IDs not present in this "
            "evidence pack and were rejected."
        )

    sources: list[SourceReference] = []
    seen_source_ids: set[str] = set()
    for source in pack.dataset_sources:
        if source.source_id in seen_source_ids:
            continue
        seen_source_ids.add(source.source_id)
        sources.append(
            SourceReference(
                source_id=source.source_id,
                title=source.dataset_name,
                organization=source.organization,
                url=source.url,
                doi=source.doi,
                licence=source.licence,
                source_kind="dataset",
                is_fixture=source.is_fixture,
            )
        )
    for source in pack.document_sources:
        if source.source_id in seen_source_ids:
            continue
        seen_source_ids.add(source.source_id)
        sources.append(
            SourceReference(
                source_id=source.source_id,
                title=source.title,
                organization=source.organization,
                url=source.url,
                doi=source.doi,
                page=source.page,
                section=source.section,
                licence=source.licence,
                source_kind="document",
                is_fixture=source.is_fixture,
            )
        )

    report.rejected_claim_count = rejected_claims
    report.overclaim_flags = list(dict.fromkeys(overclaims))
    report.rejected_evidence_ids = list(dict.fromkeys(report.rejected_evidence_ids))
    report.rejected_source_ids = list(dict.fromkeys(report.rejected_source_ids))
    report.numeric_mismatches = list(dict.fromkeys(report.numeric_mismatches))
    report.errors = list(dict.fromkeys(report.errors))

    analogy_limitations = list(
        dict.fromkeys(list(draft.analogy_limitations) + planetary_limitations(pack) + pack.limitations)
    )

    mission_applications = [
        _as_proposal(x) for x in draft.mission_applications if x.strip()
    ]
    suggested_experiments = [
        _as_proposal(x) for x in draft.suggested_experiments if x.strip()
    ]

    return AssistantAnswer(
        question=question,
        answer_summary=summary,
        planetary_target=target_name,
        earth_candidate_id=candidate_id,
        claims=claims,
        strong_matches=strong,
        weak_matches=weak,
        contradictory_evidence=contradictions,
        missing_evidence=missing,
        analogy_limitations=analogy_limitations,
        mission_applications=mission_applications,
        suggested_experiments=suggested_experiments,
        uncertainties=list(dict.fromkeys(uncertainties)),
        sources=sources,
        insufficient_evidence=insufficient,
        background=background,
        supplied_scores=list(pack.scores),
        data_provenance_mode=pack.data_provenance_mode,
        generation_mode=GenerationMode.MODEL,
        validation=report,
        score_integrity_notice=score_notice,
    )


def _as_proposal(value: str) -> str:
    prefix = "Proposed (not a completed observation or platform conclusion): "
    if value.lower().startswith("proposed"):
        return value
    return prefix + value


SCORE_MANIPULATION_VERBS = re.compile(
    r"\b(increase|decrease|change|set|raise|lower|calculate|recalculate|recompute|"
    r"adjust|boost|bump|modify|alter|correct|inflate|deflate)\b",
    re.I,
)
SCORE_TERMS = re.compile(r"\b(score|similarity|confidence|coverage|rank)\b", re.I)
CITATION_FABRICATION_RE = re.compile(
    r"\b(add|invent|fabricate|make\s+up|create)\b.{0,50}\b(citations?|references?|dois?|papers?|sources?)\b",
    re.I,
)


def detect_score_manipulation(question: str) -> str | None:
    if SCORE_MANIPULATION_VERBS.search(question) and SCORE_TERMS.search(question):
        return (
            "Similarity, data coverage and data confidence are supplied by the "
            "deterministic scientific engine. The assistant cannot calculate, change, "
            "recalculate, round or re-rank them; the supplied values are returned unchanged."
        )
    return None


def detect_citation_fabrication(question: str) -> str | None:
    if CITATION_FABRICATION_RE.search(question):
        return (
            "The assistant can cite only source metadata stored with the evidence pack. "
            "It cannot add publications, DOIs, page numbers or URLs that are not in the "
            "verified source records."
        )
    return None

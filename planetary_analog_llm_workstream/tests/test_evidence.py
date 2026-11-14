from __future__ import annotations

from assistant.evidence.assembler import EvidenceAssembler


def test_pack_has_candidate_target_report_and_provenance(assembler: EvidenceAssembler):
    pack = assembler.assemble(
        question="Why is CAND-001 a potential analog for Jezero Crater?",
        candidate_id="CAND-001",
    )
    assert pack.candidate.candidate_id == "CAND-001"
    assert pack.target.name == "Jezero Crater"
    assert pack.report.report_id == "REPORT-001"
    assert pack.mission_profile == "Mars landing and surface exploration"
    assert pack.data_provenance_mode.value == "fixture_test_only"
    assert pack.evidence
    assert pack.missing_evidence
    assert pack.contradictions
    assert pack.dataset_sources
    assert pack.document_sources
    assert pack.limitations[0].startswith("DATA PROVENANCE WARNING")


def test_pack_preserves_contradiction(assembler: EvidenceAssembler):
    pack = assembler.assemble(question="Compare the temperature records.", candidate_id="CAND-001")
    assert len(pack.contradictions) == 1
    contradiction = pack.contradictions[0]
    assert set(contradiction.evidence_ids) == {"EV-C1-004", "EV-C1-006"}
    assert contradiction.resolution_status == "unresolved"
    assert len(contradiction.documented_differences) == 3


def test_pack_marks_unavailable_not_zero(assembler: EvidenceAssembler):
    pack = assembler.assemble(question="What is missing?", candidate_id="CAND-001")
    missing = {e.feature: e for e in pack.missing_evidence}
    assert missing["mineral_abundance"].value is None
    assert missing["subsurface_water_ice"].value is None
    assert missing["mineral_abundance"].evidence_classification.value == "unavailable"
    zero = next(e for e in pack.evidence if e.feature == "mapped_surface_water_extent")
    assert zero.value == 0.0


def test_missing_candidate_is_not_fabricated(assembler: EvidenceAssembler):
    pack = assembler.assemble(
        question="Tell me why candidate UNKNOWN-999 is a good analog for Mars.",
        candidate_id="UNKNOWN-999",
    )
    assert pack.candidate is None
    assert any("not found" in note for note in pack.lookup_notes)
    assert pack.data_provenance_mode.value == "none"
    assert any("candidate-specific claims cannot be supported" in x for x in pack.limitations)


def test_missing_report_is_not_fabricated(assembler: EvidenceAssembler):
    pack = assembler.assemble(question="Explain REPORT-999.", report_id="REPORT-999")
    assert pack.report is None
    assert any("REPORT-999" in note for note in pack.lookup_notes)


def test_structured_records_are_authoritative_for_scores(assembler: EvidenceAssembler):
    pack = assembler.assemble(question="Explain REPORT-001.", report_id="REPORT-001")
    # Scores are copied by reference/value, not derived from evidence.
    assert pack.report.overall_similarity.value_text == "62.4"
    assert pack.report.data_coverage.value_text == "55.0"
    assert pack.report.data_confidence.value_text == "0.48"
    assert all(s.source_record_id == "REPORT-001" for s in pack.scores if s.metric != "dimension_similarity" or True)


def test_multiple_candidate_question_is_explicitly_limited(assembler: EvidenceAssembler):
    pack = assembler.assemble(
        question="Compare CAND-001 and CAND-002 for rover mobility testing."
    )
    assert pack.candidate.candidate_id == "CAND-001"
    assert any("Multiple candidate IDs were mentioned" in n for n in pack.lookup_notes)
    assert all("cross-candidate comparison" in n for n in pack.lookup_notes if "Multiple" in n)


def test_target_can_be_requested_without_changing_scores(assembler: EvidenceAssembler):
    pack = assembler.assemble(
        question="Compare CAND-001 with Shackleton Crater.",
        candidate_id="CAND-001",
        target="Shackleton Crater",
    )
    assert pack.target.name == "Shackleton Crater"
    assert pack.report.target_name == "Jezero Crater"
    assert any("differs from the stored report" in n for n in pack.lookup_notes)
    assert pack.report.overall_similarity.value_text == "62.4"

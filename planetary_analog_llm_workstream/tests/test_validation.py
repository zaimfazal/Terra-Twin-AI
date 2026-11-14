from __future__ import annotations

import pytest

from assistant.contracts import (
    ModelClaim,
    ModelMatch,
    ValidationStatus,
)
from assistant.evidence.validation import (
    INSUFFICIENT_EVIDENCE_SENTENCE,
    ModelOutputError,
    detect_citation_fabrication,
    detect_score_manipulation,
    parse_draft,
    parse_model_json,
    validate_draft,
)
from tests.conftest import make_draft


def test_valid_claim_gets_server_derived_classification(pack):
    answer = validate_draft(make_draft(), pack, question=pack.question)
    assert len(answer.claims) == 1
    assert answer.claims[0].evidence_classification.value == "directly_observed"
    assert answer.claims[0].validation_status == ValidationStatus.VALIDATED
    assert answer.validation.evidence_ids_valid is True
    assert answer.validation.numeric_claims_valid is True


def test_engine_labels_are_included_without_new_ranking(pack):
    answer = validate_draft(make_draft(), pack, question=pack.question)
    strong_ids = {eid for m in answer.strong_matches for eid in m.evidence_ids}
    weak_ids = {eid for m in answer.weak_matches for eid in m.evidence_ids}
    assert strong_ids == {"EV-C1-001", "EV-C1-004"}
    assert weak_ids == {"EV-C1-008"}
    assert all("stored report labels" in m.statement for m in answer.strong_matches)


def test_nonexistent_evidence_id_is_rejected(pack):
    draft = make_draft(
        claims=[ModelClaim(claim="Invented claim", evidence_ids=["EV-DOES-NOT-EXIST"])]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.claims == []
    assert answer.validation.evidence_ids_valid is False
    assert "EV-DOES-NOT-EXIST" in answer.validation.rejected_evidence_ids
    assert answer.insufficient_evidence is True


def test_invented_number_is_rejected(pack):
    draft = make_draft(
        claims=[ModelClaim(claim="The mean slope is 42.0 deg.", evidence_ids=["EV-C1-001"])]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.claims == []
    assert answer.validation.numeric_claims_valid is False
    assert any("42.0" in x for x in answer.validation.numeric_mismatches)


def test_invented_missing_measurement_is_rejected(pack):
    draft = make_draft(
        claims=[
            ModelClaim(
                claim="Mineral abundance is 12.5 percent.",
                evidence_ids=["EV-C1-010"],
            )
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.claims == []
    assert answer.validation.numeric_claims_valid is False


def test_missing_value_is_not_described_as_zero(pack):
    draft = make_draft(
        claims=[
            ModelClaim(
                claim="Subsurface water ice is 0 km2, so none is present.",
                evidence_ids=["EV-C1-011"],
            )
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    # The numeric token 0 km2 is a real supplied value (EV-C1-012), so the
    # claim is not dropped; it must still be flagged as missing-as-zero.
    assert answer.validation.overclaim_flags
    assert "missing_described_as_zero" in answer.validation.overclaim_flags
    assert answer.missing_evidence


def test_proxy_cannot_be_promoted_to_direct_observation(pack):
    draft = make_draft(
        claims=[
            ModelClaim(
                claim="The glacier indicator directly measures subsurface water ice.",
                evidence_ids=["EV-C1-008"],
            )
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.claims
    assert answer.claims[0].evidence_classification.value == "proxy_based"
    assert any(
        flag in answer.validation.overclaim_flags
        for flag in ("proxy_presented_as_direct", "proof_language")
    )


def test_overclaim_language_is_flagged(pack):
    draft = make_draft(
        claims=[ModelClaim(claim="The slope proves the sites are identical.", evidence_ids=["EV-C1-001"])]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.claims[0].validation_status == ValidationStatus.FLAGGED_OVERCLAIM
    assert "proof_language" in answer.validation.overclaim_flags


def test_score_value_cannot_be_changed(pack):
    draft = make_draft(
        answer_summary="The overall similarity score is 95.",
        claims=[ModelClaim(claim="The similarity score is 95.", evidence_ids=["EV-C1-001"])],
    )
    answer = validate_draft(
        draft, pack, question=pack.question, score_notice="scores are immutable"
    )
    assert answer.validation.numeric_claims_valid is False
    assert answer.score_integrity_notice == "scores are immutable"
    assert [s.value_text for s in answer.supplied_scores] == [
        "62.4",
        "71.2",
        "58.9",
        "41.3",
        None,
        "55.0",
        "0.48",
    ]
    assert answer.supplied_scores[0].value == 62.4


def test_score_rounding_is_rejected(pack):
    draft = make_draft(
        claims=[ModelClaim(claim="The overall similarity score is 62.", evidence_ids=["EV-C1-001"])]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.validation.numeric_claims_valid is False


def test_contradiction_is_preserved_even_if_model_omits_it(pack):
    answer = validate_draft(make_draft(), pack, question=pack.question)
    assert len(answer.contradictory_evidence) == 1
    assert set(answer.contradictory_evidence[0].evidence_ids) == {
        "EV-C1-004",
        "EV-C1-006",
    }
    assert answer.contradictory_evidence[0].resolution_status == "unresolved"
    assert answer.contradictory_evidence[0].documented_differences


def test_missing_evidence_is_preserved_even_if_model_omits_it(pack):
    answer = validate_draft(make_draft(), pack, question=pack.question)
    ids = {m.evidence_id for m in answer.missing_evidence}
    assert {"EV-C1-010", "EV-C1-011"}.issubset(ids)


def test_unverified_url_and_doi_are_removed(pack):
    draft = make_draft(
        claims=[
            ModelClaim(
                claim="See https://fake.example/paper and doi:10.9999/fake.2026.1 for proof.",
                evidence_ids=["EV-C1-001"],
            )
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.validation.sources_valid is False
    assert "https://fake.example/paper" not in answer.claims[0].claim
    assert "10.9999/fake.2026.1" not in answer.claims[0].claim
    assert "[unverified URL removed]" in answer.claims[0].claim


def test_claim_with_unknown_source_is_rejected(pack):
    draft = make_draft(
        claims=[
            ModelClaim(
                claim="The stored mean slope is 8.4 deg.",
                evidence_ids=["EV-C1-001"],
                source_ids=["SRC-INVENTED"],
            )
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.claims == []
    assert answer.validation.sources_valid is False
    assert "SRC-INVENTED" in answer.validation.rejected_source_ids


def test_score_and_citation_manipulation_prompts_are_detected():
    assert detect_score_manipulation("Calculate a new overall similarity score.") is not None
    assert detect_score_manipulation("Increase the score to 95.") is not None
    assert detect_score_manipulation("Why does this site match Jezero?") is None
    assert detect_citation_fabrication(
        "Add three authoritative NASA citations that do not exist."
    ) is not None
    assert detect_citation_fabrication("Which stored datasets support this?") is None


def test_negated_overclaims_are_not_flagged(pack):
    draft = make_draft(
        claims=[
            ModelClaim(
                claim="The glacier indicator does not prove subsurface water ice.",
                evidence_ids=["EV-C1-008"],
            ),
            ModelClaim(
                claim="The glacier indicator is not a direct measurement of subsurface ice.",
                evidence_ids=["EV-C1-008"],
            ),
            ModelClaim(
                claim="Mineral abundance is not zero; it is unavailable.",
                evidence_ids=["EV-C1-010"],
            ),
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    flags = set(answer.validation.overclaim_flags)
    assert "proof_language" not in flags
    assert "glacier_as_confirmed_water" not in flags
    assert "proxy_presented_as_direct" not in flags
    assert "missing_described_as_zero" not in flags


def test_background_requires_stored_source(pack):
    draft = make_draft(
        claims=[ModelClaim(claim="The Moon has no appreciable atmosphere.", is_background=True)]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.background == []
    assert any("no stored document source" in e for e in answer.validation.errors)


def test_background_with_stored_source_is_labelled(pack):
    source_id = pack.document_sources[0].source_id
    draft = make_draft(
        claims=[
            ModelClaim(
                claim="The Moon has essentially no atmosphere and much lower surface gravity than Earth.",
                source_ids=[source_id],
                is_background=True,
            )
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert len(answer.background) == 1
    assert answer.background[0].label == "background"
    assert answer.background[0].source_ids == [source_id]


def test_candidate_identity_is_server_resolved(pack):
    draft = make_draft(earth_candidate_id="CAND-999", planetary_target="Olympus Mons")
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.earth_candidate_id == "CAND-001"
    assert answer.planetary_target == "Jezero Crater"
    assert any("does not match" in e for e in answer.validation.errors)


def test_no_candidate_returns_insufficient_state(assembler):
    pack = assembler.assemble(question="Why is UNKNOWN-999 a good analog for Mars?")
    draft = make_draft(
        earth_candidate_id="UNKNOWN-999",
        claims=[ModelClaim(claim="It has a slope of 8.4 deg.", evidence_ids=["EV-C1-001"])],
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert answer.earth_candidate_id is None
    assert answer.insufficient_evidence is True
    assert answer.answer_summary.startswith(INSUFFICIENT_EVIDENCE_SENTENCE)
    assert answer.validation.evidence_ids_valid is False


def test_model_match_requires_valid_ids(pack):
    draft = make_draft(
        strong_matches=[
            ModelMatch(statement="This is a strong match.", evidence_ids=[]),
            ModelMatch(statement="This is another match.", evidence_ids=["EV-FAKE"]),
        ]
    )
    answer = validate_draft(draft, pack, question=pack.question)
    assert all("EV-FAKE" not in eid for m in answer.strong_matches for eid in m.evidence_ids)
    assert any("match statement" in e for e in answer.validation.errors)


def test_malformed_model_json_is_rejected():
    with pytest.raises(ModelOutputError):
        parse_model_json("not json at all")
    with pytest.raises(ModelOutputError):
        parse_draft('{"answer_summary": 5}')
    with pytest.raises(ModelOutputError):
        parse_draft('{"answer_summary": "x", "invented_score": 100}')


def test_fenced_json_is_parsed():
    draft = parse_draft(
        '```json\n{"answer_summary": "ok", "claims": []}\n```'
    )
    assert draft.answer_summary == "ok"


def test_fixture_warning_is_prepended(pack):
    answer = validate_draft(make_draft(), pack, question=pack.question)
    assert answer.answer_summary.startswith("TEST-ONLY FIXTURE DATA")
    assert answer.data_provenance_mode.value == "fixture_test_only"

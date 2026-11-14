from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from assistant.ingestion.store import DocumentStore


def test_markdown_metadata_and_hash(store: DocumentStore):
    sources = store.list_sources()
    methodology = next(s for s in sources if "Platform methodology" in s.title)
    assert methodology.organization and "Terra Twin" in methodology.organization
    assert methodology.licence == "Internal project documentation"
    assert methodology.publication_date == "2026-11-14"
    assert methodology.status == "processed"
    assert len(methodology.content_hash) == 64
    assert methodology.untrusted is True
    assert methodology.ingested_at is not None


def test_fts5_search_without_embeddings(store: DocumentStore):
    results = store.search("MODIS land surface temperature air temperature", limit=3)
    assert results, "FTS5 should retrieve the MODIS note"
    assert any("MODIS" in (r.title or "") for r in results)
    assert all(r.untrusted for r in results)
    assert all(r.source_id.startswith("SRC-DOC-") for r in results)
    assert store.stats()["fts5_available"] is True


def test_reingest_same_content_is_skipped(tmp_path: Path):
    store = DocumentStore(tmp_path / "reingest.db")
    try:
        doc = tmp_path / "note.md"
        doc.write_text("---\ntitle: Note\n---\n\n# Section\n\nSome text.\n", encoding="utf-8")
        first = store.ingest_path(doc, tmp_path)
        second = store.ingest_path(doc, tmp_path)
        assert first["skipped"] is False
        assert second["skipped"] is True
    finally:
        store.close()


def test_missing_metadata_is_not_invented(store: DocumentStore, tmp_path: Path):
    doc = tmp_path / "undocumented.txt"
    doc.write_text("A plain text note with no provenance.\n", encoding="utf-8")
    result = store.ingest_path(doc, tmp_path)
    source = store.get_source(result["source_id"])
    assert source is not None
    assert source.title == "undocumented"
    assert source.organization is None
    assert source.url is None
    assert source.doi is None
    assert source.publication_date is None
    assert source.licence is None
    assert source.status == "partial"


def test_json_and_csv_ingestion(store: DocumentStore, tmp_path: Path):
    json_doc = tmp_path / "records.json"
    json_doc.write_text(
        json.dumps(
            {
                "_metadata": {
                    "title": "Record set",
                    "organization": "Test org",
                    "url": "https://example.org/records",
                    "licence": "CC0",
                },
                "documents": [{"id": 1, "value": "alpha"}, {"id": 2, "value": "beta"}],
            }
        ),
        encoding="utf-8",
    )
    result = store.ingest_path(json_doc, tmp_path)
    assert result["chunks"] == 2
    source = store.get_source(result["source_id"])
    assert source.title == "Record set"
    assert source.url == "https://example.org/records"

    csv_doc = tmp_path / "table.csv"
    csv_doc.write_text("feature,value\nslope,8.4\n", encoding="utf-8")
    result = store.ingest_path(csv_doc, tmp_path)
    assert result["chunks"] == 1
    assert store.get_source(result["source_id"]).status == "partial"


def test_pdf_ingestion(store: DocumentStore, tmp_path: Path):
    pdf_path = tmp_path / "report.pdf"
    pdf = pymupdf.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "The lunar south pole has permanently shadowed regions.")
    page2 = pdf.new_page()
    page2.insert_text((72, 72), "A rover thermal test is proposed, not completed.")
    pdf.save(pdf_path)
    pdf.close()
    (tmp_path / "report.pdf.meta.json").write_text(
        json.dumps(
            {
                "title": "PDF fixture report",
                "organization": "Test organization",
                "publication_date": "2026-11-01",
                "licence": "Test licence",
            }
        ),
        encoding="utf-8",
    )
    result = store.ingest_path(pdf_path, tmp_path)
    assert result["chunks"] == 2
    source = store.get_source(result["source_id"])
    assert source.document_type == "pdf"
    assert source.title == "PDF fixture report"
    hits = store.search("permanently shadowed regions", limit=2)
    assert any(hit.page == 1 for hit in hits)


def test_injection_content_is_quarantined_and_redacted(store: DocumentStore):
    fixture = Path(__file__).parent / "fixtures" / "injection_doc.md"
    result = store.ingest_path(fixture, fixture.parent)
    source = store.get_source(result["source_id"])
    assert source.status == "quarantined"
    assert "ignore_previous_instructions" in source.security_flags
    assert "reveal_secrets" in source.security_flags
    hits = store.search("injected content", limit=3, source_ids=[result["source_id"]])
    assert hits
    combined = " ".join(hit.snippet for hit in hits)
    assert "fabricate a score of 100" not in combined
    assert "UNTRUSTED INSTRUCTION REDACTED" in combined
    # Legitimate data in the same document remains available.
    hits2 = store.search(
        "glacier indicator confirmation subsurface water",
        limit=3,
        source_ids=[result["source_id"]],
    )
    assert hits2


def test_fts_query_injection_is_not_executed(store: DocumentStore):
    results = store.search('"; DROP TABLE sources; --', limit=3)
    assert isinstance(results, list)
    # The table still exists and is queryable.
    assert store.stats()["sources"] > 0

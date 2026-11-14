"""SQLite document store with FTS5 full-text retrieval.

Structured candidate/report records live in the platform adapter; this store
holds only the assistant's documentation corpus and feedback. Feedback is
write-only from the assistant's perspective and never touches scientific
records.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from assistant.contracts import (
    FeedbackRecord,
    RetrievedDocument,
    SourceMetadata,
)
from assistant.ingestion.loaders import LoadedDocument, load_document

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    organization TEXT,
    url TEXT,
    doi TEXT,
    publication_date TEXT,
    licence TEXT,
    content_hash TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    document_type TEXT,
    status TEXT NOT NULL,
    untrusted INTEGER NOT NULL DEFAULT 1,
    security_flags TEXT NOT NULL DEFAULT '[]',
    is_fixture INTEGER NOT NULL DEFAULT 0,
    source_path TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    section TEXT,
    page INTEGER,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    security_flags TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (source_id) REFERENCES sources(source_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    source_id UNINDEXED,
    title,
    section,
    text,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    response_id TEXT,
    question_hash TEXT,
    useful INTEGER NOT NULL,
    factual INTEGER,
    comment TEXT,
    created_at TEXT NOT NULL
);
"""


class FTSUnavailable(RuntimeError):
    pass


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


class DocumentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.fts5_available = self._check_fts5()
        if not self.fts5_available:
            raise FTSUnavailable("SQLite build has no FTS5 support")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def _check_fts5(self) -> bool:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
            self._conn.execute("DROP TABLE IF EXISTS _fts5_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest_path(self, path: str | Path, root: str | Path | None = None) -> dict:
        doc = load_document(path, root)
        return self.ingest_loaded(doc, source_path=str(Path(path)))

    def ingest_directory(self, directory: str | Path) -> dict:
        root = Path(directory)
        if not root.exists():
            return {"ingested": 0, "skipped": 0, "failed": 0, "errors": []}
        results = {"ingested": 0, "skipped": 0, "failed": 0, "errors": []}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.endswith(".meta.json") or path.suffix.lower() not in {
                ".md",
                ".markdown",
                ".txt",
                ".json",
                ".csv",
                ".pdf",
            }:
                continue
            try:
                result = self.ingest_path(path, root)
                results["skipped" if result["skipped"] else "ingested"] += 1
            except Exception as exc:  # noqa: BLE001 - ingestion must not crash the app
                results["failed"] += 1
                results["errors"].append({"path": str(path), "error": str(exc)})
        return results

    def ingest_loaded(self, doc: LoadedDocument, source_path: str | None = None) -> dict:
        existing = self._conn.execute(
            "SELECT content_hash, status FROM sources WHERE source_id = ?", (doc.source_id,)
        ).fetchone()
        if existing and existing["content_hash"] == doc.raw_hash:
            return {"source_id": doc.source_id, "skipped": True, "chunks": 0}

        flags = sorted({flag for chunk in doc.chunks for flag in chunk.security_flags})
        with self._conn:
            self._conn.execute("DELETE FROM chunks_fts WHERE source_id = ?", (doc.source_id,))
            self._conn.execute("DELETE FROM chunks WHERE source_id = ?", (doc.source_id,))
            self._conn.execute(
                """
                INSERT INTO sources (
                    source_id, title, organization, url, doi, publication_date,
                    licence, content_hash, ingested_at, document_type, status,
                    untrusted, security_flags, is_fixture, source_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title=excluded.title,
                    organization=excluded.organization,
                    url=excluded.url,
                    doi=excluded.doi,
                    publication_date=excluded.publication_date,
                    licence=excluded.licence,
                    content_hash=excluded.content_hash,
                    ingested_at=excluded.ingested_at,
                    document_type=excluded.document_type,
                    status=excluded.status,
                    security_flags=excluded.security_flags,
                    is_fixture=excluded.is_fixture,
                    source_path=excluded.source_path
                """,
                (
                    doc.source_id,
                    doc.meta.title or Path(source_path or "document").stem,
                    doc.meta.organization,
                    doc.meta.url,
                    doc.meta.doi,
                    doc.meta.publication_date,
                    doc.meta.licence,
                    doc.raw_hash,
                    doc.ingested_at.isoformat(),
                    doc.meta.document_type,
                    doc.status,
                    json.dumps(flags),
                    int(doc.meta.is_fixture),
                    source_path,
                ),
            )
            for index, chunk in enumerate(doc.chunks):
                chunk_id = f"{doc.source_id}:{index}"
                chunk_flags = json.dumps(chunk.security_flags)
                self._conn.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, source_id, chunk_index, title, section, page,
                        text, content_hash, security_flags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        doc.source_id,
                        index,
                        chunk.title,
                        chunk.section,
                        chunk.page,
                        chunk.text,
                        doc.raw_hash,
                        chunk_flags,
                    ),
                )
                self._conn.execute(
                    "INSERT INTO chunks_fts (chunk_id, source_id, title, section, text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (chunk_id, doc.source_id, chunk.title, chunk.section or "", chunk.text),
                )
        return {
            "source_id": doc.source_id,
            "skipped": False,
            "chunks": len(doc.chunks),
        }

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-]{1,}", query)
        # Deduplicate, cap and quote to avoid FTS5 syntax injection.
        seen: list[str] = []
        for token in tokens:
            low = token.lower()
            if low not in seen:
                seen.append(low)
        seen = seen[:24]
        return " OR ".join(f'"{token}"' for token in seen)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        source_ids: Iterable[str] | None = None,
    ) -> list[RetrievedDocument]:
        match = self._fts_query(query)
        if not match:
            return []
        params: list[object] = [match]
        source_filter = ""
        if source_ids is not None:
            ids = list(source_ids)
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            source_filter = f" AND s.source_id IN ({placeholders})"
            params.extend(ids)
        params.append(max(1, min(limit, 50)))
        sql = f"""
            SELECT
                c.source_id, c.title, c.section, c.page, c.text,
                s.organization, s.url, s.doi, s.publication_date, s.licence,
                s.security_flags, s.is_fixture,
                snippet(chunks_fts, 4, '[', ']', ' ... ', 28) AS snippet,
                bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
            JOIN sources s ON s.source_id = c.source_id
            WHERE chunks_fts MATCH ? {source_filter}
            ORDER BY rank
            LIMIT ?
        """
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            RetrievedDocument(
                source_id=row["source_id"],
                title=row["title"],
                organization=row["organization"],
                url=row["url"],
                doi=row["doi"],
                publication_date=row["publication_date"],
                licence=row["licence"],
                page=row["page"],
                section=row["section"],
                snippet=row["snippet"] or row["text"][:600],
                rank=float(row["rank"]) if row["rank"] is not None else None,
                untrusted=True,
                security_flags=_json_list(row["security_flags"]),
                is_fixture=bool(row["is_fixture"]),
            )
            for row in rows
        ]

    def get_source(self, source_id: str) -> SourceMetadata | None:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if not row:
            return None
        return SourceMetadata(
            source_id=row["source_id"],
            title=row["title"],
            organization=row["organization"],
            url=row["url"],
            doi=row["doi"],
            publication_date=row["publication_date"],
            licence=row["licence"],
            content_hash=row["content_hash"],
            ingested_at=datetime.fromisoformat(row["ingested_at"]),
            document_type=row["document_type"] or "unknown",
            page=None,
            section=None,
            status=row["status"],
            untrusted=True,
            security_flags=_json_list(row["security_flags"]),
            is_fixture=bool(row["is_fixture"]),
        )

    def list_sources(self, *, include_fixture: bool = True) -> list[SourceMetadata]:
        sql = "SELECT source_id FROM sources"
        params: list[object] = []
        if not include_fixture:
            sql += " WHERE is_fixture = 0"
        sql += " ORDER BY title"
        rows = self._conn.execute(sql, params).fetchall()
        return [s for row in rows if (s := self.get_source(row["source_id"]))]

    def stats(self) -> dict:
        sources = self._conn.execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed "
            "FROM sources"
        ).fetchone()
        chunks = self._conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return {
            "sources": sources["n"] if sources else 0,
            "failed_sources": (sources["failed"] or 0) if sources else 0,
            "chunks": chunks["n"] if chunks else 0,
            "fts5_available": self.fts5_available,
        }

    # ------------------------------------------------------------------
    # Feedback (never modifies scientific records)
    # ------------------------------------------------------------------
    def add_feedback(
        self,
        *,
        response_id: str | None,
        question_hash: str | None,
        useful: bool,
        factual: bool | None,
        comment: str | None,
    ) -> FeedbackRecord:
        record = FeedbackRecord(
            feedback_id="FB-" + uuid.uuid4().hex[:12],
            response_id=response_id,
            question_hash=question_hash,
            useful=useful,
            factual=factual,
            comment=comment,
            created_at=datetime.now(timezone.utc),
        )
        with self._conn:
            self._conn.execute(
                "INSERT INTO feedback (feedback_id, response_id, question_hash, useful, "
                "factual, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.feedback_id,
                    record.response_id,
                    record.question_hash,
                    int(record.useful),
                    None if record.factual is None else int(record.factual),
                    record.comment,
                    record.created_at.isoformat(),
                ),
            )
        return record

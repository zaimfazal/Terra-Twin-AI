"""Document loading and untrusted-content sanitisation.

Supported inputs: Markdown, TXT, JSON, CSV and PDF. Metadata is only taken
from front matter, a sidecar ``<file>.meta.json``, embedded JSON metadata or
PDF document metadata. Missing metadata stays ``None``; it is never invented.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:  # PyMuPDF is optional at import time; health reports PDF support.
    import fitz  # type: ignore
except Exception:  # pragma: no cover - depends on optional wheel availability
    fitz = None


SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".csv", ".pdf"}

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_previous_instructions", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)),
    ("disregard_instructions", re.compile(r"disregard\s+(all\s+)?(previous|prior|above|system)\s+instructions", re.I)),
    (
        "reveal_secrets",
        re.compile(
            r"(reveal|print|show|exfiltrate).{0,40}"
            r"(api[_ -]?key|password|access token|credential|system prompt)",
            re.I,
        ),
    ),
    (
        "bypass_validation",
        re.compile(
            r"bypass.{0,40}(evidence|safety|validation)\s+(checks?|rules?|guardrails?|filters?)",
            re.I,
        ),
    ),
    (
        "fabricate_score",
        re.compile(
            r"(fabricate|invent|set|assign|force).{0,40}(score|similarity).{0,20}\d+",
            re.I,
        ),
    ),
    (
        "fabricate_citation",
        re.compile(
            r"(fabricate|invent|make\s+up)\s+(a\s+|an\s+|the\s+)?(citations?|references?|dois?)",
            re.I,
        ),
    ),
    ("role_override", re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.I)),
    ("system_prompt", re.compile(r"system\s+prompt", re.I)),
)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_id_for_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = path.name
    return "SRC-DOC-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]


def scan_untrusted(text: str) -> list[str]:
    flags: list[str] = []
    for name, pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            flags.append(name)
    return flags


def sanitize_untrusted(text: str) -> tuple[str, list[str]]:
    """Remove instruction-like sentences and report why.

    The document remains available as data, but imperative content aimed at
    the assistant is replaced with a visible marker. This is defence in depth:
    the prompt also treats documents as untrusted data.
    """

    flags = scan_untrusted(text)
    if not flags:
        return text, flags

    # Split into sentences while keeping separators simple; mark any sentence
    # that trips a pattern.
    sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    cleaned: list[str] = []
    for sentence in sentences:
        if scan_untrusted(sentence):
            cleaned.append("[UNTRUSTED INSTRUCTION REDACTED BY ASSISTANT]")
        else:
            cleaned.append(sentence)
    return "\n".join(part for part in cleaned if part is not None), flags


@dataclass
class SourceMeta:
    title: str | None = None
    organization: str | None = None
    url: str | None = None
    doi: str | None = None
    publication_date: str | None = None
    licence: str | None = None
    document_type: str | None = None
    is_fixture: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadedChunk:
    title: str
    section: str | None
    page: int | None
    text: str
    security_flags: list[str]


@dataclass
class LoadedDocument:
    path: Path
    source_id: str
    meta: SourceMeta
    chunks: list[LoadedChunk]
    raw_hash: str
    status: str
    ingested_at: datetime
    parser: str


def _read_sidecar(path: Path) -> dict[str, Any]:
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not sidecar.exists():
        # Also accept <stem>.meta.json next to the document.
        sidecar = path.with_name(path.stem + ".meta.json")
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _meta_from_mapping(data: dict[str, Any]) -> SourceMeta:
    # Accept a top-level "_metadata" wrapper or metadata keys directly.
    if isinstance(data.get("_metadata"), dict):
        data = data["_metadata"]
    allowed = {
        "title",
        "organization",
        "url",
        "doi",
        "publication_date",
        "licence",
        "document_type",
        "is_fixture",
    }
    clean = {k: v for k, v in data.items() if k in allowed and v not in ("", None)}
    extra = {k: v for k, v in data.items() if k not in allowed}
    return SourceMeta(**clean, extra=extra)


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for idx in range(1, min(len(lines), 80)):
        if lines[idx].strip() == "---":
            block = "\n".join(lines[1:idx])
            try:
                data = yaml.safe_load(block) or {}
            except yaml.YAMLError:
                return {}, text
            if not isinstance(data, dict):
                return {}, text
            return data, "\n".join(lines[idx + 1 :])
    return {}, text


def _split_markdown(text: str) -> list[tuple[str | None, str]]:
    """Return (section heading path, body) chunks."""
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current: list[str] = []

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if match:
            if current and "\n".join(current).strip():
                sections.append((current_heading, current))
            current_heading = match.group(2).strip()
            current = [line]
        else:
            current.append(line)
    if current and "\n".join(current).strip():
        sections.append((current_heading, current))

    result: list[tuple[str | None, str]] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            result.append((heading, body))
    return result or [(None, text)]


def _split_plain(text: str, target_chars: int = 4000) -> list[tuple[str | None, str]]:
    text = text.strip()
    if len(text) <= target_chars:
        return [(None, text)] if text else []
    parts: list[tuple[str | None, str]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target_chars)
        if end < len(text):
            cut = text.rfind("\n\n", start, end)
            if cut > start + target_chars // 2:
                end = cut
        parts.append((None, text[start:end].strip()))
        start = end
    return [p for p in parts if p[1]]


def _chunk(text: str, section: str | None, page: int | None) -> list[LoadedChunk]:
    sanitized, flags = sanitize_untrusted(text)
    return [
        LoadedChunk(
            title="",
            section=section,
            page=page,
            text=sanitized,
            security_flags=flags,
        )
    ]


def load_document(path: str | Path, root: str | Path | None = None) -> LoadedDocument:
    path = Path(path)
    root = Path(root) if root is not None else path.parent
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"unsupported document type: {suffix}")

    raw = path.read_bytes()
    digest = content_hash(raw)
    sidecar = _read_sidecar(path)
    meta = _meta_from_mapping(sidecar) if sidecar else SourceMeta()
    ingested_at = datetime.now(timezone.utc)
    status = "processed"
    parser = suffix.lstrip(".")

    chunks: list[LoadedChunk] = []

    if suffix in {".md", ".markdown", ".txt"}:
        text = raw.decode("utf-8", errors="replace")
        front, body = _front_matter(text)
        if front:
            fm = _meta_from_mapping(front)
            # Front matter wins only for fields the sidecar did not supply.
            for key in (
                "title",
                "organization",
                "url",
                "doi",
                "publication_date",
                "licence",
                "document_type",
                "is_fixture",
            ):
                if getattr(meta, key) in (None, False, "") and getattr(fm, key) not in (None, False, ""):
                    setattr(meta, key, getattr(fm, key))
        if suffix == ".txt" and not sidecar and not front:
            status = "partial"  # no verified provenance metadata supplied
        for section, body_text in (
            _split_markdown(body) if suffix != ".txt" else _split_plain(body)
        ):
            chunks.extend(_chunk(body_text, section, None))

    elif suffix == ".json":
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict) and "_metadata" in data:
            meta = _meta_from_mapping(data)
            payload = data.get("documents", data.get("content", data))
        else:
            payload = data
        if isinstance(payload, list):
            for index, item in enumerate(payload, start=1):
                text = json.dumps(item, ensure_ascii=False, indent=2)
                chunks.extend(_chunk(text, f"record {index}", None))
        elif isinstance(payload, dict):
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            chunks.extend(_chunk(text, None, None))
        else:
            chunks.extend(_chunk(str(payload), None, None))

    elif suffix == ".csv":
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            chunks.extend(_chunk("", None, None))
        for index, row in enumerate(rows, start=1):
            # Keep row order and headers; never infer scientific meaning from
            # column names.
            body = "\n".join(f"{key}: {value}" for key, value in row.items())
            chunks.extend(_chunk(body, f"row {index}", None))

    elif suffix == ".pdf":
        if fitz is None:
            raise RuntimeError("PDF ingestion requires PyMuPDF (pymupdf)")
        pdf = fitz.open(path)
        pdf_title = (pdf.metadata or {}).get("title") or None
        if not meta.title and pdf_title:
            meta.title = pdf_title
        for page_index, page in enumerate(pdf, start=1):
            page_text = page.get_text("text")
            if page_text.strip():
                chunks.extend(_chunk(page_text, None, page_index))
        pdf.close()
        if not sidecar:
            status = "partial"  # PDF metadata is often incomplete

    if not chunks:
        status = "failed"

    if not meta.title:
        # A filename is a transparent fallback, not invented provenance.
        meta.title = path.stem
        if status == "processed":
            status = "partial"

    if not meta.document_type:
        meta.document_type = parser

    for chunk in chunks:
        chunk.title = meta.title or path.stem

    # Any flagged chunk makes the document's status visible while keeping the
    # sanitized text available for retrieval.
    flags = sorted({flag for chunk in chunks for flag in chunk.security_flags})
    if flags:
        status = "quarantined" if status == "processed" else status

    return LoadedDocument(
        path=path,
        source_id=source_id_for_path(path, root),
        meta=meta,
        chunks=chunks,
        raw_hash=digest,
        status=status,
        ingested_at=ingested_at,
        parser=parser,
    )

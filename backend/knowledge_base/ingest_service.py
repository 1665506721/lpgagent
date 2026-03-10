from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from knowledge_base import BIZ_DOMAIN, PERSIST_DIR, SAFETY_DOMAIN
from knowledge_base.ingest_chunking import split_document
from knowledge_base.models import KnowledgeDocument
from knowledge_base.ocr import OCRService
from knowledge_base.parsers import load_document
from knowledge_base.schemas import IngestResult, VersioningStrategy
from knowledge_base.vector_store import add_ingested_chunks, delete_by_doc_id


logger = logging.getLogger(__name__)
SUPPORTED_DOMAINS = {SAFETY_DOMAIN, BIZ_DOMAIN}
UPLOAD_ROOT = PERSIST_DIR.parent / "kb_uploads"
TEMP_UPLOAD_ROOT = UPLOAD_ROOT / "_tmp"


class IngestError(Exception):
    pass


def _ensure_domain(domain: str) -> str:
    value = str(domain or "").strip().lower()
    if value not in SUPPORTED_DOMAINS:
        raise IngestError(f"Unsupported domain: {domain}")
    return value


def _ensure_strategy(value: str | VersioningStrategy | None) -> str:
    if isinstance(value, VersioningStrategy):
        return value.value
    raw = str(value or VersioningStrategy.REPLACE.value).strip().lower()
    if raw not in {VersioningStrategy.REPLACE.value, VersioningStrategy.KEEP_HISTORY.value}:
        raise IngestError(f"Unsupported versioning strategy: {value}")
    return raw


def _normalize_source(source: str | None, file_name: str) -> str:
    value = str(source or file_name).strip()
    return value[:512] or file_name


def _checksum_for_path(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_doc_id(domain: str, source: str) -> str:
    token = hashlib.sha1(f"{domain}:{source}".encode("utf-8")).hexdigest()[:16]
    return f"doc_{token}"


def _existing_current(domain: str, source: str) -> KnowledgeDocument | None:
    return (
        KnowledgeDocument.objects.filter(domain=domain, source=source, is_current=True)
        .order_by("-version", "-id")
        .first()
    )


def _next_version(existing: KnowledgeDocument | None) -> int:
    return int(existing.version) + 1 if existing else 1


def _managed_storage_path(domain: str, doc_id: str, version: int, file_name: str) -> Path:
    safe_name = Path(file_name).name
    return UPLOAD_ROOT / domain / doc_id / f"v{version}" / safe_name


def _copy_file_to_storage(src_path: Path, storage_path: Path) -> None:
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    if src_path.resolve() == storage_path.resolve():
        return
    shutil.copy2(src_path, storage_path)


def _write_uploaded_file(uploaded_file, storage_path: Path) -> None:
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    with storage_path.open("wb") as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)


def _build_ingest_result(record: KnowledgeDocument, checksum: str, strategy: str, skipped: bool = False) -> IngestResult:
    return IngestResult(
        doc_id=record.doc_id,
        domain=record.domain,
        version=record.version,
        file_name=record.file_name,
        source=record.source,
        doc_type=record.doc_type,
        chunks=record.chunk_count,
        checksum=checksum,
        status=record.status,
        strategy=strategy,
        title=record.title,
        storage_path=record.storage_path,
        skipped=skipped,
        extra_metadata=record.extra_metadata or {},
    )


def _archive_previous_versions(existing: KnowledgeDocument | None, strategy: str) -> None:
    if not existing:
        return
    delete_by_doc_id(existing.domain, existing.doc_id)
    if strategy == VersioningStrategy.REPLACE.value:
        KnowledgeDocument.objects.filter(doc_id=existing.doc_id).delete()
        return
    KnowledgeDocument.objects.filter(doc_id=existing.doc_id, is_current=True).update(
        is_current=False,
        status=KnowledgeDocument.STATUS_SUPERSEDED,
        updated_at=timezone.now(),
    )


def _create_document_record(
    *,
    doc_id: str,
    domain: str,
    source: str,
    file_name: str,
    doc_type: str,
    title: str,
    version: int,
    checksum: str,
    storage_path: Path,
    chunk_count: int,
    extra_metadata: dict | None,
) -> KnowledgeDocument:
    return KnowledgeDocument.objects.create(
        doc_id=doc_id,
        domain=domain,
        source=source,
        file_name=file_name,
        doc_type=doc_type,
        title=title,
        version=version,
        checksum=checksum,
        storage_path=str(storage_path),
        status=KnowledgeDocument.STATUS_ACTIVE,
        is_current=True,
        chunk_count=chunk_count,
        extra_metadata=extra_metadata or {},
    )


def ingest_file(
    file_path: str | Path,
    *,
    domain: str,
    source: str | None = None,
    versioning_strategy: str | VersioningStrategy = VersioningStrategy.REPLACE,
    chunk_size: int = 800,
    overlap: int = 120,
    extra_metadata: dict | None = None,
    ocr_service: OCRService | None = None,
) -> IngestResult:
    path = Path(file_path)
    if not path.exists():
        raise IngestError(f"File not found: {path}")
    domain = _ensure_domain(domain)
    strategy = _ensure_strategy(versioning_strategy)
    normalized_source = _normalize_source(source, path.name)
    existing = _existing_current(domain, normalized_source)
    doc_id = existing.doc_id if existing else _build_doc_id(domain, normalized_source)
    version = _next_version(existing)
    storage_path = _managed_storage_path(domain, doc_id, version, path.name)
    _copy_file_to_storage(path, storage_path)
    checksum = _checksum_for_path(storage_path)

    if existing and existing.checksum == checksum:
        return _build_ingest_result(existing, checksum=checksum, strategy=strategy, skipped=True)

    parsed = load_document(storage_path, source=normalized_source, ocr_service=ocr_service)
    chunks = split_document(parsed, parent_doc_id=doc_id, version=version, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        raise IngestError(f"No valid chunks produced for {path.name}")
    for chunk in chunks:
        chunk.metadata.update(
            {
                "doc_id": doc_id,
                "domain": domain,
                "source": normalized_source,
                "file_name": parsed.file_name,
                "doc_type": parsed.doc_type,
                "title": parsed.title,
                "record_type": "ingested_document",
                "version": version,
                "is_active": True,
                "text": chunk.text,
            }
        )

    with transaction.atomic():
        _archive_previous_versions(existing, strategy)
        add_ingested_chunks(domain, chunks)
        record = _create_document_record(
            doc_id=doc_id,
            domain=domain,
            source=normalized_source,
            file_name=parsed.file_name,
            doc_type=parsed.doc_type,
            title=parsed.title,
            version=version,
            checksum=checksum,
            storage_path=storage_path,
            chunk_count=len(chunks),
            extra_metadata={**(extra_metadata or {}), **(parsed.extra_metadata or {})},
        )
    logger.info("Ingested document doc_id=%s domain=%s version=%s chunks=%s", doc_id, domain, version, len(chunks))
    return _build_ingest_result(record, checksum=checksum, strategy=strategy)


def ingest_uploaded_file(
    uploaded_file,
    *,
    domain: str,
    source: str | None = None,
    versioning_strategy: str | VersioningStrategy = VersioningStrategy.REPLACE,
    chunk_size: int = 800,
    overlap: int = 120,
    extra_metadata: dict | None = None,
    ocr_service: OCRService | None = None,
) -> IngestResult:
    temp_path = TEMP_UPLOAD_ROOT / f"{uuid.uuid4().hex}_{Path(getattr(uploaded_file, 'name', 'uploaded.bin')).name}"
    _write_uploaded_file(uploaded_file, temp_path)
    try:
        return ingest_file(
            temp_path,
            domain=domain,
            source=source or Path(getattr(uploaded_file, "name", "uploaded.bin")).name,
            versioning_strategy=versioning_strategy,
            chunk_size=chunk_size,
            overlap=overlap,
            extra_metadata=extra_metadata,
            ocr_service=ocr_service,
        )
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def batch_ingest_files(file_paths, **kwargs) -> list[IngestResult]:
    return [ingest_file(item, **kwargs) for item in file_paths]


def batch_ingest_uploads(uploaded_files, **kwargs) -> list[IngestResult]:
    return [ingest_uploaded_file(item, **kwargs) for item in uploaded_files]


def delete_document(*, doc_id: str | None = None, source: str | None = None, domain: str | None = None) -> dict:
    if not doc_id and not source:
        raise IngestError("doc_id or source is required")
    query = KnowledgeDocument.objects.all()
    if domain:
        query = query.filter(domain=_ensure_domain(domain))
    if doc_id:
        query = query.filter(doc_id=doc_id)
    if source:
        query = query.filter(source=source)
    records = list(query)
    deleted_vectors = 0
    touched_docs = 0
    seen = set()
    for record in records:
        key = (record.domain, record.doc_id)
        if key in seen:
            continue
        seen.add(key)
        deleted_vectors += delete_by_doc_id(record.domain, record.doc_id)
        touched_docs += 1
    query.update(is_current=False, status=KnowledgeDocument.STATUS_DELETED, updated_at=timezone.now())
    return {"documents": touched_docs, "deleted_vectors": deleted_vectors}


def list_documents(*, domain: str | None = None, include_history: bool = False):
    query = KnowledgeDocument.objects.all().order_by("domain", "source", "-version")
    if domain:
        query = query.filter(domain=_ensure_domain(domain))
    if not include_history:
        query = query.filter(is_current=True)
    return list(query)


def reindex_document(
    *,
    doc_id: str | None = None,
    file_path: str | Path | None = None,
    domain: str | None = None,
    source: str | None = None,
    versioning_strategy: str | VersioningStrategy = VersioningStrategy.KEEP_HISTORY,
    chunk_size: int = 800,
    overlap: int = 120,
) -> IngestResult:
    if doc_id:
        record = (
            KnowledgeDocument.objects.filter(doc_id=doc_id, is_current=True)
            .order_by("-version", "-id")
            .first()
        )
        if not record:
            raise IngestError(f"Document not found: {doc_id}")
        return ingest_file(
            record.storage_path,
            domain=record.domain,
            source=record.source,
            versioning_strategy=versioning_strategy,
            chunk_size=chunk_size,
            overlap=overlap,
        )
    if file_path:
        if not domain:
            raise IngestError("domain is required when reindexing from file")
        return ingest_file(
            file_path,
            domain=domain,
            source=source,
            versioning_strategy=versioning_strategy,
            chunk_size=chunk_size,
            overlap=overlap,
        )
    raise IngestError("doc_id or file_path is required")


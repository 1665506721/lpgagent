from __future__ import annotations

import json

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from knowledge_base.ingest_service import (
    IngestError,
    batch_ingest_files,
    batch_ingest_uploads,
    delete_document,
    ingest_uploaded_file,
    list_documents,
    reindex_document,
)
from knowledge_base.schemas import VersioningStrategy


def _parse_extra_metadata(raw_value):
    if not raw_value:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        return json.loads(raw_value)
    return {}


def _parse_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _record_to_payload(record):
    return {
        "doc_id": record.doc_id,
        "domain": record.domain,
        "source": record.source,
        "file_name": record.file_name,
        "doc_type": record.doc_type,
        "title": record.title,
        "version": record.version,
        "checksum": record.checksum,
        "storage_path": record.storage_path,
        "status": record.status,
        "is_current": record.is_current,
        "chunk_count": record.chunk_count,
        "extra_metadata": record.extra_metadata or {},
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


class IngestView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "file is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = ingest_uploaded_file(
                upload,
                domain=request.data.get("domain"),
                source=request.data.get("source"),
                versioning_strategy=request.data.get("versioning_strategy", VersioningStrategy.REPLACE.value),
                chunk_size=_parse_int(request.data.get("chunk_size"), 800),
                overlap=_parse_int(request.data.get("overlap"), 120),
                extra_metadata=_parse_extra_metadata(request.data.get("extra_metadata")),
            )
        except (IngestError, ValueError, json.JSONDecodeError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.__dict__)


class BatchIngestView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        domain = request.data.get("domain")
        strategy = request.data.get("versioning_strategy", VersioningStrategy.REPLACE.value)
        chunk_size = _parse_int(request.data.get("chunk_size"), 800)
        overlap = _parse_int(request.data.get("overlap"), 120)
        extra_metadata = _parse_extra_metadata(request.data.get("extra_metadata"))
        uploads = request.FILES.getlist("files")
        file_paths = request.data.get("file_paths")
        try:
            if uploads:
                results = batch_ingest_uploads(
                    uploads,
                    domain=domain,
                    versioning_strategy=strategy,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    extra_metadata=extra_metadata,
                )
            else:
                if isinstance(file_paths, str):
                    file_paths = json.loads(file_paths)
                if not file_paths:
                    raise IngestError("files or file_paths is required")
                results = batch_ingest_files(
                    file_paths,
                    domain=domain,
                    versioning_strategy=strategy,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    extra_metadata=extra_metadata,
                )
        except (IngestError, ValueError, json.JSONDecodeError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"items": [item.__dict__ for item in results], "count": len(results)})


class ReindexView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def post(self, request):
        try:
            result = reindex_document(
                doc_id=request.data.get("doc_id"),
                file_path=request.data.get("file_path"),
                domain=request.data.get("domain"),
                source=request.data.get("source"),
                versioning_strategy=request.data.get("versioning_strategy", VersioningStrategy.KEEP_HISTORY.value),
                chunk_size=_parse_int(request.data.get("chunk_size"), 800),
                overlap=_parse_int(request.data.get("overlap"), 120),
            )
        except (IngestError, ValueError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.__dict__)


class DocumentListView(APIView):
    def get(self, request):
        include_history = str(request.query_params.get("include_history", "false")).lower() in {"1", "true", "yes"}
        try:
            records = list_documents(domain=request.query_params.get("domain"), include_history=include_history)
        except IngestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"items": [_record_to_payload(record) for record in records], "count": len(records)})


class DocumentDeleteView(APIView):
    def delete(self, request, doc_id):
        try:
            payload = delete_document(doc_id=doc_id, domain=request.query_params.get("domain"))
        except IngestError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)

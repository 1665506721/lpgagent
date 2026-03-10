import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from knowledge_base.models import KnowledgeDocument
from knowledge_base.schemas import IngestResult


class IngestApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @mock.patch("knowledge_base.views.ingest_uploaded_file")
    def test_ingest_endpoint_accepts_upload(self, mock_ingest):
        mock_ingest.return_value = IngestResult(
            doc_id="doc_1",
            domain="biz",
            version=1,
            file_name="manual.txt",
            source="manual.txt",
            doc_type="txt",
            chunks=1,
            checksum="abc",
            status="ACTIVE",
            strategy="replace",
        )
        upload = SimpleUploadedFile("manual.txt", b"hello", content_type="text/plain")
        response = self.client.post("/api/ingest", data={"file": upload, "domain": "biz"}, format="multipart")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["doc_id"], "doc_1")

    def test_documents_endpoint_lists_current_records(self):
        KnowledgeDocument.objects.create(
            doc_id="doc_1",
            domain="biz",
            source="manual.txt",
            file_name="manual.txt",
            doc_type="txt",
            title="Manual",
            version=1,
            checksum="abc",
            storage_path="/tmp/manual.txt",
            status="ACTIVE",
            is_current=True,
            chunk_count=2,
        )
        response = self.client.get("/api/documents")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["doc_id"], "doc_1")

    @mock.patch("knowledge_base.views.reindex_document")
    def test_reindex_endpoint_returns_result(self, mock_reindex):
        mock_reindex.return_value = IngestResult(
            doc_id="doc_1",
            domain="biz",
            version=2,
            file_name="manual.txt",
            source="manual.txt",
            doc_type="txt",
            chunks=3,
            checksum="def",
            status="ACTIVE",
            strategy="keep_history",
        )
        response = self.client.post(
            "/api/reindex",
            data=json.dumps({"doc_id": "doc_1"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 2)

    @mock.patch("knowledge_base.views.delete_document")
    def test_delete_endpoint_calls_service(self, mock_delete):
        mock_delete.return_value = {"documents": 1, "deleted_vectors": 4}
        response = self.client.delete("/api/documents/doc_1?domain=biz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_vectors"], 4)

import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase
from openpyxl import Workbook

from knowledge_base.ingest_chunking import split_document
from knowledge_base.ingest_service import delete_document, ingest_file
from knowledge_base.models import KnowledgeDocument
from knowledge_base.parsers import load_document
from knowledge_base.schemas import DocumentParseResult, ParsedSection, VersioningStrategy


class ParserAndChunkingTests(SimpleTestCase):
    def test_markdown_parser_preserves_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "guide.md"
            path.write_text("# Overview\n\nParagraph one\n\n## Workflow\n\nParagraph two", encoding="utf-8")
            parsed = load_document(path, source="guide.md")

        self.assertEqual(parsed.doc_type, "markdown")
        self.assertEqual(parsed.title, "Overview")
        self.assertEqual(len(parsed.sections), 2)
        self.assertEqual(parsed.sections[1].section, "Workflow")

    def test_faq_chunking_splits_by_question_answer(self):
        parsed = DocumentParseResult(
            file_path=Path("faq.txt"),
            source="faq.txt",
            file_name="faq.txt",
            doc_type="txt",
            title="FAQ",
            section="FAQ",
            text="Q: How to order\nA: Open the app\n\nQ: When can it arrive\nA: Usually within two hours",
            sections=[
                ParsedSection(
                    text="Q: How to order\nA: Open the app\n\nQ: When can it arrive\nA: Usually within two hours",
                    title="FAQ",
                    section="FAQ",
                )
            ],
        )
        chunks = split_document(parsed, parent_doc_id="doc_1", version=1, chunk_size=200, overlap=20)

        self.assertEqual(len(chunks), 2)
        self.assertIn("Q: How to order", chunks[0].text)
        self.assertIn("A: Usually within two hours", chunks[1].text)

    def test_xlsx_parser_formats_sheet_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Pricing"
            sheet.append(["Type", "Price"])
            sheet.append(["15kg", 120])
            workbook.save(path)
            parsed = load_document(path, source="prices.xlsx")

        self.assertEqual(parsed.doc_type, "xlsx")
        self.assertEqual(len(parsed.sections), 1)
        self.assertIn("Sheet: Pricing", parsed.sections[0].text)
        self.assertIn("Type: 15kg", parsed.sections[0].text)


class IngestServiceTests(TestCase):
    @mock.patch("knowledge_base.ingest_service.add_ingested_chunks", return_value=1)
    @mock.patch("knowledge_base.ingest_service.delete_by_doc_id", return_value=1)
    def test_ingest_keep_history_creates_new_version(self, _mock_delete, _mock_add):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.txt"
            path.write_text("version one", encoding="utf-8")
            first = ingest_file(path, domain="biz", source="manual.txt", versioning_strategy=VersioningStrategy.KEEP_HISTORY)
            path.write_text("version two", encoding="utf-8")
            second = ingest_file(path, domain="biz", source="manual.txt", versioning_strategy=VersioningStrategy.KEEP_HISTORY)

        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        current = KnowledgeDocument.objects.get(doc_id=second.doc_id, version=2)
        old = KnowledgeDocument.objects.get(doc_id=second.doc_id, version=1)
        self.assertTrue(current.is_current)
        self.assertEqual(old.status, KnowledgeDocument.STATUS_SUPERSEDED)
        self.assertFalse(old.is_current)

    @mock.patch("knowledge_base.ingest_service.add_ingested_chunks", return_value=1)
    @mock.patch("knowledge_base.ingest_service.delete_by_doc_id", return_value=2)
    def test_delete_document_marks_rows_deleted(self, _mock_delete, _mock_add):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.txt"
            path.write_text("delete me", encoding="utf-8")
            result = ingest_file(path, domain="biz", source="delete.txt")

        payload = delete_document(doc_id=result.doc_id, domain="biz")
        record = KnowledgeDocument.objects.get(doc_id=result.doc_id)
        self.assertEqual(payload["documents"], 1)
        self.assertEqual(record.status, KnowledgeDocument.STATUS_DELETED)
        self.assertFalse(record.is_current)

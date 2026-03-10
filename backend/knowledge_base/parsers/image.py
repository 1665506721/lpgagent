from __future__ import annotations

from pathlib import Path

from knowledge_base.cleaning import clean_text, clean_title
from knowledge_base.ocr import OCRService
from knowledge_base.parsers.base import BaseDocumentParser
from knowledge_base.schemas import DocumentParseResult, ParsedSection


class ImageParser(BaseDocumentParser):
    supported_extensions = (".png", ".jpg", ".jpeg")

    def parse(self, file_path: Path, source: str, ocr_service: OCRService | None = None) -> DocumentParseResult:
        if ocr_service is None:
            ocr_service = OCRService()
        text = clean_text(ocr_service.extract_text_from_image_path(file_path))
        title = clean_title(file_path.stem)
        sections = [ParsedSection(text=text, title=title, section=title)] if text else []
        return DocumentParseResult(
            file_path=file_path,
            source=source,
            file_name=file_path.name,
            doc_type="image",
            text=text,
            title=title,
            section=title,
            sections=sections,
        )

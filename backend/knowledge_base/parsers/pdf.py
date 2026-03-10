from __future__ import annotations

from pathlib import Path

import fitz

from knowledge_base.cleaning import clean_text, clean_title
from knowledge_base.ocr import OCRService
from knowledge_base.parsers.base import BaseDocumentParser
from knowledge_base.schemas import DocumentParseResult, ParsedSection


class PdfParser(BaseDocumentParser):
    supported_extensions = (".pdf",)

    def parse(self, file_path: Path, source: str, ocr_service: OCRService | None = None) -> DocumentParseResult:
        if ocr_service is None:
            ocr_service = OCRService()
        document = fitz.open(str(file_path))
        sections: list[ParsedSection] = []
        combined_parts: list[str] = []

        for index, page in enumerate(document, start=1):
            text = clean_text(page.get_text("text"))
            if len(text) < 30:
                pix = page.get_pixmap(dpi=200)
                image_bytes = pix.tobytes("png")
                text = clean_text(ocr_service.extract_text_from_bytes(image_bytes))
            if not text:
                continue
            combined_parts.append(text)
            sections.append(
                ParsedSection(
                    text=text,
                    title=clean_title(file_path.stem),
                    section=f"page_{index}",
                    page_num=index,
                )
            )

        full_text = clean_text("\n\n".join(combined_parts))
        return DocumentParseResult(
            file_path=file_path,
            source=source,
            file_name=file_path.name,
            doc_type="pdf",
            text=full_text,
            title=clean_title(file_path.stem),
            section=clean_title(file_path.stem),
            sections=sections,
        )

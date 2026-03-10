from __future__ import annotations

from pathlib import Path

from docx import Document

from knowledge_base.cleaning import clean_text, clean_title
from knowledge_base.ocr import OCRService
from knowledge_base.parsers.base import BaseDocumentParser
from knowledge_base.schemas import DocumentParseResult, ParsedSection


class DocxParser(BaseDocumentParser):
    supported_extensions = (".docx",)

    def parse(self, file_path: Path, source: str, ocr_service: OCRService | None = None) -> DocumentParseResult:
        doc = Document(str(file_path))
        sections: list[ParsedSection] = []
        current_title = ""
        current_lines: list[str] = []
        doc_title = ""

        def flush_section() -> None:
            text = clean_text("\n".join(current_lines))
            if text:
                sections.append(
                    ParsedSection(
                        text=text,
                        title=current_title or doc_title or file_path.stem,
                        section=current_title or doc_title or file_path.stem,
                    )
                )

        for paragraph in doc.paragraphs:
            text = clean_text(paragraph.text)
            if not text:
                continue
            style_name = str(getattr(paragraph.style, "name", "") or "").lower()
            if style_name.startswith("heading"):
                if current_lines:
                    flush_section()
                    current_lines.clear()
                current_title = clean_title(text)
                if not doc_title:
                    doc_title = current_title
                continue
            current_lines.append(text)

        if current_lines:
            flush_section()

        text = clean_text("\n\n".join(section.text for section in sections))
        if not sections and text:
            title = clean_title(file_path.stem)
            sections = [ParsedSection(text=text, title=title, section=title)]
        return DocumentParseResult(
            file_path=file_path,
            source=source,
            file_name=file_path.name,
            doc_type="docx",
            text=text,
            title=doc_title or clean_title(file_path.stem),
            section=doc_title or clean_title(file_path.stem),
            sections=sections,
        )

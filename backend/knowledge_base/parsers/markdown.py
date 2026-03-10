from __future__ import annotations

from pathlib import Path

from knowledge_base.cleaning import clean_text, clean_title
from knowledge_base.ocr import OCRService
from knowledge_base.parsers.base import BaseDocumentParser
from knowledge_base.schemas import DocumentParseResult, ParsedSection


class MarkdownParser(BaseDocumentParser):
    supported_extensions = (".md", ".markdown")

    def parse(self, file_path: Path, source: str, ocr_service: OCRService | None = None) -> DocumentParseResult:
        lines = file_path.read_text(encoding="utf-8").splitlines()
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

        for raw in lines:
            stripped = raw.strip()
            if stripped.startswith("#"):
                if current_lines:
                    flush_section()
                    current_lines.clear()
                heading = clean_title(stripped.lstrip("#").strip())
                if not doc_title:
                    doc_title = heading
                current_title = heading
                continue
            current_lines.append(raw)

        if current_lines:
            flush_section()

        text = clean_text("\n\n".join(section.text for section in sections))
        if not sections and text:
            sections = [ParsedSection(text=text, title=file_path.stem, section=file_path.stem)]
        return DocumentParseResult(
            file_path=file_path,
            source=source,
            file_name=file_path.name,
            doc_type="markdown",
            text=text,
            title=doc_title or clean_title(file_path.stem),
            section=doc_title or clean_title(file_path.stem),
            sections=sections,
        )

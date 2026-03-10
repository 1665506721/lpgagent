from __future__ import annotations

from pathlib import Path

from knowledge_base.ocr import OCRService
from knowledge_base.schemas import DocumentParseResult


_PARSER_BY_SUFFIX = {
    ".pdf": ("knowledge_base.parsers.pdf", "PdfParser"),
    ".docx": ("knowledge_base.parsers.docx", "DocxParser"),
    ".md": ("knowledge_base.parsers.markdown", "MarkdownParser"),
    ".markdown": ("knowledge_base.parsers.markdown", "MarkdownParser"),
    ".txt": ("knowledge_base.parsers.txt", "TxtParser"),
    ".xlsx": ("knowledge_base.parsers.xlsx", "XlsxParser"),
    ".png": ("knowledge_base.parsers.image", "ImageParser"),
    ".jpg": ("knowledge_base.parsers.image", "ImageParser"),
    ".jpeg": ("knowledge_base.parsers.image", "ImageParser"),
}


def _load_parser_for_suffix(suffix: str):
    target = _PARSER_BY_SUFFIX.get(suffix)
    if not target:
        raise ValueError(f"Unsupported file type: {suffix}")
    module_name, class_name = target
    try:
        module = __import__(module_name, fromlist=[class_name])
    except ImportError as exc:
        raise ValueError(f"Parser dependency missing for {suffix}: {exc}") from exc
    parser_cls = getattr(module, class_name)
    return parser_cls()


def load_document(file_path: str | Path, source: str | None = None, ocr_service: OCRService | None = None) -> DocumentParseResult:
    path = Path(file_path)
    parser = _load_parser_for_suffix(path.suffix.lower())
    return parser.parse(path, source=source or path.name, ocr_service=ocr_service)

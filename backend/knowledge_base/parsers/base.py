from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from knowledge_base.ocr import OCRService
from knowledge_base.schemas import DocumentParseResult


class BaseDocumentParser(ABC):
    supported_extensions: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, file_path: Path, source: str, ocr_service: OCRService | None = None) -> DocumentParseResult:
        raise NotImplementedError

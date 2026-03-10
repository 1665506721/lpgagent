from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image

from knowledge_base.cleaning import clean_text


logger = logging.getLogger(__name__)


class BaseOCRProvider(ABC):
    @abstractmethod
    def extract_text(self, image: Image.Image) -> str:
        raise NotImplementedError


class RapidOCRProvider(BaseOCRProvider):
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR()

    def extract_text(self, image: Image.Image) -> str:
        result, _ = self._engine(image)
        if not result:
            return ""
        lines = [str(item[1]).strip() for item in result if len(item) >= 2 and str(item[1]).strip()]
        return clean_text("\n".join(lines))


class OCRService:
    def __init__(self, provider: BaseOCRProvider | None = None):
        self._provider = provider

    def _get_provider(self) -> BaseOCRProvider:
        if self._provider is None:
            self._provider = RapidOCRProvider()
        return self._provider

    def extract_text_from_image_path(self, image_path: str | Path) -> str:
        with Image.open(image_path) as image:
            return self.extract_text_from_image(image)

    def extract_text_from_bytes(self, data: bytes) -> str:
        with Image.open(io.BytesIO(data)) as image:
            return self.extract_text_from_image(image)

    def extract_text_from_image(self, image: Image.Image) -> str:
        try:
            return clean_text(self._get_provider().extract_text(image))
        except Exception as exc:
            logger.warning("OCR extraction failed: %s", exc)
            return ""

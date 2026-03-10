from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class VersioningStrategy(str, Enum):
    REPLACE = "replace"
    KEEP_HISTORY = "keep_history"


@dataclass
class ParsedSection:
    text: str
    title: str = ""
    section: str = ""
    page_num: int | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentParseResult:
    file_path: Path
    source: str
    file_name: str
    doc_type: str
    text: str
    title: str = ""
    section: str = ""
    page_num: int | None = None
    sections: list[ParsedSection] = field(default_factory=list)
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkRecord:
    text: str
    chunk_id: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    doc_id: str
    domain: str
    version: int
    file_name: str
    source: str
    doc_type: str
    chunks: int
    checksum: str
    status: str
    strategy: str
    title: str = ""
    storage_path: str = ""
    skipped: bool = False
    extra_metadata: dict[str, Any] = field(default_factory=dict)

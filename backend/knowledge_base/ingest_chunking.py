from __future__ import annotations

import re
from typing import Iterable

from knowledge_base.cleaning import clean_text, split_paragraphs
from knowledge_base.schemas import ChunkRecord, DocumentParseResult, ParsedSection


FAQ_QUESTION_PREFIXES = ("Q:", "Q\uFF1A", "\u95EE:", "\u95EE\uFF1A")
FAQ_ANSWER_PREFIXES = ("A:", "A\uFF1A", "\u7B54:", "\u7B54\uFF1A")


def _slugify_section(value: str) -> str:
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", str(value or "").strip())
    text = text.strip("-")
    return text[:48] or "section"


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        cleaned = clean_text(text)
        return [cleaned] if cleaned else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        paragraph_len = len(paragraph)
        if current and current_len + paragraph_len + 2 > chunk_size:
            chunks.append("\n\n".join(current))
            if overlap > 0:
                carry: list[str] = []
                carry_len = 0
                for item in reversed(current):
                    item_len = len(item)
                    if carry and carry_len + item_len > overlap:
                        break
                    carry.insert(0, item)
                    carry_len += item_len
                current = carry
                current_len = sum(len(item) for item in current)
            else:
                current = []
                current_len = 0
        current.append(paragraph)
        current_len += paragraph_len + 2

    if current:
        chunks.append("\n\n".join(current))
    return [clean_text(chunk) for chunk in chunks if clean_text(chunk)]


def _iter_faq_pairs(text: str) -> Iterable[tuple[str, str]]:
    question = ""
    answer_lines: list[str] = []
    for raw in clean_text(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(FAQ_QUESTION_PREFIXES):
            if question and answer_lines:
                yield question, clean_text("\n".join(answer_lines))
            question = re.sub(r"^(Q:|Q\uFF1A|\u95EE:|\u95EE\uFF1A)", "", line).strip()
            answer_lines = []
            continue
        if line.startswith(FAQ_ANSWER_PREFIXES):
            answer_lines.append(re.sub(r"^(A:|A\uFF1A|\u7B54:|\u7B54\uFF1A)", "", line).strip())
            continue
        if question:
            answer_lines.append(line)
    if question and answer_lines:
        yield question, clean_text("\n".join(answer_lines))


def _looks_like_faq(parsed_doc: DocumentParseResult) -> bool:
    source = "\n".join(section.text for section in parsed_doc.sections) or parsed_doc.text
    hit_count = 0
    for prefix in FAQ_QUESTION_PREFIXES:
        hit_count += source.count(prefix)
    return "faq" in parsed_doc.file_name.lower() or hit_count >= 2


def _has_heading_structure(parsed_doc: DocumentParseResult) -> bool:
    unique_sections = {section.section for section in parsed_doc.sections if section.section}
    return len(unique_sections) >= 2


def _build_chunk(
    text: str,
    parent_doc_id: str,
    chunk_index: int,
    parsed_doc: DocumentParseResult,
    version: int,
    title: str = "",
    section: str = "",
    page_num: int | None = None,
    extra_metadata: dict | None = None,
) -> ChunkRecord:
    chunk_id = f"{parent_doc_id}::chunk::{chunk_index}::{_slugify_section(section or title or parsed_doc.file_name)}"
    metadata = {
        "parent_doc_id": parent_doc_id,
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "source": parsed_doc.source,
        "file_name": parsed_doc.file_name,
        "doc_type": parsed_doc.doc_type,
        "title": title or parsed_doc.title,
        "section": section or parsed_doc.section,
        "page_num": page_num,
        "version": version,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ChunkRecord(text=clean_text(text), chunk_id=chunk_id, chunk_index=chunk_index, metadata=metadata)


def split_document(
    parsed_doc: DocumentParseResult,
    parent_doc_id: str,
    version: int,
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    chunk_index = 0

    if _looks_like_faq(parsed_doc):
        sections = parsed_doc.sections or [ParsedSection(text=parsed_doc.text, title=parsed_doc.title, section=parsed_doc.section)]
        for section in sections:
            for question, answer in _iter_faq_pairs(section.text):
                chunks.append(
                    _build_chunk(
                        text=f"Q: {question}\nA: {answer}",
                        parent_doc_id=parent_doc_id,
                        chunk_index=chunk_index,
                        parsed_doc=parsed_doc,
                        version=version,
                        title=section.title or parsed_doc.title,
                        section=section.section or parsed_doc.section,
                        page_num=section.page_num,
                        extra_metadata=section.extra_metadata,
                    )
                )
                chunk_index += 1
        if chunks:
            return chunks

    if _has_heading_structure(parsed_doc):
        for section in parsed_doc.sections:
            section_chunks = _split_long_text(section.text, chunk_size=chunk_size, overlap=overlap)
            for part in section_chunks:
                chunks.append(
                    _build_chunk(
                        text=part,
                        parent_doc_id=parent_doc_id,
                        chunk_index=chunk_index,
                        parsed_doc=parsed_doc,
                        version=version,
                        title=section.title or parsed_doc.title,
                        section=section.section or parsed_doc.section,
                        page_num=section.page_num,
                        extra_metadata=section.extra_metadata,
                    )
                )
                chunk_index += 1
        if chunks:
            return chunks

    generic_sections = parsed_doc.sections or [
        ParsedSection(
            text=parsed_doc.text,
            title=parsed_doc.title,
            section=parsed_doc.section,
            page_num=parsed_doc.page_num,
            extra_metadata=parsed_doc.extra_metadata,
        )
    ]
    for section in generic_sections:
        for part in _split_long_text(section.text, chunk_size=chunk_size, overlap=overlap):
            chunks.append(
                _build_chunk(
                    text=part,
                    parent_doc_id=parent_doc_id,
                    chunk_index=chunk_index,
                    parsed_doc=parsed_doc,
                    version=version,
                    title=section.title or parsed_doc.title,
                    section=section.section or parsed_doc.section,
                    page_num=section.page_num,
                    extra_metadata=section.extra_metadata,
                )
            )
            chunk_index += 1
    return chunks

from __future__ import annotations

import re


_BROKEN_CHARS = {
    "\x00": "",
    "\ufeff": "",
}


def clean_text(text: str) -> str:
    value = str(text or "")
    for src, target in _BROKEN_CHARS.items():
        value = value.replace(src, target)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def clean_title(text: str) -> str:
    value = clean_text(text)
    value = value.replace("#", "").strip()
    return value[:255]


def split_paragraphs(text: str) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    return [part.strip() for part in cleaned.split("\n\n") if part.strip()]


def format_table_row(headers: list[str], values: list[object]) -> str:
    parts = []
    for index, value in enumerate(values):
        if value in (None, ""):
            continue
        header = ""
        if index < len(headers):
            header = str(headers[index] or "").strip()
        if header:
            parts.append(f"{header}: {value}")
        else:
            parts.append(str(value))
    return " | ".join(parts).strip()

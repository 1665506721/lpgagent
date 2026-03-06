import re


def _normalize_line(text):
    value = str(text or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _split_long_text(text, max_chars):
    value = _normalize_line(text)
    if not value:
        return []
    if len(value) <= max_chars:
        return [value]
    parts = []
    start = 0
    while start < len(value):
        end = min(len(value), start + max_chars)
        parts.append(value[start:end].strip())
        start = end
    return [item for item in parts if item]


def _collect_units(doc, max_chars):
    primary = list(doc.get("content_bullets", []) or [])
    secondary = list(doc.get("extra_bullets", []) or [])
    aliases = list(doc.get("aliases", []) or [])
    units = []
    for raw in primary + secondary:
        line = _normalize_line(raw)
        if not line:
            continue
        units.extend(_split_long_text(line, max_chars=max_chars))
    for raw in aliases:
        line = _normalize_line(raw)
        if line:
            units.append(f"用户问法：{line}")
    return units


def chunk_document(doc, target_chars=260, max_chars=420, overlap_chars=60):
    # 按中文字符窗切片，优先保留条目语义，并在 chunk 间做短重叠。
    units = _collect_units(doc, max_chars=max_chars)
    if not units:
        return []

    chunks = []
    current = []
    current_len = 0

    for unit in units:
        size = len(unit)
        if not current:
            current = [unit]
            current_len = size
            continue
        if current_len + 1 + size <= max_chars:
            current.append(unit)
            current_len += 1 + size
            continue

        if current:
            chunks.append(list(current))

        overlap = []
        overlap_len = 0
        for item in reversed(current):
            add = len(item) + (1 if overlap else 0)
            if overlap and overlap_len + add > overlap_chars:
                break
            overlap.insert(0, item)
            overlap_len += add

        current = overlap + [unit]
        current_len = sum(len(item) for item in current) + max(0, len(current) - 1)

    if current:
        chunks.append(list(current))

    if len(chunks) <= 1:
        return chunks

    merged = []
    for part in chunks:
        part_len = sum(len(item) for item in part)
        if merged:
            prev_len = sum(len(item) for item in merged[-1])
            if part_len < int(target_chars * 0.55) and prev_len + part_len <= max_chars + int(overlap_chars * 0.5):
                merged[-1].extend(part)
                continue
        merged.append(part)
    return merged

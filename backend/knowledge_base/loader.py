import re
from pathlib import Path

from knowledge_base import BIZ_DOMAIN, BIZ_DOCS_DIR, SAFETY_DOMAIN, SAFETY_DOCS_DIR


SECTION_NAMES = {"content", "do_not", "exceptions", "aliases", "intent_tags"}


def _parse_list(value):
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _zh_ratio(text):
    value = str(text or "")
    if not value:
        return 0.0
    zh_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    return zh_count / max(1, len(value))


def _is_low_quality_doc(title, bullets):
    merged = " ".join([str(title or "")] + [str(item or "") for item in bullets])
    if not merged.strip():
        return True
    # 中文注释：默认索引中文语料，过滤英文模板文档与噪声。
    return _zh_ratio(merged) < 0.18


def _load_markdown(file_path, domain):
    lines = file_path.read_text(encoding="utf-8").splitlines()
    title = ""
    tags = []
    topic = ""
    risk_level = ""
    policy_type = ""
    policy_level = ""
    source = ""
    updated_at = ""
    content_bullets = []
    extra_bullets = []
    aliases = []
    intent_tags = []
    section = ""

    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        if text.startswith("# "):
            if not title:
                title = text[2:].strip()
            section = ""
            continue
        if ":" in text and not text.startswith("-"):
            key, value = text.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in SECTION_NAMES:
                section = key
                continue
            if key == "title":
                title = value
                section = ""
                continue
            if key == "tags":
                tags = _parse_list(value)
                section = ""
                continue
            if key == "topic":
                topic = value
                section = ""
                continue
            if key == "risk_level":
                risk_level = value
                section = ""
                continue
            if key == "policy_type":
                policy_type = value
                section = ""
                continue
            if key == "policy_level":
                policy_level = value
                section = ""
                continue
            if key == "source":
                source = value
                section = ""
                continue
            if key == "updated_at":
                updated_at = value
                section = ""
                continue

        if text.startswith("-"):
            item = text.lstrip("-").strip()
            if not item:
                continue
            if section == "content":
                content_bullets.append(item)
            elif section == "aliases":
                aliases.append(item)
            elif section == "intent_tags":
                intent_tags.append(item)
            else:
                extra_bullets.append(item)
            continue

        if section == "content":
            content_bullets.append(text)
        elif section == "aliases":
            aliases.extend(_parse_list(text))
        elif section == "intent_tags":
            intent_tags.extend(_parse_list(text))
        elif section in {"do_not", "exceptions"}:
            extra_bullets.append(text)

    if not title:
        title = file_path.stem.replace("_", " ").strip()
    if not content_bullets:
        return None
    # 中文注释：V2 知识库要求显式 topic，避免旧模板文档误入索引。
    if not topic:
        return None
    if _is_low_quality_doc(title, content_bullets + aliases):
        return None

    doc_id = file_path.stem
    meta = {
        "source": source,
        "topic": topic,
        "updated_at": updated_at,
        "policy_level": policy_level,
    }
    if domain == SAFETY_DOMAIN:
        meta["risk_level"] = risk_level
    if domain == BIZ_DOMAIN:
        meta["policy_type"] = policy_type

    return {
        "doc_id": doc_id,
        "title": title,
        "tags": tags,
        "content_bullets": content_bullets,
        "extra_bullets": extra_bullets,
        "aliases": aliases,
        "intent_tags": list(dict.fromkeys(intent_tags)),
        "meta": meta,
    }


def load_markdown_docs(domain):
    if domain == SAFETY_DOMAIN:
        docs_dir = SAFETY_DOCS_DIR
    elif domain == BIZ_DOMAIN:
        docs_dir = BIZ_DOCS_DIR
    else:
        raise ValueError(f"Unsupported domain: {domain}")

    documents = []
    for file_path in sorted(Path(docs_dir).glob("*.md")):
        doc = _load_markdown(file_path, domain)
        if doc:
            documents.append(doc)
    return documents

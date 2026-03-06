import re

from knowledge_base import BIZ_DOMAIN, SAFETY_DOMAIN
from knowledge_base.vector_store import retrieve_knowledge


def _tokenize(text):
    value = str(text or "").lower()
    words = [item for item in re.split(r"[\s,，。；;、:：|/]+", value) if item]
    return [item for item in words if len(item) >= 2]


def _topic_hint(query):
    value = str(query or "")
    if any(key in value for key in ["价格", "报价", "多少钱", "收费", "涨价"]):
        return "price"
    if any(key in value for key in ["发票", "开票", "税号", "抬头"]):
        return "invoice"
    if any(key in value for key in ["年检", "检验", "复检", "到期"]):
        return "inspection"
    if any(key in value for key in ["漏气", "泄漏", "异味", "报警", "应急"]):
        return "safety_leak"
    if any(key in value for key in ["退", "退款", "售后"]):
        return "refund"
    return ""


def _rerank_hits(query, hits, topic=""):
    terms = _tokenize(query)
    desired_topic = topic or _topic_hint(query)
    ranked = []
    for hit in hits or []:
        score = float(hit.get("score") or 0.0)
        text = " ".join(
            [
                str(hit.get("title") or ""),
                " ".join(hit.get("bullets") or []),
                " ".join(hit.get("tags") or []),
                " ".join(hit.get("aliases") or []),
                " ".join(hit.get("intent_tags") or []),
                str((hit.get("meta") or {}).get("topic") or ""),
            ]
        ).lower()
        lexical_bonus = 0.0
        if terms:
            matched = sum(1 for item in terms if item in text)
            lexical_bonus += min(0.2, 0.04 * matched)
        meta_topic = str((hit.get("meta") or {}).get("topic") or "").strip().lower()
        if desired_topic and desired_topic == meta_topic:
            lexical_bonus += 0.25
        intent_tags = [str(item).lower() for item in (hit.get("intent_tags") or [])]
        if desired_topic and desired_topic in intent_tags:
            lexical_bonus += 0.15
        hit["score"] = round(score + lexical_bonus, 3)
        ranked.append(hit)
    ranked.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return ranked


def search_safety(query, top_k=4):
    if not query:
        return []
    fetch_k = max(4, int(top_k or 4) * 3)
    hits = retrieve_knowledge(SAFETY_DOMAIN, query, top_k=fetch_k)
    ranked = _rerank_hits(query, hits, topic="safety_leak")
    return ranked[: max(1, int(top_k or 4))]


def search_biz(query, top_k=4):
    if not query:
        return []
    fetch_k = max(4, int(top_k or 4) * 3)
    hits = retrieve_knowledge(BIZ_DOMAIN, query, top_k=fetch_k)
    ranked = _rerank_hits(query, hits, topic="")
    return ranked[: max(1, int(top_k or 4))]


def retrieve_by_domain(domain, query, top_k=4):
    if not query:
        return []
    fetch_k = max(4, int(top_k or 4) * 3)
    hits = retrieve_knowledge(domain, query, top_k=fetch_k)
    ranked = _rerank_hits(query, hits, topic="")
    return ranked[: max(1, int(top_k or 4))]

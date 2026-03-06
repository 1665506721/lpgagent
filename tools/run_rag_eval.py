import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from knowledge_base.retriever import retrieve_by_domain


def load_cases(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def score_case(case, top_k=6):
    domain = case.get("domain") or "biz"
    query = case.get("query") or ""
    topic = str(case.get("expect_topic") or "")
    keywords = [str(item) for item in (case.get("expect_keywords") or [])]
    hits = retrieve_by_domain(domain, query, top_k=top_k)
    top1 = hits[0] if hits else {}
    top1_meta_topic = str((top1.get("meta") or {}).get("topic") or "")
    top1_ok = bool(topic and top1_meta_topic == topic)
    keyword_hit = False
    for hit in hits[:top_k]:
        bullets = " ".join(hit.get("bullets") or [])
        text = " ".join([hit.get("title") or "", bullets])
        if keywords and all(word in text for word in keywords[:2]):
            keyword_hit = True
            break
    reciprocal_rank = 0.0
    for idx, hit in enumerate(hits[:top_k], start=1):
        meta_topic = str((hit.get("meta") or {}).get("topic") or "")
        if topic and meta_topic == topic:
            reciprocal_rank = 1.0 / idx
            break
    return {
        "id": case.get("id"),
        "query": query,
        "domain": domain,
        "expect_topic": topic,
        "top1_topic": top1_meta_topic,
        "top1_ok": top1_ok,
        "keyword_hit": keyword_hit,
        "mrr_component": reciprocal_rank,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="spec/rag_eval_cases_zh.jsonl")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    results = [score_case(case, top_k=args.top_k) for case in cases]
    total = len(results) or 1
    top1_rate = sum(1 for item in results if item["top1_ok"]) / total
    keyword_rate = sum(1 for item in results if item["keyword_hit"]) / total
    mrr = sum(item["mrr_component"] for item in results) / total
    summary = {
        "total": len(results),
        "top1_hit_rate": round(top1_rate, 4),
        "keyword_hit_rate": round(keyword_rate, 4),
        "mrr": round(mrr, 4),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.out_json:
        payload = {"summary": summary, "results": results}
        Path(args.out_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

import math
import os
import sys
from functools import lru_cache

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMA_TELEMETRY", "false")

import chromadb
from chromadb.api.types import Documents, Embeddings

from knowledge_base import BIZ_DOMAIN, PERSIST_DIR, SAFETY_DOMAIN
from knowledge_base.chunking import chunk_document
from knowledge_base.loader import load_markdown_docs


try:
    import posthog

    def _safe_capture(*args, **kwargs):
        return None

    posthog.capture = _safe_capture
except Exception:
    pass


COLLECTIONS = {
    SAFETY_DOMAIN: "safety_kb",
    BIZ_DOMAIN: "biz_kb",
}
LEGACY_RECORD_TYPE = "legacy_markdown"
INGESTED_RECORD_TYPE = "ingested_document"


class SimpleEmbeddingFunction:
    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed(text) for text in input]

    def _embed(self, text):
        dims = 24
        buckets = [0.0] * dims
        for index, char in enumerate(text or ""):
            bucket = index % dims
            buckets[bucket] += ord(char)
        norm = math.sqrt(sum(value * value for value in buckets)) or 1.0
        return [value / norm for value in buckets]


class OllamaEmbeddingFunction:
    def __init__(self, embedder):
        self._embedder = embedder

    def __call__(self, input: Documents) -> Embeddings:
        return self._embedder.embed_documents(list(input))


class SentenceTransformerEmbeddingFunction:
    def __init__(self, model_name, device="cpu"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device=device)

    def __call__(self, input: Documents) -> Embeddings:
        vectors = self._model.encode(
            list(input),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


class BGEM3EmbeddingFunction:
    def __init__(self, model_name, device="cpu"):
        from FlagEmbedding import BGEM3FlagModel

        use_fp16 = str(device or "").lower().startswith("cuda")
        self._model = BGEM3FlagModel(model_name, use_fp16=use_fp16)

    def __call__(self, input: Documents) -> Embeddings:
        result = self._model.encode(list(input), batch_size=16, max_length=8192)
        vectors = result.get("dense_vecs")
        if vectors is None:
            vectors = []
        return [list(map(float, vec)) for vec in vectors]


def _embed_provider_config():
    provider = (os.getenv("KB_EMBED_PROVIDER") or "").strip().upper()
    model = (os.getenv("KB_EMBED_MODEL") or "").strip()
    device = (os.getenv("KB_EMBED_DEVICE") or "cpu").strip()
    legacy_ollama_model = (os.getenv("OLLAMA_EMBED_MODEL") or "").strip()
    if not provider:
        if legacy_ollama_model:
            provider = "OLLAMA"
            model = legacy_ollama_model
        else:
            provider = "LOCAL_BGE_M3"
    if not model:
        if provider == "LOCAL_BGE_M3":
            model = "BAAI/bge-m3"
        elif provider == "OLLAMA":
            model = legacy_ollama_model or "bge-m3"
    return {"provider": provider, "model": model, "device": device}


@lru_cache(maxsize=4)
def _build_embedding_function(provider, model, device):
    if provider == "OLLAMA":
        try:
            from langchain_ollama import OllamaEmbeddings

            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            fn = OllamaEmbeddingFunction(OllamaEmbeddings(base_url=base_url, model=model))
            setattr(fn, "_actual_provider", "OLLAMA")
            return fn
        except Exception:
            fn = SimpleEmbeddingFunction()
            setattr(fn, "_actual_provider", "SIMPLE_FALLBACK")
            return fn

    if provider == "LOCAL_BGE_M3":
        try:
            fn = BGEM3EmbeddingFunction(model_name=model, device=device)
            setattr(fn, "_actual_provider", "LOCAL_BGE_M3_FLAG")
            return fn
        except Exception:
            try:
                fn = SentenceTransformerEmbeddingFunction(model_name=model, device=device)
                setattr(fn, "_actual_provider", "LOCAL_BGE_M3_ST")
                return fn
            except Exception:
                try:
                    fn = SentenceTransformerEmbeddingFunction(
                        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                        device=device,
                    )
                    setattr(fn, "_actual_provider", "LOCAL_ST_FALLBACK")
                    return fn
                except Exception:
                    fn = SimpleEmbeddingFunction()
                    setattr(fn, "_actual_provider", "SIMPLE_FALLBACK")
                    return fn

    fn = SimpleEmbeddingFunction()
    setattr(fn, "_actual_provider", "SIMPLE_FALLBACK")
    return fn


def _get_embedding_function():
    if "test" in sys.argv:
        fn = SimpleEmbeddingFunction()
        setattr(fn, "_actual_provider", "TEST_SIMPLE")
        return fn
    cfg = _embed_provider_config()
    return _build_embedding_function(cfg["provider"], cfg["model"], cfg["device"])


def _embedding_meta():
    cfg = _embed_provider_config()
    fn = _get_embedding_function()
    return {
        "provider": cfg["provider"],
        "actual_provider": getattr(fn, "_actual_provider", cfg["provider"]),
        "model": cfg["model"],
        "device": cfg["device"],
    }


def _get_collection(client, domain, embedding_function):
    collection_name = COLLECTIONS.get(domain)
    if not collection_name:
        raise ValueError(f"Unsupported domain: {domain}")
    return client.get_or_create_collection(name=collection_name, embedding_function=embedding_function)


def _persistent_client():
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(PERSIST_DIR))


def _collection_ids(collection, where):
    try:
        result = collection.get(where=where)
    except Exception:
        return []
    ids = result.get("ids") or []
    return [item for item in ids if item]


def _serialize_metadata_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return str(value)


def _prepare_metadata(metadata):
    output = {}
    for key, value in (metadata or {}).items():
        output[key] = _serialize_metadata_value(value)
    return output


def _index_domain_docs(domain, collection):
    documents = load_markdown_docs(domain)
    ids = []
    texts = []
    metadatas = []
    chunk_count = 0

    for doc in documents:
        chunks = chunk_document(doc)
        for index, chunk in enumerate(chunks):
            doc_id = doc["doc_id"]
            chunk_id = f"legacy::{doc_id}::chunk::{index}"
            chunk_text = "\n".join(chunk)
            ids.append(chunk_id)
            texts.append(chunk_text)
            meta = doc.get("meta", {})
            metadatas.append(
                _prepare_metadata(
                    {
                        "doc_id": doc_id,
                        "parent_doc_id": doc_id,
                        "title": doc["title"],
                        "bullets": chunk_text,
                        "tags": ",".join(doc.get("tags", [])),
                        "aliases": ",".join(doc.get("aliases", [])),
                        "intent_tags": ",".join(doc.get("intent_tags", [])),
                        "domain": domain,
                        "topic": meta.get("topic", ""),
                        "risk_level": meta.get("risk_level", ""),
                        "policy_type": meta.get("policy_type", ""),
                        "policy_level": meta.get("policy_level", ""),
                        "source": meta.get("source", "") or doc_id,
                        "file_name": f"{doc_id}.md",
                        "doc_type": "markdown",
                        "updated_at": meta.get("updated_at", ""),
                        "chunk_index": index,
                        "record_type": LEGACY_RECORD_TYPE,
                        "version": 1,
                        "is_active": True,
                    }
                )
            )
            chunk_count += 1

    if ids:
        collection.add(ids=ids, documents=texts, metadatas=metadatas)
    return len(documents), chunk_count


def build_or_load_vector_store(domain):
    client = _persistent_client()
    embedding_function = _get_embedding_function()
    collection = _get_collection(client, domain, embedding_function)
    if collection.count() == 0:
        _index_domain_docs(domain, collection)
        return collection
    legacy_ids = _collection_ids(collection, {"record_type": LEGACY_RECORD_TYPE})
    if not legacy_ids:
        _index_domain_docs(domain, collection)
    return collection


def rebuild_vector_store(domain, force=False):
    client = _persistent_client()
    embedding_function = _get_embedding_function()
    collection = _get_collection(client, domain, embedding_function)
    legacy_ids = _collection_ids(collection, {"record_type": LEGACY_RECORD_TYPE})
    if legacy_ids:
        collection.delete(ids=legacy_ids)
    doc_count, chunk_count = _index_domain_docs(domain, collection)
    output = {
        "documents": doc_count,
        "chunks": chunk_count,
        "collection": COLLECTIONS[domain],
        "persist_path": str(PERSIST_DIR),
    }
    output.update(_embedding_meta())
    return output


def add_ingested_chunks(domain, chunks):
    if not chunks:
        return 0
    collection = build_or_load_vector_store(domain)
    ids = [chunk.chunk_id for chunk in chunks]
    texts = [chunk.text for chunk in chunks]
    metadatas = [_prepare_metadata(chunk.metadata) for chunk in chunks]
    collection.add(ids=ids, documents=texts, metadatas=metadatas)
    return len(ids)


def delete_by_doc_id(domain, doc_id):
    collection = build_or_load_vector_store(domain)
    ids = _collection_ids(collection, {"parent_doc_id": doc_id})
    if not ids:
        ids = _collection_ids(collection, {"doc_id": doc_id})
    if ids:
        collection.delete(ids=ids)
    return len(ids)


def delete_by_source(domain, source):
    collection = build_or_load_vector_store(domain)
    ids = _collection_ids(collection, {"source": source})
    if ids:
        collection.delete(ids=ids)
    return len(ids)


def retrieve_knowledge(domain, query, top_k=4):
    collection = build_or_load_vector_store(domain)
    n_results = max(1, int(top_k or 4))
    try:
        available = int(collection.count() or 0)
    except Exception:
        available = 0
    if available > 0:
        n_results = min(n_results, available)
    results = collection.query(query_texts=[query], n_results=n_results)
    output = []
    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    for doc_id, metadata, distance in zip(ids, metadatas, distances):
        if distance is None:
            score = 0.0
        else:
            score = 1.0 / (1.0 + float(distance))
        meta = {}
        if metadata:
            for key in ["risk_level", "policy_type", "policy_level", "source", "topic", "updated_at", "version", "doc_type", "file_name", "section", "page_num"]:
                if metadata.get(key) not in (None, ""):
                    meta[key] = metadata.get(key)
        bullets = metadata.get("bullets", []) if metadata else []
        if isinstance(bullets, str):
            bullets = [item for item in bullets.splitlines() if item.strip()]
        if not bullets:
            doc_text = metadata.get("text", "") if metadata else ""
            if isinstance(doc_text, str) and doc_text.strip():
                bullets = [item for item in doc_text.splitlines() if item.strip()]
        tags = metadata.get("tags", "") if metadata else ""
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        aliases = metadata.get("aliases", "") if metadata else ""
        if isinstance(aliases, str):
            aliases = [item.strip() for item in aliases.split(",") if item.strip()]
        intent_tags = metadata.get("intent_tags", "") if metadata else ""
        if isinstance(intent_tags, str):
            intent_tags = [item.strip() for item in intent_tags.split(",") if item.strip()]
        output.append(
            {
                "doc_id": metadata.get("doc_id", metadata.get("parent_doc_id", doc_id)),
                "title": metadata.get("title", ""),
                "bullets": bullets,
                "score": round(score, 3),
                "domain": metadata.get("domain", domain),
                "tags": tags,
                "aliases": aliases,
                "intent_tags": intent_tags,
                "meta": meta,
            }
        )
    return output


def get_kb_status():
    if not PERSIST_DIR.exists():
        return {"ok": False, "domain": [], "error": "NOT_CONFIGURED"}
    try:
        client = _persistent_client()
        existing = {collection.name for collection in client.list_collections()}
        domains = [domain for domain, collection_name in COLLECTIONS.items() if collection_name in existing]
        if not domains:
            return {"ok": False, "domain": [], "error": "NOT_CONFIGURED"}
        out = {"ok": True, "domain": domains, "error": None}
        out.update(_embedding_meta())
        return out
    except Exception as exc:
        return {"ok": False, "domain": [], "error": str(exc)}


from pathlib import Path


# 中文注释：统一知识库路径与域名常量，避免散落在多个文件中
BASE_DIR = Path(__file__).resolve().parent
SAFETY_DOMAIN = "safety"
BIZ_DOMAIN = "biz"

SAFETY_DOCS_DIR = BASE_DIR / "safety_docs"
BIZ_DOCS_DIR = BASE_DIR / "biz_docs"
PERSIST_DIR = BASE_DIR.parent / "data" / "chroma"

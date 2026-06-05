from __future__ import annotations

import chromadb
from langchain_chroma import Chroma

from core.config import get_settings
from core.langchain_client import get_embeddings
from core.logging import get_logger

logger = get_logger(__name__)

_client: chromadb.PersistentClient | None = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        logger.info({"event": "chroma_client_init", "path": settings.chroma_persist_dir})
    return _client


def get_sop_collection() -> chromadb.Collection:
    settings = get_settings()
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def get_langchain_vectorstore() -> Chroma:
    settings = get_settings()
    return Chroma(
        client=get_chroma_client(),
        collection_name=settings.chroma_collection_name,
        embedding_function=get_embeddings(),
        collection_metadata={"hnsw:space": "cosine"},
    )


def health_check() -> bool:
    try:
        col = get_sop_collection()
        _ = col.count()
        return True
    except Exception:
        return False

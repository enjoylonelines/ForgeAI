from __future__ import annotations

from functools import lru_cache

from langchain_ollama import ChatOllama, OllamaEmbeddings

from core.config import get_settings


@lru_cache(maxsize=None)
def get_chat_llm(model: str | None = None) -> ChatOllama:
    s = get_settings()
    return ChatOllama(
        model=model or s.ollama_chat_model,
        base_url=s.ollama_base_url,
        temperature=0.1,
        timeout=int(s.ollama_timeout_seconds),
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    s = get_settings()
    return OllamaEmbeddings(
        model=s.ollama_embed_model,
        base_url=s.ollama_base_url,
    )

from __future__ import annotations

from functools import lru_cache

from langchain_ollama import ChatOllama, OllamaEmbeddings

from core.config import get_settings


_BASE_SEED = 42


@lru_cache(maxsize=None)
def get_chat_llm(model: str | None = None, seed: int = _BASE_SEED) -> ChatOllama:
    s = get_settings()
    return ChatOllama(
        model=model or s.ollama_chat_model,
        base_url=s.ollama_base_url,
        temperature=0.0,
        seed=seed,
        timeout=int(s.ollama_timeout_seconds),
        num_ctx=s.ollama_num_ctx,
        num_predict=s.ollama_num_predict,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    s = get_settings()
    return OllamaEmbeddings(
        model=s.ollama_embed_model,
        base_url=s.ollama_base_url,
    )

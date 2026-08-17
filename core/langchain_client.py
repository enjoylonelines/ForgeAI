from __future__ import annotations

from functools import lru_cache

from langchain_ollama import ChatOllama, OllamaEmbeddings

from core.config import get_settings
from core.openai_compatible_client import OpenAICompatibleChatModel, OpenAICompatibleEmbeddings


_BASE_SEED = 42


@lru_cache(maxsize=None)
def get_chat_llm(model: str | None = None, seed: int = _BASE_SEED):
    s = get_settings()
    if s.llm_mode == "api":
        if not s.llm_api_key:
            raise RuntimeError("LLM_MODE=api requires OPENAI_API_KEY or LLM_API_KEY")
        return OpenAICompatibleChatModel(
            api_key=s.llm_api_key,
            base_url=s.llm_api_base_url,
            model=model or s.llm_api_chat_model,
            temperature=0.0,
            timeout=s.llm_api_timeout_seconds,
            seed=seed,
        )
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
def get_embeddings():
    s = get_settings()
    if s.llm_mode == "api":
        if not s.llm_api_key:
            raise RuntimeError("LLM_MODE=api requires OPENAI_API_KEY or LLM_API_KEY")
        return OpenAICompatibleEmbeddings(
            api_key=s.llm_api_key,
            base_url=s.llm_api_base_url,
            model=s.llm_api_embedding_model,
            timeout=s.llm_api_timeout_seconds,
        )
    return OllamaEmbeddings(
        model=s.ollama_embed_model,
        base_url=s.ollama_base_url,
    )

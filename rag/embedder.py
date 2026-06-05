from __future__ import annotations

from core.langchain_client import get_embeddings


async def embed_text(text: str) -> list[float]:
    return await get_embeddings().aembed_query(text)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    return await get_embeddings().aembed_documents(texts)

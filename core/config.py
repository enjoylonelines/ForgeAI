from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_chat_model: str = field(default_factory=lambda: os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b"))
    ollama_embed_model: str = field(default_factory=lambda: os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
    ollama_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120.0")))
    ollama_num_ctx: int = field(default_factory=lambda: int(os.getenv("OLLAMA_NUM_CTX", "2048")))
    ollama_num_predict: int = field(default_factory=lambda: int(os.getenv("OLLAMA_NUM_PREDICT", "512")))

    chroma_persist_dir: str = field(default_factory=lambda: os.getenv("CHROMA_PERSIST_DIR", "./data/chroma"))
    chroma_collection_name: str = field(default_factory=lambda: os.getenv("CHROMA_COLLECTION_NAME", "sop_documents"))

    grounding_score_threshold: float = field(default_factory=lambda: float(os.getenv("GROUNDING_SCORE_THRESHOLD", "0.75")))
    grounding_approve_threshold: float = field(default_factory=lambda: float(os.getenv("GROUNDING_APPROVE_THRESHOLD", "0.85")))
    grounding_review_threshold: float = field(default_factory=lambda: float(os.getenv("GROUNDING_REVIEW_THRESHOLD", "0.60")))
    chunk_size: int = field(default_factory=lambda: int(os.getenv("CHUNK_SIZE", "1024")))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv("CHUNK_OVERLAP", "200")))
    top_k_retrieval: int = field(default_factory=lambda: int(os.getenv("TOP_K_RETRIEVAL", "5")))

    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    langfuse_enabled: bool = field(default_factory=lambda: os.getenv("LANGFUSE_ENABLED", "false").lower() == "true")
    langfuse_host: str = field(default_factory=lambda: os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))

    pipeline_max_retries: int = field(default_factory=lambda: int(os.getenv("PIPELINE_MAX_RETRIES", "2")))
    control_adapter_path: str = field(default_factory=lambda: os.getenv("CONTROL_ADAPTER_PATH", "./build/control_adapter"))
    decision_log_path: str = field(default_factory=lambda: os.getenv("DECISION_LOG_PATH", "./logs/decisions.jsonl"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

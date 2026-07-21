from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate

from core.config import get_settings
from core.langchain_client import _BASE_SEED, get_chat_llm
from core.langfuse_client import get_langfuse
from core.logging import get_logger

logger = get_logger(__name__)


class MaxRetriesExceededError(RuntimeError):
    pass


class ParseOutputError(ValueError):
    pass


class BaseAgent:
    def __init__(
        self,
        system_prompt: str,
        model: str | None = None,
        prompt_name: str = "",
        prompt_version: str = "",
    ) -> None:
        self.system_prompt = system_prompt
        self.model = model
        self.prompt_name = prompt_name
        self.prompt_version = prompt_version

        self._prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            HumanMessagePromptTemplate.from_template("{user_message}"),
        ])
        self._chain = (
            self._prompt | get_chat_llm(model) | JsonOutputParser()
        ).with_retry(stop_after_attempt=3, wait_exponential_jitter=True)

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def _invoke_chain(
        self,
        user_message: str,
        correlation_id: str | None,
        seed: int | None = None,
    ) -> dict:
        if seed is not None and seed != _BASE_SEED:
            chain = (
                self._prompt | get_chat_llm(self.model, seed=seed) | JsonOutputParser()
            ).with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
        else:
            chain = self._chain

        start = time.monotonic()
        lf = get_langfuse()
        generation = None

        if lf:
            generation = lf.start_observation(
                name=self.__class__.__name__,
                as_type="generation",
                model=self.model or get_settings().ollama_chat_model,
                input=user_message,
                metadata={
                    "prompt_name": self.prompt_name,
                    "prompt_version": self.prompt_version,
                    "correlation_id": correlation_id,
                },
            )

        try:
            result: dict = await chain.ainvoke({"user_message": user_message})
            elapsed_ms = round((time.monotonic() - start) * 1000)
            if generation:
                generation.update(output=result, metadata={"latency_ms": elapsed_ms})
                generation.end()
            logger.info({
                "event": "llm_call_success",
                "correlation_id": correlation_id,
                "agent": self.__class__.__name__,
                "prompt_name": self.prompt_name,
                "prompt_version": self.prompt_version,
                "latency_ms": elapsed_ms,
            })
            return result
        except Exception as exc:
            if generation:
                generation.update(level="ERROR", status_message=str(exc))
                generation.end()
            logger.warning({
                "event": "llm_call_failed",
                "correlation_id": correlation_id,
                "agent": self.__class__.__name__,
                "error": str(exc),
            })
            raise MaxRetriesExceededError(
                f"{self.__class__.__name__} chain failed after retries"
            ) from exc

    def _log(self, event: str, correlation_id: str | None, **extra: Any) -> None:
        logger.info({
            "event": event,
            "correlation_id": correlation_id,
            "agent": self.__class__.__name__,
            **extra,
        })

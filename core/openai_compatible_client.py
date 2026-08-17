from __future__ import annotations

import json
from typing import Any, Iterable

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class OpenAICompatibleChatModel(BaseChatModel):
    """Small OpenAI-compatible chat model adapter backed by httpx.

    It intentionally avoids the optional openai/langchain-openai packages so the
    frozen dependency lock can remain unchanged.
    """

    api_key: str
    base_url: str
    model: str
    temperature: float = 0.0
    timeout: float = 60.0
    seed: int | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "openai-compatible"

    def bind_tools(self, tools: Iterable[Any], **_: Any) -> "OpenAICompatibleChatModel":
        return self.model_copy(update={"tools": [_tool_schema(tool) for tool in tools]})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_openai(message) for message in messages],
            "temperature": self.temperature,
        }
        if stop:
            payload["stop"] = stop
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.tools:
            payload["tools"] = self.tools

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        message = data["choices"][0]["message"]
        generation_info = {
            "model": data.get("model", self.model),
            "usage": data.get("usage"),
        }
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=_message_from_openai(message),
                    generation_info=generation_info,
                )
            ],
            llm_output=generation_info,
        )


class OpenAICompatibleEmbeddings:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        data = self._post_embeddings(texts)
        return [item["embedding"] for item in data["data"]]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        data = await self._apost_embeddings(texts)
        return [item["embedding"] for item in data["data"]]

    def _post_embeddings(self, texts: list[str]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, headers=headers, json={"model": self.model, "input": texts})
            response.raise_for_status()
            return response.json()

    async def _apost_embeddings(self, texts: list[str]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=headers, json={"model": self.model, "input": texts})
            response.raise_for_status()
            return response.json()


def _message_to_openai(message: BaseMessage) -> dict[str, Any]:
    content = message.content if isinstance(message.content, str) else json.dumps(message.content, ensure_ascii=False)
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": content}
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": content}
    if isinstance(message, AIMessage):
        row: dict[str, Any] = {"role": "assistant", "content": content}
        if message.tool_calls:
            row["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["args"], ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return row
    if isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": content,
        }
    return {"role": "user", "content": content}


def _message_from_openai(message: dict[str, Any]) -> AIMessage:
    tool_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        raw_args = function.get("arguments") or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {"_raw_arguments": raw_args}
        tool_calls.append({
            "name": function.get("name", ""),
            "args": args,
            "id": call.get("id", ""),
            "type": "tool_call",
        })
    return AIMessage(content=message.get("content") or "", tool_calls=tool_calls)


def _tool_schema(tool: Any) -> dict[str, Any]:
    properties = dict(getattr(tool, "args", {}) or {})
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": getattr(tool, "description", "") or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties.keys()),
                "additionalProperties": False,
            },
        },
    }

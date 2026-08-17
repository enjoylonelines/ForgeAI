from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage, ToolMessage

from core.openai_compatible_client import OpenAICompatibleChatModel, OpenAICompatibleEmbeddings
from tools.sensor_tools import calculate_risk_index


def test_openai_chat_model_posts_chat_completion_without_leaking_key():
    response = MagicMock()
    response.json.return_value = {
        "model": "gpt-test",
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        "choices": [{"message": {"content": "{\"ok\": true}"}}],
    }
    response.raise_for_status.return_value = None

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response

    with patch("core.openai_compatible_client.httpx.Client", return_value=client):
        model = OpenAICompatibleChatModel(
            api_key="secret-key",
            base_url="https://example.test/v1",
            model="gpt-test",
        )
        result = model.invoke([HumanMessage(content="hello")])

    assert result.content == "{\"ok\": true}"
    _, kwargs = client.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer secret-key"
    assert kwargs["json"]["model"] == "gpt-test"
    assert "secret-key" not in str(kwargs["json"])


def test_openai_chat_model_converts_tool_calls():
    response = MagicMock()
    response.json.return_value = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "calculate_risk_index",
                        "arguments": "{\"tool_wear_min\": 220, \"torque_nm\": 60, \"rotational_speed_rpm\": 1500}",
                    },
                }],
            }
        }],
    }
    response.raise_for_status.return_value = None

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response

    with patch("core.openai_compatible_client.httpx.Client", return_value=client):
        model = OpenAICompatibleChatModel(
            api_key="secret-key",
            base_url="https://example.test/v1",
            model="gpt-test",
        ).bind_tools([calculate_risk_index])
        result = model.invoke([HumanMessage(content="use tool")])

    assert result.tool_calls[0]["name"] == "calculate_risk_index"
    assert result.tool_calls[0]["args"]["tool_wear_min"] == 220
    _, kwargs = client.post.call_args
    assert kwargs["json"]["tools"][0]["function"]["name"] == "calculate_risk_index"


def test_openai_chat_model_serializes_tool_messages():
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "done"}}]}
    response.raise_for_status.return_value = None

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response

    with patch("core.openai_compatible_client.httpx.Client", return_value=client):
        model = OpenAICompatibleChatModel(
            api_key="secret-key",
            base_url="https://example.test/v1",
            model="gpt-test",
        )
        model.invoke([ToolMessage(content="{\"risk_index\": 1}", tool_call_id="call-1")])

    _, kwargs = client.post.call_args
    assert kwargs["json"]["messages"][0]["role"] == "tool"
    assert kwargs["json"]["messages"][0]["tool_call_id"] == "call-1"


async def test_openai_embeddings_posts_embedding_request():
    response = MagicMock()
    response.json.return_value = {
        "data": [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
        ]
    }
    response.raise_for_status.return_value = None

    client = MagicMock()
    client.__aenter__.return_value = client
    client.post = AsyncMock(return_value=response)

    with patch("core.openai_compatible_client.httpx.AsyncClient", return_value=client):
        embeddings = OpenAICompatibleEmbeddings(
            api_key="secret-key",
            base_url="https://example.test/v1",
            model="embed-test",
        )
        result = await embeddings.aembed_documents(["a", "b"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    _, kwargs = client.post.call_args
    assert kwargs["json"] == {"model": "embed-test", "input": ["a", "b"]}

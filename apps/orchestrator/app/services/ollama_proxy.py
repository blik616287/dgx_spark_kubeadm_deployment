import json
import time
import uuid
from typing import AsyncIterator

import httpx

from ..models import (
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    DeltaMessage,
    StreamChoice,
    Usage,
)


def _to_ollama_request(
    ollama_model: str,
    messages: list[ChatMessage],
    stream: bool,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
) -> dict:
    body = {
        "model": ollama_model,
        "messages": [{"role": m.role, "content": m.content or ""} for m in messages],
        "stream": stream,
    }
    options = {}
    if temperature is not None:
        options["temperature"] = temperature
    if top_p is not None:
        options["top_p"] = top_p
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    if options:
        body["options"] = options
    return body


async def chat_completion(
    client: httpx.AsyncClient,
    backend_url: str,
    ollama_model: str,
    messages: list[ChatMessage],
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    request_model_name: str = "",
) -> ChatCompletionResponse:
    body = _to_ollama_request(
        ollama_model, messages, stream=False,
        temperature=temperature, top_p=top_p, max_tokens=max_tokens,
    )
    resp = await client.post(f"{backend_url}/api/chat", json=body, timeout=300.0)
    resp.raise_for_status()
    data = resp.json()

    return ChatCompletionResponse(
        model=request_model_name or ollama_model,
        choices=[Choice(
            message=ChatMessage(role="assistant", content=data.get("message", {}).get("content", "")),
            finish_reason="stop",
        )],
        usage=Usage(
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        ),
    )


async def chat_completion_stream(
    client: httpx.AsyncClient,
    backend_url: str,
    ollama_model: str,
    messages: list[ChatMessage],
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    request_model_name: str = "",
) -> AsyncIterator[str]:
    body = _to_ollama_request(
        ollama_model, messages, stream=True,
        temperature=temperature, top_p=top_p, max_tokens=max_tokens,
    )

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    model_name = request_model_name or ollama_model

    first_chunk = ChatCompletionChunk(
        id=chunk_id, created=created, model=model_name,
        choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
    )
    yield f"data: {first_chunk.model_dump_json()}\n\n"

    async with client.stream("POST", f"{backend_url}/api/chat", json=body, timeout=300.0) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            done = data.get("done", False)

            if content:
                chunk = ChatCompletionChunk(
                    id=chunk_id, created=created, model=model_name,
                    choices=[StreamChoice(delta=DeltaMessage(content=content))],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"

            if done:
                final = ChatCompletionChunk(
                    id=chunk_id, created=created, model=model_name,
                    choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
                )
                yield f"data: {final.model_dump_json()}\n\n"
                yield "data: [DONE]\n\n"
                break

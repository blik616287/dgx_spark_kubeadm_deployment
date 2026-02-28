import asyncio
import json
import uuid
import logging

import httpx
from fastapi import APIRouter, Header, BackgroundTasks
from fastapi.responses import StreamingResponse

from ..config import Settings
from ..models import ChatCompletionRequest, ChatCompletionResponse, ChatMessage
from ..services import (
    router as model_router,
    ollama_proxy,
    working_memory,
    recall_memory,
    archival_memory,
    embedding,
    summarizer,
    workspace as workspace_svc,
)

logger = logging.getLogger("orchestrator.chat")
router = APIRouter()

_settings: Settings | None = None
_http_client: httpx.AsyncClient | None = None


def init_chat(settings: Settings, client: httpx.AsyncClient):
    global _settings, _http_client
    _settings = settings
    _http_client = client


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    background_tasks: BackgroundTasks,
    x_workspace: str | None = Header(default=None),
):
    # 1. Resolve model -> backend
    backend_url, ollama_model = model_router.resolve(request.model)

    # 2. Derive workspace
    ws = workspace_svc.derive_workspace(request, x_workspace)

    # 3. Session management
    session_id = request.session_id or str(uuid.uuid4())
    await recall_memory.ensure_session(session_id, ws, request.model)

    # 4. Store incoming user messages
    user_message = None
    for msg in request.messages:
        if msg.role == "user":
            user_message = msg
    if user_message:
        await working_memory.append_turn(
            session_id, user_message, _settings.session_ttl_seconds
        )
        await recall_memory.store_message(session_id, user_message)

    # 5. Build augmented message list
    augmented_messages = await _build_augmented_messages(request, session_id, ws)

    # 6. Proxy to backend LLM
    if request.stream:
        collected_content = []

        async def stream_and_capture():
            async for chunk_str in ollama_proxy.chat_completion_stream(
                _http_client, backend_url, ollama_model,
                augmented_messages,
                temperature=request.temperature,
                top_p=request.top_p,
                max_tokens=request.max_tokens,
                request_model_name=request.model,
            ):
                if chunk_str.startswith("data: ") and chunk_str.strip() != "data: [DONE]":
                    try:
                        chunk_data = json.loads(chunk_str[6:])
                        delta_content = (
                            chunk_data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta_content:
                            collected_content.append(delta_content)
                    except (json.JSONDecodeError, IndexError):
                        pass
                yield chunk_str

            # After streaming, store assistant response
            full_response = "".join(collected_content)
            if full_response:
                assistant_msg = ChatMessage(role="assistant", content=full_response)
                await working_memory.append_turn(
                    session_id, assistant_msg, _settings.session_ttl_seconds
                )
                await recall_memory.store_message(session_id, assistant_msg)
                turn_count = await working_memory.get_turn_count(session_id)
                await summarizer.maybe_promote(session_id, ws, turn_count)

        return StreamingResponse(
            stream_and_capture(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Session-Id": session_id,
            },
        )
    else:
        response = await ollama_proxy.chat_completion(
            _http_client, backend_url, ollama_model,
            augmented_messages,
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_tokens,
            request_model_name=request.model,
        )

        if response.choices:
            assistant_msg = response.choices[0].message
            await working_memory.append_turn(
                session_id, assistant_msg, _settings.session_ttl_seconds
            )
            await recall_memory.store_message(session_id, assistant_msg)

        turn_count = await working_memory.get_turn_count(session_id)
        background_tasks.add_task(
            summarizer.maybe_promote, session_id, ws, turn_count
        )

        return response


async def _build_augmented_messages(
    request: ChatCompletionRequest,
    session_id: str,
    workspace: str,
) -> list[ChatMessage]:
    messages = list(request.messages)

    system_msg = None
    non_system = []
    for msg in messages:
        if msg.role == "system":
            system_msg = msg
        else:
            non_system.append(msg)

    user_query = ""
    for msg in reversed(non_system):
        if msg.role == "user" and msg.content:
            user_query = msg.content
            break

    if not user_query:
        return messages

    # Fetch all three memory tiers in parallel
    working_task = working_memory.get_turns(session_id)
    recall_task = _fetch_recall_context(user_query, workspace, session_id)
    archival_task = _fetch_archival_context(user_query, workspace)

    prior_turns, recall_context, archival_context = await asyncio.gather(
        working_task, recall_task, archival_task, return_exceptions=True,
    )

    if isinstance(prior_turns, Exception):
        logger.warning(f"Working memory fetch failed: {prior_turns}")
        prior_turns = []
    if isinstance(recall_context, Exception):
        logger.warning(f"Recall memory fetch failed: {recall_context}")
        recall_context = ""
    if isinstance(archival_context, Exception):
        logger.warning(f"Archival memory fetch failed: {archival_context}")
        archival_context = ""

    # Build memory context block for system message
    context_parts = []
    if archival_context:
        context_parts.append(
            f"<archival_memory>\n{archival_context}\n</archival_memory>"
        )
    if recall_context:
        context_parts.append(
            f"<recall_memory>\n{recall_context}\n</recall_memory>"
        )

    # Build augmented message list
    augmented = []

    # System message (with memory context if any)
    if context_parts:
        memory_block = "\n\n".join(context_parts)
        if system_msg:
            augmented.append(ChatMessage(
                role="system",
                content=f"{system_msg.content}\n\n--- Relevant Memory ---\n{memory_block}",
            ))
        else:
            augmented.append(ChatMessage(
                role="system",
                content=f"--- Relevant Memory ---\n{memory_block}",
            ))
    elif system_msg:
        augmented.append(system_msg)

    # Inject prior working memory turns (excluding the latest user msg we just appended)
    # This gives the LLM full conversation history for cross-model session sharing
    if prior_turns:
        # Drop the last turn — it's the current user message we just stored
        history = prior_turns[:-1]
        for turn in history:
            augmented.append(turn)

    augmented.extend(non_system)
    return augmented


async def _fetch_recall_context(
    query: str, workspace: str, session_id: str
) -> str:
    query_vector = await embedding.embed_text(query, _http_client)
    results = await recall_memory.search_similar_sessions(
        workspace, query_vector,
        top_k=_settings.recall_top_k,
        exclude_session_id=session_id,
    )
    if not results:
        return ""

    parts = []
    for r in results:
        sim = r["similarity"]
        if sim < 0.3:
            continue
        parts.append(f"[Past conversation (relevance: {sim:.2f})]\n{r['summary']}")

    return "\n\n".join(parts)


async def _fetch_archival_context(query: str, workspace: str) -> str:
    data = await archival_memory.query(query, workspace, mode="hybrid", client=_http_client)
    if not data.get("entities") and not data.get("relations") and not data.get("chunks"):
        return ""
    return archival_memory.format_context(data)

import logging

import httpx

from . import working_memory, recall_memory, archival_memory, embedding
from ..config import Settings

logger = logging.getLogger("orchestrator.summarizer")

_settings: Settings | None = None


def init_summarizer(settings: Settings):
    global _settings
    _settings = settings


async def maybe_promote(session_id: str, workspace: str, turn_count: int):
    if not _settings:
        return

    try:
        if turn_count >= _settings.promote_after_turns and turn_count % _settings.promote_after_turns == 0:
            await _summarize_and_store(session_id, workspace)

        if turn_count >= _settings.archival_after_turns and turn_count % _settings.archival_after_turns == 0:
            await _promote_to_archival(session_id, workspace)
    except Exception as e:
        logger.error(f"Promotion failed for session {session_id}: {e}")


async def _summarize_and_store(session_id: str, workspace: str):
    logger.info(f"Summarizing session {session_id}")

    messages = await recall_memory.get_session_messages(session_id)
    if not messages:
        return

    conversation_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in messages if m.get('content')
    )

    if len(conversation_text) > 12000:
        conversation_text = conversation_text[:12000] + "\n... (truncated)"

    summary = await _call_summarizer(conversation_text)
    if not summary:
        return

    async with httpx.AsyncClient() as client:
        summary_vector = await embedding.embed_text(summary, client)

    await recall_memory.update_session_summary(session_id, summary, summary_vector)
    logger.info(f"Session {session_id} summarized ({len(summary)} chars)")


async def _promote_to_archival(session_id: str, workspace: str):
    logger.info(f"Promoting session {session_id} to archival")

    session_info = await recall_memory.get_session_info(session_id)
    if not session_info:
        return

    summary = session_info.get("summary")
    if not summary:
        await _summarize_and_store(session_id, workspace)
        session_info = await recall_memory.get_session_info(session_id)
        summary = session_info.get("summary") if session_info else None
        if not summary:
            return

    archival_text = (
        f"Conversation Summary (session: {session_id}, workspace: {workspace})\n\n"
        f"{summary}"
    )

    async with httpx.AsyncClient() as client:
        await archival_memory.ingest_text(archival_text, workspace, client)

    logger.info(f"Session {session_id} promoted to archival in workspace {workspace}")


async def _call_summarizer(conversation_text: str) -> str:
    prompt = (
        "Summarize the following conversation concisely. "
        "Focus on key decisions, facts, technical details, and action items. "
        "Write in third person. Keep it under 500 words.\n\n"
        f"CONVERSATION:\n{conversation_text}\n\n"
        "SUMMARY:"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_settings.summarizer_url}/api/chat",
            json={
                "model": _settings.summarizer_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 1024},
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")

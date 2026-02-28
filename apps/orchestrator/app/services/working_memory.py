import json

import redis.asyncio as redis

from ..models import ChatMessage

_client: redis.Redis | None = None


async def init_redis(url: str):
    global _client
    _client = redis.from_url(url, decode_responses=True)
    await _client.ping()


async def close_redis():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _key(session_id: str) -> str:
    return f"session:{session_id}"


async def get_turns(session_id: str) -> list[ChatMessage]:
    data = await _client.lrange(_key(session_id), 0, -1)
    return [ChatMessage(**json.loads(item)) for item in data]


async def append_turn(session_id: str, message: ChatMessage, ttl: int = 7200):
    key = _key(session_id)
    await _client.rpush(key, message.model_dump_json())
    await _client.expire(key, ttl)


async def get_turn_count(session_id: str) -> int:
    return await _client.llen(_key(session_id))


async def delete_session(session_id: str):
    await _client.delete(_key(session_id))

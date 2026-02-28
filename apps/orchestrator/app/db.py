import asyncpg

from .config import Settings

_pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS orchestrator_sessions (
    id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL DEFAULT 'default',
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary TEXT,
    summary_vector vector(1024)
);

CREATE TABLE IF NOT EXISTS orchestrator_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES orchestrator_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orchestrator_documents (
    id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL DEFAULT 'default',
    file_name TEXT NOT NULL,
    content_type TEXT,
    compressed_blob BYTEA NOT NULL,
    original_size BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_orchestrator_sessions_workspace
    ON orchestrator_sessions(workspace);
CREATE INDEX IF NOT EXISTS idx_orchestrator_messages_session
    ON orchestrator_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_orchestrator_documents_workspace
    ON orchestrator_documents(workspace);
CREATE INDEX IF NOT EXISTS idx_orchestrator_sessions_summary_vector
    ON orchestrator_sessions
    USING hnsw (summary_vector vector_cosine_ops);

CREATE TABLE IF NOT EXISTS orchestrator_ingest_jobs (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES orchestrator_documents(id),
    workspace TEXT NOT NULL DEFAULT 'default',
    job_type TEXT NOT NULL DEFAULT 'document',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    result JSONB DEFAULT '{}'::jsonb,
    attempts INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status
    ON orchestrator_ingest_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_workspace
    ON orchestrator_ingest_jobs(workspace);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_doc_id
    ON orchestrator_ingest_jobs(doc_id);
"""


def _encode_vector(v: list[float]) -> str:
    return "[" + ",".join(str(x) for x in v) + "]"


def _decode_vector(v: str) -> list[float]:
    return [float(x) for x in v.strip("[]").split(",")]


async def _init_connection(conn: asyncpg.Connection):
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.set_type_codec(
        "vector",
        encoder=_encode_vector,
        decoder=_decode_vector,
        schema="public",
        format="text",
    )


async def init_pool(settings: Settings) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        database=settings.pg_database,
        min_size=2,
        max_size=10,
        init=_init_connection,
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    return _pool


def get_pool() -> asyncpg.Pool:
    assert _pool is not None, "Database pool not initialized"
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

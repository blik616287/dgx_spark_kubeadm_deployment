import json
import logging

import asyncpg

from .config import Settings

logger = logging.getLogger("ingest-worker.db")

_pool: asyncpg.Pool | None = None

JOB_SCHEMA_SQL = """
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


async def init_pool(settings: Settings) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        database=settings.pg_database,
        min_size=2,
        max_size=5,
    )
    async with _pool.acquire() as conn:
        await conn.execute(JOB_SCHEMA_SQL)
    logger.info("Database pool initialized, job table ready")
    return _pool


def get_pool() -> asyncpg.Pool:
    assert _pool is not None, "Database pool not initialized"
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_job(job_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM orchestrator_ingest_jobs WHERE id = $1", job_id
    )
    return dict(row) if row else None


async def mark_job_started(job_id: str):
    pool = get_pool()
    await pool.execute(
        """UPDATE orchestrator_ingest_jobs
           SET status = 'processing', started_at = now(), attempts = attempts + 1
           WHERE id = $1""",
        job_id,
    )


async def mark_job_completed(job_id: str, result: dict):
    pool = get_pool()
    await pool.execute(
        """UPDATE orchestrator_ingest_jobs
           SET status = 'completed', completed_at = now(), result = $2::jsonb
           WHERE id = $1""",
        job_id, json.dumps(result),
    )


async def mark_job_failed(job_id: str, error: str):
    pool = get_pool()
    await pool.execute(
        """UPDATE orchestrator_ingest_jobs
           SET status = 'failed', completed_at = now(), error = $2
           WHERE id = $1""",
        job_id, error,
    )


async def reset_job_queued(job_id: str):
    pool = get_pool()
    await pool.execute(
        "UPDATE orchestrator_ingest_jobs SET status = 'queued' WHERE id = $1",
        job_id,
    )


async def get_document_blob(doc_id: str) -> tuple[str, str, bytes, str | None] | None:
    """Returns (file_name, workspace, compressed_blob, metadata) or None."""
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT file_name, workspace, compressed_blob, metadata
           FROM orchestrator_documents WHERE id = $1""",
        doc_id,
    )
    if not row:
        return None
    return row["file_name"], row["workspace"], row["compressed_blob"], row["metadata"]

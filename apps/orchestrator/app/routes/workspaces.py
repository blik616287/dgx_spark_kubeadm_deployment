import logging

import httpx
from fastapi import APIRouter

from ..config import Settings
from ..db import get_pool

logger = logging.getLogger("orchestrator.workspaces")

router = APIRouter()
_settings: Settings | None = None


def init_workspaces(settings: Settings):
    global _settings
    _settings = settings


@router.delete("/v1/workspaces/{workspace}")
async def delete_workspace(workspace: str):
    """Delete all orchestrator documents, jobs, and LightRAG data for a workspace."""
    pool = get_pool()
    deleted_jobs = await pool.execute(
        "DELETE FROM orchestrator_ingest_jobs WHERE workspace = $1", workspace
    )
    deleted_docs = await pool.execute(
        "DELETE FROM orchestrator_documents WHERE workspace = $1", workspace
    )
    jobs_count = int(deleted_jobs.split()[-1]) if deleted_jobs else 0
    docs_count = int(deleted_docs.split()[-1]) if deleted_docs else 0

    # Clear LightRAG workspace
    lr_status = "skipped"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{_settings.lightrag_url}/documents",
                headers={"LIGHTRAG-WORKSPACE": workspace},
            )
            lr_status = "ok" if resp.status_code == 200 else f"error:{resp.status_code}"
    except Exception as e:
        lr_status = f"error:{e}"
        logger.warning(f"Failed to clear LightRAG workspace '{workspace}': {e}")

    logger.info(f"Deleted workspace '{workspace}': {docs_count} docs, {jobs_count} jobs, lightrag={lr_status}")
    return {
        "deleted_workspace": workspace,
        "documents_deleted": docs_count,
        "jobs_deleted": jobs_count,
        "lightrag": lr_status,
    }


@router.get("/v1/workspaces")
async def list_workspaces():
    pool = get_pool()
    rows = await pool.fetch("""
        SELECT
            d.workspace,
            COUNT(DISTINCT d.id) AS doc_count,
            COUNT(DISTINCT j.id) FILTER (WHERE j.status = 'queued') AS queued,
            COUNT(DISTINCT j.id) FILTER (WHERE j.status = 'processing') AS processing,
            COUNT(DISTINCT j.id) FILTER (WHERE j.status = 'completed') AS completed,
            COUNT(DISTINCT j.id) FILTER (WHERE j.status = 'failed') AS failed,
            MAX(d.created_at) AS last_activity
        FROM orchestrator_documents d
        LEFT JOIN orchestrator_ingest_jobs j ON j.doc_id = d.id
        GROUP BY d.workspace
        ORDER BY last_activity DESC
    """)
    return {
        "workspaces": [
            {
                "name": r["workspace"],
                "doc_count": r["doc_count"],
                "jobs": {
                    "queued": r["queued"],
                    "processing": r["processing"],
                    "completed": r["completed"],
                    "failed": r["failed"],
                },
                "last_activity": r["last_activity"].isoformat() if r["last_activity"] else None,
            }
            for r in rows
        ]
    }

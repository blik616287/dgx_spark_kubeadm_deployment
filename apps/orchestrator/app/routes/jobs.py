import json
import logging

from fastapi import APIRouter, HTTPException, Query

from ..db import get_pool
from ..models import JobStatusResponse


def _parse_result(raw) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return None

logger = logging.getLogger("orchestrator.jobs")

router = APIRouter()


@router.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM orchestrator_ingest_jobs WHERE id = $1", job_id
    )
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    return JobStatusResponse(
        job_id=row["id"],
        doc_id=row["doc_id"],
        workspace=row["workspace"],
        job_type=row["job_type"],
        status=row["status"],
        created_at=row["created_at"].isoformat(),
        started_at=row["started_at"].isoformat() if row["started_at"] else None,
        completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
        error=row["error"],
        result=_parse_result(row["result"]),
        attempts=row["attempts"],
    )


@router.get("/v1/jobs")
async def list_jobs(
    workspace: str = Query(default=None),
    status: str = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    pool = get_pool()
    conditions = []
    params = []
    idx = 1

    if workspace:
        conditions.append(f"workspace = ${idx}")
        params.append(workspace)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""SELECT * FROM orchestrator_ingest_jobs
                {where}
                ORDER BY created_at DESC
                LIMIT ${idx}"""
    params.append(limit)

    rows = await pool.fetch(query, *params)
    return {
        "jobs": [
            JobStatusResponse(
                job_id=r["id"],
                doc_id=r["doc_id"],
                workspace=r["workspace"],
                job_type=r["job_type"],
                status=r["status"],
                created_at=r["created_at"].isoformat(),
                started_at=r["started_at"].isoformat() if r["started_at"] else None,
                completed_at=r["completed_at"].isoformat() if r["completed_at"] else None,
                error=r["error"],
                result=_parse_result(r["result"]),
                attempts=r["attempts"],
            )
            for r in rows
        ],
        "count": len(rows),
    }

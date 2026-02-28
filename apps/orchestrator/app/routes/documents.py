import gzip
import logging
import uuid

from fastapi import APIRouter, UploadFile, File, Header, HTTPException
from fastapi.responses import Response

from ..config import Settings
from ..models import DocumentIngestResponse, CodebaseIngestResponse
from ..db import get_pool
from ..services.nats_client import publish_ingest_job

logger = logging.getLogger("orchestrator.documents")

router = APIRouter()
_settings: Settings | None = None


def init_documents(settings: Settings):
    global _settings
    _settings = settings


@router.post("/v1/documents/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    x_workspace: str = Header(default="default"),
):
    content = await file.read()
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    file_name = file.filename or "unknown"
    workspace = x_workspace

    compressed = gzip.compress(content)

    pool = get_pool()

    # Store blob
    await pool.execute(
        """INSERT INTO orchestrator_documents
           (id, workspace, file_name, content_type, compressed_blob, original_size)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        doc_id, workspace, file_name, file.content_type, compressed, len(content),
    )

    # Create job record
    await pool.execute(
        """INSERT INTO orchestrator_ingest_jobs
           (id, doc_id, workspace, job_type, status)
           VALUES ($1, $2, $3, $4, $5)""",
        job_id, doc_id, workspace, "document", "queued",
    )

    # Publish to NATS
    await publish_ingest_job(job_id, "document")

    return DocumentIngestResponse(
        doc_id=doc_id,
        job_id=job_id,
        file_name=file_name,
        workspace=workspace,
        original_size=len(content),
        compressed_size=len(compressed),
        status="queued",
    )


@router.get("/v1/documents/{doc_id}/download")
async def download_document(doc_id: str):
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT file_name, content_type, compressed_blob, original_size
           FROM orchestrator_documents WHERE id = $1""",
        doc_id,
    )
    if not row:
        raise HTTPException(404, f"Document {doc_id} not found")

    content = gzip.decompress(row["compressed_blob"])
    return Response(
        content=content,
        media_type=row["content_type"] or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{row["file_name"]}"',
            "Content-Length": str(len(content)),
        },
    )


@router.post("/v1/codebase/ingest")
async def ingest_codebase(
    file: UploadFile = File(...),
    x_workspace: str = Header(default="default"),
):
    """Ingest an entire codebase from a tar.gz or zip archive.

    Stores the archive and queues it for async processing by the ingest worker.
    """
    archive_bytes = await file.read()
    archive_name = file.filename or "codebase.tar.gz"
    workspace = x_workspace
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    compressed = gzip.compress(archive_bytes)

    pool = get_pool()

    # Store archive blob
    await pool.execute(
        """INSERT INTO orchestrator_documents
           (id, workspace, file_name, content_type, compressed_blob, original_size, metadata)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        doc_id, workspace, archive_name,
        file.content_type or "application/gzip",
        compressed, len(archive_bytes),
        '{"type": "codebase"}',
    )

    # Create job record
    await pool.execute(
        """INSERT INTO orchestrator_ingest_jobs
           (id, doc_id, workspace, job_type, status)
           VALUES ($1, $2, $3, $4, $5)""",
        job_id, doc_id, workspace, "codebase", "queued",
    )

    # Publish to NATS
    await publish_ingest_job(job_id, "codebase")

    return CodebaseIngestResponse(
        doc_id=doc_id,
        job_id=job_id,
        workspace=workspace,
        archive_name=archive_name,
        original_size=len(archive_bytes),
        compressed_size=len(compressed),
        status="queued",
    )

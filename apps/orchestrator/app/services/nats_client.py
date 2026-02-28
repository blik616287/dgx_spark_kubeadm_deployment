import json
import logging

import nats
from nats.js import JetStreamContext

logger = logging.getLogger("orchestrator.nats")

_nc: nats.NATS | None = None
_js: JetStreamContext | None = None


async def init_nats(nats_url: str):
    global _nc, _js
    _nc = await nats.connect(nats_url)
    _js = _nc.jetstream()
    logger.info(f"Connected to NATS at {nats_url}")


async def close_nats():
    global _nc, _js
    if _nc:
        await _nc.drain()
        _nc = None
        _js = None


async def publish_ingest_job(job_id: str, job_type: str = "document"):
    """Publish an ingestion job to the NATS INGEST stream."""
    assert _js is not None, "NATS not initialized"
    subject = f"ingest.{job_type}"
    payload = json.dumps({"job_id": job_id, "type": job_type}).encode()
    ack = await _js.publish(subject, payload)
    logger.info(f"Published job {job_id} to {subject} (seq={ack.seq})")
    return ack

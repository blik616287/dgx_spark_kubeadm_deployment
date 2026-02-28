import asyncio
import json
import logging
import signal

import nats
from nats.js.api import StreamConfig

from .config import Settings
from .db import init_pool, close_pool, get_job, mark_job_started, mark_job_completed, mark_job_failed, reset_job_queued
from .processor import process_document, process_codebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest-worker")

STREAM_NAME = "INGEST"
SUBJECTS = ["ingest.document", "ingest.codebase"]
CONSUMER_NAME = "ingest-worker"

settings = Settings()
_shutdown = asyncio.Event()


async def setup_stream(js):
    """Create or verify the INGEST JetStream stream."""
    try:
        await js.find_stream_name_by_subject("ingest.>")
        logger.info(f"Stream {STREAM_NAME} already exists")
    except Exception:
        await js.add_stream(
            StreamConfig(
                name=STREAM_NAME,
                subjects=SUBJECTS,
                retention="workqueue",
                max_msgs=10000,
                storage="file",
            )
        )
        logger.info(f"Created stream {STREAM_NAME}")


async def handle_message(msg):
    """Process a single NATS message."""
    try:
        payload = json.loads(msg.data.decode())
        job_id = payload["job_id"]
        job_type = payload.get("type", "document")
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Invalid message payload: {e}")
        await msg.term()
        return

    logger.info(f"Processing job {job_id} (type={job_type})")

    job = await get_job(job_id)
    if not job:
        logger.error(f"Job {job_id} not found in database")
        await msg.term()
        return

    if job["status"] == "completed":
        logger.info(f"Job {job_id} already completed, skipping")
        await msg.ack()
        return

    await mark_job_started(job_id)

    try:
        if job_type == "codebase":
            result = await process_codebase(
                job_id, job["doc_id"], settings.preprocessor_url, settings.batch_size
            )
        else:
            result = await process_document(
                job_id, job["doc_id"], settings.preprocessor_url
            )

        await mark_job_completed(job_id, result)
        await msg.ack()
        logger.info(f"Job {job_id} completed: {result}")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        attempts = job["attempts"] + 1
        if attempts >= settings.max_redeliveries:
            await mark_job_failed(job_id, str(e))
            await msg.term()
            logger.error(f"Job {job_id} permanently failed after {attempts} attempts")
        else:
            await mark_job_failed(job_id, str(e))
            await reset_job_queued(job_id)
            await msg.nak()


async def run():
    logger.info("Starting ingest worker...")

    await init_pool(settings)

    nc = await nats.connect(settings.nats_url)
    js = nc.jetstream()
    await setup_stream(js)
    logger.info(f"Connected to NATS at {settings.nats_url}")

    sub = await js.pull_subscribe(
        "ingest.>",
        durable=CONSUMER_NAME,
        stream=STREAM_NAME,
    )

    logger.info("Ingest worker ready, waiting for jobs...")

    while not _shutdown.is_set():
        try:
            messages = await sub.fetch(batch=1, timeout=5)
            for msg in messages:
                await handle_message(msg)
        except nats.errors.TimeoutError:
            continue
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            await asyncio.sleep(1)

    logger.info("Shutting down ingest worker...")
    await sub.unsubscribe()
    await nc.drain()
    await close_pool()


def main():
    loop = asyncio.new_event_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown.set)

    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()

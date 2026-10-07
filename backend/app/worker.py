"""Background worker: processes queued jobs (document extraction, later indexing).

    python -m app.worker

Run as many as you like; jobs are claimed atomically. Stops cleanly on SIGINT/SIGTERM
after finishing the job in hand.
"""

import asyncio
import logging
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import dispose_engine
from app.services import (
    document_processor,  # noqa: F401  (registers its job handler)
    jobs,
)
from app.services.ocr import get_ocr

logger = logging.getLogger("travel.worker")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.log_format)
    ocr = get_ocr()
    logger.info("worker.start", extra={
        "ocr": ocr.name if ocr else "unavailable",
        "document_ai": settings.DOCUMENT_AI_PROVIDER,
        "scanner": settings.MALWARE_SCANNER,
    })

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C raises KeyboardInterrupt instead
            pass

    try:
        while not stop.is_set():
            try:
                ran = await jobs.run_pending(max_jobs=10)
            except Exception:
                logger.exception("worker.loop_error")
                ran = 0
            if ran == 0:
                try:
                    await asyncio.wait_for(stop.wait(), settings.WORKER_POLL_SECONDS)
                except TimeoutError:
                    pass
    finally:
        await dispose_engine()
        logger.info("worker.stop")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

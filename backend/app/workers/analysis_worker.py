"""Run from backend/: python -m app.workers.analysis_worker [--once]."""
import argparse
import asyncio
import logging
import signal

import psycopg

from app.ai_engine.errors import AnalysisError
from app.ai_engine.groq_adapter import GroqTextAnalyzer
from app.config import load_ai_settings
from app.models.analysis_jobs import JobUnavailable, WorkerJobs
from app.services.analysis_jobs import AnalysisProcessor
from app.workers.config import load_worker_settings

logger = logging.getLogger(__name__)


async def run_loop(processor: AnalysisProcessor, stop: asyncio.Event, *, once: bool = False) -> None:
    while not stop.is_set():
        try:
            status = await processor.process_one()
        except (psycopg.Error, JobUnavailable):
            # No exception interpolation: DB errors may contain DSNs or row data.
            logger.error('analysis_worker database_unavailable')
            if once:
                raise JobUnavailable('Worker database unavailable') from None
            status = None
        if status:
            logger.info('analysis_worker status=%s', status)
        if once:
            return
        if status is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=processor.settings.poll_seconds)
            except TimeoutError:
                pass


async def run(*, once: bool = False) -> None:
    ai, config = load_ai_settings(), load_worker_settings()
    config.validate(ai)
    if not config.database_url:
        raise ValueError('WORKER_DATABASE_URL is required')
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with GroqTextAnalyzer(ai) as analyzer:
            processor = AnalysisProcessor(WorkerJobs(config.database_url), analyzer, ai, config)
            await run_loop(processor, stop, once=once)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main() -> int:
    parser = argparse.ArgumentParser(description='Process durable PostgreSQL analysis jobs')
    parser.add_argument('--once', action='store_true', help='Process at most one job, then exit')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(once=args.once))
    except (ValueError, AnalysisError, JobUnavailable):
        logger.error('analysis_worker startup_or_database_failure')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

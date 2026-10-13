"""Bounded read-only source worker. Run separately from AI and import workers."""
import argparse
import logging
import os
import signal
import threading
from app.integrations.sources.settings import load_source_settings, PROVIDERS
from app.config import load_github_settings
from app.models.source_connections import SourceJobs, SourceStateError
from app.services.source_sync import SourceProcessor


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--once',action='store_true'); args=parser.parse_args()
    settings=load_source_settings()
    if not settings.enabled: raise ValueError('Sources are not enabled')
    database_url=os.getenv('WORKER_DATABASE_URL')
    if not database_url: raise ValueError('WORKER_DATABASE_URL is required')
    try: github=load_github_settings()
    except ValueError: github=None
    providers=[x for x in PROVIDERS if settings.configured(x) and (x!='github' or github)]
    jobs=SourceJobs(database_url); processor=SourceProcessor(jobs,settings,github)
    stop=threading.Event()
    for name in (signal.SIGINT,signal.SIGTERM): signal.signal(name,lambda *_:stop.set())
    while not stop.is_set():
        job=None
        try:
            job=jobs.claim(providers)
            if job: processor.process(job)
        except SourceStateError as error:
            logging.getLogger(__name__).warning('Source worker: %s',error.code)
        except Exception:
            # No provider body, document content, token or credential URL in logs.
            logging.getLogger(__name__).error('Source worker operation failed')
        if args.once: break
        if not job: stop.wait(3)


if __name__=='__main__': main()

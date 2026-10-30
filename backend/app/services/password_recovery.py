"""Bounded in-process mail admission; HTTP never waits for account lookup or SMTP."""

from concurrent.futures import ThreadPoolExecutor
import logging
from threading import BoundedSemaphore

logger = logging.getLogger(__name__)


class RecoveryDispatcher:
    def __init__(self, *, workers: int = 4, capacity: int = 32):
        self._slots = BoundedSemaphore(capacity)
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="flare-recovery")

    def submit(self, function, *args) -> bool:
        if not self._slots.acquire(blocking=False):
            return False
        try:
            future = self._executor.submit(self._run, function, args)
        except RuntimeError:
            self._slots.release()
            return False
        # Also release cancelled queued jobs during shutdown.
        future.add_done_callback(lambda _future: self._slots.release())
        return True

    @staticmethod
    def _run(function, args):
        try:
            function(*args)
        except Exception:
            # Account addresses, provider errors and links must never reach logs.
            logger.warning("password_recovery_job_failed")

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

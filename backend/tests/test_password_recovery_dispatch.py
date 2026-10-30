from threading import Event

from app.services.password_recovery import RecoveryDispatcher


def test_dispatcher_bounds_queued_work_recovers_capacity_and_sanitizes_logs(caplog):
    dispatcher = RecoveryDispatcher(workers=1, capacity=1)
    started, release = Event(), Event()

    def blocked():
        started.set()
        assert release.wait(5)
        raise RuntimeError("private@example.invalid secret-token")

    try:
        assert dispatcher.submit(blocked)
        assert started.wait(5)
        assert not dispatcher.submit(lambda: None)
    finally:
        release.set()
        dispatcher.close()
    assert "password_recovery_job_failed" in caplog.text
    assert "private@" not in caplog.text and "secret-token" not in caplog.text
    assert not dispatcher.submit(lambda: None)


def test_cancelled_queued_jobs_release_admission_slots():
    dispatcher = RecoveryDispatcher(workers=1, capacity=3)
    started, release = Event(), Event()
    def work():
        started.set()
        assert release.wait(5)
    try:
        assert dispatcher.submit(work)
        assert started.wait(5)
        assert dispatcher.submit(lambda: None)
        assert dispatcher.submit(lambda: None)
        assert not dispatcher.submit(lambda: None)
        dispatcher._executor.shutdown(wait=False, cancel_futures=True)
    finally:
        release.set()
        dispatcher.close()
    for _ in range(3):
        assert dispatcher._slots.acquire(blocking=False)
    assert not dispatcher._slots.acquire(blocking=False)

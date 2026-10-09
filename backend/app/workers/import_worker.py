"""Dedicated durable import worker; imports no AI/provider or Analyze executor.

Run from backend/: python -m app.workers.import_worker --mode jobs|cleanup [--once]
Production uses the explicitly enabled, bounded PostgreSQL staging adapter.
"""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import threading
import time

import psycopg
from psycopg.rows import dict_row
from app.import_staging import LocalStagedObjects
from app.import_staging.policy import ImportPolicy
from app.models.import_packages import ImportWorkerJobs, ImportPackageError


class ImportProcessor:
    def __init__(self, jobs, storage, policy=None, stop=None):
        self.jobs, self.storage, self.policy = jobs,storage,policy or ImportPolicy()
        self.stop = stop

    def check_stop(self):
        if self.stop is not None and self.stop.is_set():
            raise ImportWorkerStopped

    def decode(self, job, source, action, ordinal=None):
        policy = ImportPolicy(**job['policy'])
        timeout = policy.inspect_seconds if action=='manifest' else policy.file_seconds
        # Output/ZIP share the explicitly bounded scratch budget; paths are
        # server-generated and private, never taken from an archive entry.
        output_limit = min(policy.scratch_bytes-job['file_size'],
            policy.manifest_bytes+100 if action=='manifest' else policy.file_bytes*8+100_000)
        if output_limit<100:
            raise ImportPackageError('scratch_bound')
        with tempfile.TemporaryFile() as output:
            request = {'fd':source.fileno(),'action':action,'ordinal':ordinal,'policy':asdict(policy),'outputLimit':output_limit}
            source.seek(0)
            child = subprocess.Popen([sys.executable,'-m','app.workers.import_subprocess'],
                stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,pass_fds=(source.fileno(),),
                env={'PYTHONPATH':str(Path(__file__).resolve().parents[2])})
            try:
                child.stdin.write(json.dumps(request).encode())
                child.stdin.close()
                started, heartbeat = time.monotonic(),time.monotonic()
                memory_check = started
                while child.poll() is None:
                    self.check_stop()
                    if sys.platform == 'darwin' and time.monotonic()-memory_check>=0.25:
                        usage=subprocess.run(['/bin/ps','-o','rss=','-p',str(child.pid)],capture_output=True,text=True,timeout=1)
                        if usage.stdout.strip() and int(usage.stdout.strip())*1024>policy.memory_bytes:
                            raise ImportPackageError('decoder_memory_limit')
                        memory_check=time.monotonic()
                    if time.monotonic()-started>timeout:
                        raise ImportPackageError('decode_deadline')
                    if time.monotonic()-heartbeat>=max(0.1,policy.lease_seconds/3):
                        self.jobs.step(job,'heartbeat')
                        heartbeat=time.monotonic()
                    time.sleep(0.02)
                if child.returncode:
                    raise ImportPackageError('decoder_resource_limit')
                output.seek(0)
                result=json.loads(output.read(output_limit+1))
                if result.get('error'):
                    raise ImportPackageError(result['error'])
                self.jobs.step(job,'heartbeat')
                return result
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait()

    def process_one(self):
        job=self.jobs.claim(self.policy.global_concurrency)
        if not job:
            return None
        if job.get('expired'):
            return 'expired'
        policy=ImportPolicy(**job['policy'])
        current_ordinal=None
        started=time.monotonic()
        cpu_start=resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            # One bounded immutable object copy is verified on every restart.
            # No database transaction stays open while this storage I/O runs.
            storage = self.storage.for_job(job) if hasattr(self.storage, 'for_job') else self.storage
            with tempfile.TemporaryFile() as source, storage.reader(job['object_key']) as original:
                count,digest,heartbeat=0,hashlib.sha256(),time.monotonic()
                for block in iter(lambda: original.read(64*1024),b''):
                    self.check_stop()
                    count+=len(block)
                    if count>min(policy.compressed_bytes,policy.scratch_bytes):
                        raise ImportPackageError('compressed_bytes')
                    source.write(block); digest.update(block)
                    if time.monotonic()-started>policy.inspect_seconds:
                        raise ImportPackageError('inspect_deadline')
                    if time.monotonic()-heartbeat>=max(0.1,policy.lease_seconds/3):
                        self.jobs.step(job,'heartbeat'); heartbeat=time.monotonic()
                if count!=job['file_size'] or digest.hexdigest()!=job['archive_hash']:
                    raise ImportPackageError('object_integrity')
                rows=self.decode(job,source,'manifest')['manifest']
                self.jobs.step(job,'manifest',rows)
                while True:
                    self.check_stop()
                    cpu=resource.getrusage(resource.RUSAGE_CHILDREN)
                    if time.monotonic()-started>policy.job_seconds or cpu.ru_utime+cpu.ru_stime-cpu_start.ru_utime-cpu_start.ru_stime>policy.cpu_seconds:
                        raise ImportPackageError('job_resource_limit')
                    next_step=self.jobs.step(job,'next')
                    current_ordinal=next_step.get('entry',{}).get('ordinal')
                    if next_step.get('entry'):
                        result=self.decode(job,source,'file',next_step['entry']['ordinal'])
                        self.jobs.step(job,'entry',result)
                    elif 'publish' in next_step:
                        self.jobs.step(job,'publish',{'ordinal':next_step['publish']})
                    else:
                        self.jobs.step(job,'gate')
                        return 'completed'
        except ImportWorkerStopped:
            # Leave provisional work fenced by its lease; another worker can
            # resume after expiry. A shutdown is not package rejection/success.
            return 'stopped'
        except ImportPackageError as error:
            if error.code=='lease_lost':
                return 'lease_lost'
            try: self.jobs.step(job,'reject',{'code':error.code,'ordinal':current_ordinal})
            except ImportPackageError: pass
            return 'failed'
        except (OSError,subprocess.SubprocessError):
            try: self.jobs.step(job,'transient',{'code':'storage_or_worker_unavailable'})
            except ImportPackageError: pass
            return 'retry_wait'

    def cleanup_one(self):
        obj=self.jobs.cleanup()
        if not obj:
            return None
        try:
            self.jobs.cleanup('check',obj['key'],obj['cleanup_token'])
            # Keys are unique per upload attempt and never reused. A stale
            # delete can only touch an already-terminal, quarantined object;
            # all database completion writes remain token/expiry fenced.
            self.check_stop()
            storage = self.storage.for_cleanup(obj) if hasattr(self.storage, 'for_cleanup') else self.storage
            storage.delete(obj['key'])
            self.jobs.cleanup('done',obj['key'],obj['cleanup_token'])
            return 'deleted'
        except OSError:
            self.jobs.cleanup('retry',obj['key'],obj['cleanup_token'])
            return 'cleanup_retry'
        except ImportPackageError:
            return 'lease_lost'
        except ImportWorkerStopped:
            return 'stopped'


class ImportWorkerStopped(Exception):
    """Stop between bounded operations without changing a leased package."""


@dataclass(frozen=True)
class ImportRuntimeSettings:
    database_url: str
    provider: str
    staging_root: str | None
    heartbeat_dir: str | None
    policy: ImportPolicy
    poll_seconds: int = 1


def load_import_runtime() -> ImportRuntimeSettings:
    environment = os.getenv('FLARE_ENV', 'production')
    if environment not in {'production', 'development', 'test'}:
        raise ValueError('Invalid import environment')
    production = environment == 'production'
    enabled = os.getenv('FLARE_IMPORT_ENABLED', 'false' if production else 'true')
    if enabled != 'true':
        raise ValueError('Import worker must be explicitly enabled')
    database_url = os.getenv('WORKER_DATABASE_URL', '')
    provider = os.getenv('FLARE_IMPORT_STORAGE_PROVIDER', '' if production else 'local')
    staging_root = os.getenv('FLARE_IMPORT_STAGING_ROOT')
    heartbeat_dir = os.getenv('FLARE_WORKER_HEARTBEAT_DIR')
    concurrency = os.getenv('FLARE_IMPORT_WORKER_CONCURRENCY', '' if production else '1')
    if not database_url or concurrency != '1':
        raise ValueError('Restricted worker database and concurrency=1 are required')
    if provider not in {'local', 'postgres'} or (production and provider != 'postgres'):
        raise ValueError('Production imports require PostgreSQL staging')
    if provider == 'local' and not staging_root:
        raise ValueError('Local staging root is required')
    if production and not heartbeat_dir:
        raise ValueError('Private worker heartbeat directory is required')
    policy = ImportPolicy.from_environment(production=production)
    if provider == 'postgres':
        policy.validate_postgres()
    return ImportRuntimeSettings(database_url, provider, staging_root, heartbeat_dir, policy)


class RuntimeImportWorkerJobs(ImportWorkerJobs):
    """Keep even idle claim/cleanup and role probes bounded during shutdown."""

    def connection(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=3,
            options='-c statement_timeout=30000 -c lock_timeout=3000')


def create_processor(settings: ImportRuntimeSettings, stop: threading.Event) -> ImportProcessor:
    if settings.provider == 'postgres':
        from app.import_staging.postgres import PostgresStagedObjects
        storage = PostgresStagedObjects(settings.database_url)
        storage.probe()
    else:
        storage = LocalStagedObjects(settings.staging_root)
    return ImportProcessor(RuntimeImportWorkerJobs(settings.database_url), storage, settings.policy, stop)


def record_heartbeat(directory: str | None, mode: str) -> None:
    if directory is None:
        return
    if mode not in {'jobs', 'cleanup'}:
        raise ValueError('Invalid import consumer mode')
    private = Path(directory)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    if private.is_symlink() or private.stat().st_uid != os.getuid():
        raise ValueError('Worker heartbeat directory must be private and owned')
    private.chmod(0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=private, prefix=f'.{mode}-', delete=False) as output:
        path = Path(output.name)
        try:
            json.dump({'checked_at': time.monotonic()}, output)
            output.flush()
            os.replace(path, private / f'{mode}.json')
        finally:
            path.unlink(missing_ok=True)


def update_heartbeat(processor: ImportProcessor, settings: ImportRuntimeSettings, mode: str) -> None:
    if settings.provider == 'postgres':
        # Database readiness requires a recent successful restricted operation;
        # a live PID or a failed poll must never renew it.
        processor.storage.heartbeat(mode)
    record_heartbeat(settings.heartbeat_dir, mode)


def run_loop(processor: ImportProcessor, settings: ImportRuntimeSettings,
             stop: threading.Event, *, mode: str, once: bool = False) -> int:
    if mode not in {'jobs', 'cleanup'}:
        raise ValueError('Invalid import consumer mode')
    update_heartbeat(processor, settings, mode)
    operation = processor.process_one if mode == 'jobs' else processor.cleanup_one
    while not stop.is_set():
        try:
            result = operation()
            if stop.is_set():
                break
            update_heartbeat(processor, settings, mode)
            if result:
                logging.info('import_worker mode=%s outcome=%s', mode, result)
        except (psycopg.Error, OSError):
            # Database/storage exceptions can contain DSNs or row values.
            logging.error('import_worker mode=%s database_or_storage_unavailable', mode)
            if once:
                return 1
        if once:
            return 0
        stop.wait(settings.poll_seconds)
    return 0


def main():
    parser=argparse.ArgumentParser(description='Process bounded durable ZIP imports or staging cleanup')
    parser.add_argument('--mode', choices=('jobs', 'cleanup'), default='jobs')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        handlers[sig] = signal.signal(sig, lambda *_: stop.set())
    settings = None
    try:
        settings = load_import_runtime()
        processor = create_processor(settings, stop)
        return run_loop(processor, settings, stop, mode=args.mode, once=args.once)
    except (ValueError, ImportPackageError, psycopg.Error, OSError):
        logging.error('import_worker startup_or_runtime_failure')
        return 1
    finally:
        if settings and settings.heartbeat_dir:
            try:
                (Path(settings.heartbeat_dir) / f'{args.mode}.json').unlink(missing_ok=True)
            except OSError:
                logging.error('import_worker heartbeat_cleanup_unavailable')
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__=='__main__':
    raise SystemExit(main())

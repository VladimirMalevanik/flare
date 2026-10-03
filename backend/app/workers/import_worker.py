"""Dedicated durable import worker; imports no AI/provider or Analyze executor.

Run from backend/: python -m app.workers.import_worker [--once]
Production requires an injected OPS-approved storage adapter; this CLI is local/test.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import logging
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

import psycopg
from app.import_staging import LocalStagedObjects
from app.import_staging.policy import ImportPolicy
from app.models.import_packages import ImportWorkerJobs, ImportPackageError


class ImportProcessor:
    def __init__(self, jobs, storage, policy=None):
        self.jobs, self.storage, self.policy = jobs,storage,policy or ImportPolicy()

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
            with tempfile.TemporaryFile() as source, self.storage.reader(job['object_key']) as original:
                count,digest,heartbeat=0,hashlib.sha256(),time.monotonic()
                for block in iter(lambda: original.read(64*1024),b''):
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
            self.storage.delete(obj['key'])
            self.jobs.cleanup('done',obj['key'],obj['cleanup_token'])
            return 'deleted'
        except OSError:
            self.jobs.cleanup('retry',obj['key'],obj['cleanup_token'])
            return 'cleanup_retry'
        except ImportPackageError:
            return 'lease_lost'


def main():
    parser=argparse.ArgumentParser(description='Process durable local/test ZIP imports')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if os.getenv('FLARE_ENV','production') not in {'development','test'}:
        raise ValueError('Production imports require OPS-approved adapter/worker wiring')
    url=os.getenv('WORKER_DATABASE_URL'); root=os.getenv('FLARE_IMPORT_STAGING_ROOT')
    if not url or not root:
        raise ValueError('WORKER_DATABASE_URL and FLARE_IMPORT_STAGING_ROOT are required')
    processor=ImportProcessor(ImportWorkerJobs(url),LocalStagedObjects(root),ImportPolicy.from_environment())
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            result=processor.process_one(); cleaned=processor.cleanup_one()
            if result or cleaned: logging.info('import_worker outcome=%s cleanup=%s',result,cleaned)
        except psycopg.Error:
            logging.error('import_worker database_unavailable')
            if args.once: return 1
        if args.once: return 0
        time.sleep(1)


if __name__=='__main__':
    raise SystemExit(main())

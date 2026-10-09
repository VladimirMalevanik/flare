"""Lease-bound, bounded temporary ZIP streams over private SQL capabilities.

Connections and transactions are short; no connection survives between blocks.
The permanent import_objects row, rather than Python cancellation, fences writers.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import re
import threading

import psycopg
from app.models.import_packages import ImportPackageError

BLOCK_BYTES = 256 * 1024
MAX_BYTES = 8 * 1024 * 1024
_KEY = re.compile(r'[0-9a-f]{32}-[0-9a-f]{32}\Z')
_ERRORS = frozenset(('forbidden', 'authorization_revoked', 'lease_lost', 'compressed_bytes',
                     'staged_quota', 'integrity_failure', 'object_exists', 'invalid_action'))


@dataclass(frozen=True)
class PostgresStagedObjects:
    dsn: str = field(repr=False)
    _mode: str | None = None
    _key: str | None = None
    _identity: object = None
    _token: object = field(default=None, repr=False)
    _job_id: object = None
    _generation: object = None

    def for_upload(self, identity, key, upload_token):
        self._validate_key(key)
        return replace(self, _mode='upload', _key=key, _identity=identity,
                       _token=upload_token, _job_id=None, _generation=None)

    def for_job(self, job):
        self._validate_key(job['object_key'])
        return replace(self, _mode='job', _key=job['object_key'], _identity=None,
                       _token=job['lease_token'], _job_id=job['id'], _generation=job['generation'])

    def for_cleanup(self, obj):
        self._validate_key(obj['key'])
        return replace(self, _mode='cleanup', _key=obj['key'], _identity=None,
                       _token=obj['cleanup_token'], _job_id=None, _generation=None)

    @staticmethod
    def _validate_key(key):
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError('Invalid staged object key')

    def _bound(self, mode, key):
        self._validate_key(key)
        if self._mode != mode or key != self._key or self._token is None:
            raise ImportPackageError('lease_lost')

    def _call(self, function, parameters=(), role=None):
        """Map database failures to fixed codes; never expose a DSN or SQL detail."""
        try:
            with psycopg.connect(self.dsn, connect_timeout=3,
                                options='-c statement_timeout=5000 -c lock_timeout=2000',
                                application_name='flare-import-staging') as connection:
                safe = connection.execute('''SELECT rolname, NOT rolsuper AND NOT rolbypassrls
                    AND NOT rolcreatedb AND NOT rolcreaterole AND NOT EXISTS
                    (SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
                    FROM pg_roles WHERE rolname=current_user''').fetchone()
                if not safe or not safe[1] or safe[0] not in ('flare_app', 'flare_worker') or (role and safe[0] != role):
                    raise ImportPackageError('forbidden')
                if self._mode == 'upload':
                    connection.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",
                                       (str(self._identity.workspace_id), self._identity.user_id))
                placeholders = ','.join(['%s'] * len(parameters))
                return connection.execute(f'SELECT public.{function}({placeholders})', parameters).fetchone()[0]
        except psycopg.Error as error:
            code = error.diag.message_primary if error.sqlstate == 'P0001' else None
            if code in _ERRORS:
                raise ImportPackageError(code) from None
            raise OSError('storage_unavailable') from None

    def probe(self):
        if not self._call('import_staging_probe'):
            raise OSError('storage_unavailable')
        return True

    def heartbeat(self, mode):
        if mode not in ('jobs', 'cleanup'):
            raise ValueError('Invalid import consumer mode')
        self._call('import_staging_heartbeat', (mode,), 'flare_worker')

    def ready(self):
        return self._call('import_staging_ready', role='flare_app') is True

    def _upload(self, action, ordinal=None, data=None):
        return self._call('import_staging_upload', (self._key, self._token, action, ordinal, data), 'flare_app')

    @contextmanager
    def writer(self, key):
        self._bound('upload', key)
        size = self._upload('begin')['bytes']
        stream = _Writer(self, size)
        try:
            yield stream
            stream.finish()
        finally:
            # Wait for a late to_thread write to finish, then discard any buffered
            # suffix. A cancelled upload is never completed by context teardown.
            stream.close()

    def size(self, key):
        self._bound('job', key)
        return self._call('import_staging_size', (key, self._job_id, self._token, self._generation), 'flare_worker')

    @contextmanager
    def reader(self, key):
        size = self.size(key)
        stream = _Reader(self, size)
        try:
            yield stream
        finally:
            stream.close()

    def _read(self, ordinal):
        return self._call('import_staging_read',
                          (self._key, self._job_id, self._token, self._generation, ordinal), 'flare_worker')

    def delete(self, key):
        self._bound('cleanup', key)
        self._call('import_staging_retire', (key, self._token), 'flare_worker')


class _Writer:
    def __init__(self, storage, size):
        self.storage, self.size = storage, size
        self._lock = threading.RLock()
        self._buffer = bytearray()
        self._ordinal = self._count = 0
        self.closed = False

    def _flush(self):
        if self._buffer:
            self.storage._upload('append', self._ordinal, bytes(self._buffer))
            self._ordinal += 1
            self._buffer.clear()

    def write(self, data):
        with self._lock:
            if self.closed:
                raise ValueError('Write to closed staged object')
            source = memoryview(data).cast('B')
            if self._count + len(source) > self.size or self.size > MAX_BYTES:
                raise ImportPackageError('compressed_bytes')
            self._count += len(source)
            offset = 0
            while offset < len(source):
                length = min(BLOCK_BYTES - len(self._buffer), len(source) - offset)
                self._buffer.extend(source[offset:offset + length])
                offset += length
                if len(self._buffer) == BLOCK_BYTES:
                    self._flush()
            return len(source)

    def finish(self):
        with self._lock:
            if self.closed:
                raise ValueError('Finish closed staged object')
            if self._count != self.size:
                raise ImportPackageError('integrity_failure')
            self._flush()
            self.storage._upload('finish')
            self.closed = True

    def close(self):
        with self._lock:
            self.closed = True
            self._buffer.clear()


class _Reader:
    def __init__(self, storage, size):
        self.storage, self.size = storage, size
        self._lock = threading.RLock()
        self._buffer = b''
        self._ordinal = self._count = 0
        self.closed = False

    def read(self, length=-1):
        # Worker spool uses 64KiB reads. Enforce a memory bound even for accidental
        # read-all calls; ZIP parsing receives the separate seekable scratch file.
        if not isinstance(length, int) or length < 0 or length > BLOCK_BYTES:
            raise ValueError('Staged reads require a size between 0 and 262144')
        with self._lock:
            if self.closed:
                raise ValueError('Read from closed staged object')
            # Revalidate even buffered data and EOF after cancellation/revocation.
            self.storage.size(self.storage._key)
            result = bytearray()
            while len(result) < length and self._count < self.size:
                if not self._buffer:
                    block = self.storage._read(self._ordinal)
                    if block is None or not 0 < len(block) <= BLOCK_BYTES:
                        raise ImportPackageError('integrity_failure')
                    self._buffer = bytes(block)
                    self._ordinal += 1
                take = min(length - len(result), len(self._buffer), self.size - self._count)
                result.extend(self._buffer[:take])
                self._buffer = self._buffer[take:]
                self._count += take
            return bytes(result)

    def close(self):
        with self._lock:
            self.closed = True
            self._buffer = b''

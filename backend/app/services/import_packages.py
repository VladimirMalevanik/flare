"""Session/upload/finalize orchestration. No analysis or provider dependency."""
import asyncio
from dataclasses import asdict
import hashlib
import re
from uuid import UUID
from app.import_staging.policy import ImportPolicy
from app.models.import_packages import ImportPackages, ImportPackageError


class ImportPackageService:
    def __init__(self, repository: ImportPackages, storage, policy: ImportPolicy):
        self.repo, self.storage, self.policy = repository, storage, policy

    def create(self, *, source_kind, file_name, file_size, request_key):
        if not self.storage:
            raise ImportPackageError('storage_unavailable')
        if source_kind not in {'notion','obsidian'} or not re.fullmatch(r'[^/\\\x00-\x1f\x7f]{1,255}\.zip', file_name, flags=re.I):
            raise ImportPackageError('invalid_file')
        if len(file_name.encode('utf-8'))>255:
            raise ImportPackageError('invalid_file')
        result = self.repo.action('create', payload={'sourceKind':source_kind,'fileName':file_name,'fileSize':file_size,
            'requestKey':str(request_key),'policy':asdict(self.policy)})
        package = self.repo.get(UUID(result['id']))
        # SQL serializes workspace/key admission and persists immutable caller
        # identity. Check its winner, including concurrent retries, before replay.
        # Server policy may change between retries; it is not request identity.
        if (package['source_kind'], package['file_name'], package['file_size']) != (source_kind, file_name, file_size):
            raise ImportPackageError('request_key_conflict')
        return package

    async def upload(self, package_id, stream):
        if not self.storage:
            raise ImportPackageError('storage_unavailable')
        claim = await asyncio.to_thread(self.repo.action, 'upload_claim', package_id)
        policy = ImportPolicy(**claim['policy'])
        count, digest = 0, hashlib.sha256()
        try:
            # The adapter performs bounded writes; no body() or multipart buffer.
            with self.storage.writer(claim['key']) as target:
                async with asyncio.timeout(policy.upload_seconds):
                    async for block in stream:
                        count += len(block)
                        if count>policy.compressed_bytes or count>claim['fileSize']:
                            raise ImportPackageError('compressed_bytes')
                        digest.update(block)
                        await asyncio.to_thread(target.write, block)
                if count!=claim['fileSize']:
                    raise ImportPackageError('upload_size')
            await asyncio.to_thread(self.repo.action, 'upload_done', package_id,
                {'token':claim['token'],'bytes':count,'hash':digest.hexdigest()})
        except BaseException:
            # Object was recorded before writing. Even a disconnect/crash leaves
            # a durable cleanup obligation, including incomplete .part files.
            await asyncio.shield(asyncio.to_thread(self.repo.action,'upload_abort',package_id,{'token':claim['token']}))
            raise
        return await asyncio.to_thread(self.repo.get, package_id)

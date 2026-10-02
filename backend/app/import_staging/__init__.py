"""Private immutable staged objects; production adapters are an OPS decision."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import BinaryIO, Iterator, Protocol


class StagedObjects(Protocol):
    def writer(self, key: str): ...
    def reader(self, key: str): ...
    def delete(self, key: str) -> None: ...
    def size(self, key: str) -> int: ...


class LocalStagedObjects:
    """Explicit local/test backend. Server keys only, no archive paths, no symlink following.

    Root must be a private directory shared by the local API and import worker.
    No production topology or retention guarantee is inferred from this backend.
    """
    def __init__(self, root: str | Path):
        root = Path(root).absolute()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
            raise ValueError("Staging root must be a private directory")
        self.root = root

    def _open_root(self):
        return os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    @staticmethod
    def _name(key: str):
        if not re.fullmatch(r"[0-9a-f]{32}-[0-9a-f]{32}", key):
            raise ValueError("Invalid staged object key")
        return key + ".zip"

    @contextmanager
    def writer(self, key: str) -> Iterator[BinaryIO]:
        name = self._name(key)
        root = self._open_root()
        temp = name + ".part"
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
            with os.fdopen(fd, "wb") as stream:
                yield stream
                stream.flush()
                os.fsync(stream.fileno())
            # link creates the immutable destination exclusively; overwrite is impossible.
            os.link(temp, name, src_dir_fd=root, dst_dir_fd=root, follow_symlinks=False)
            os.fsync(root)
        finally:
            try:
                os.unlink(temp, dir_fd=root)
            except FileNotFoundError:
                pass
            os.close(root)

    @contextmanager
    def reader(self, key: str) -> Iterator[BinaryIO]:
        root = self._open_root()
        try:
            fd = os.open(self._name(key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                os.close(fd)
                raise OSError("Staged objects must be regular files")
            with os.fdopen(fd, "rb") as stream:
                yield stream
        finally:
            os.close(root)

    def size(self, key: str) -> int:
        with self.reader(key) as stream:
            return os.fstat(stream.fileno()).st_size

    def delete(self, key: str) -> None:
        root = self._open_root()
        try:
            for name in (self._name(key), self._name(key) + ".part"):
                try:
                    os.unlink(name, dir_fd=root)
                except FileNotFoundError:
                    pass
            os.fsync(root)
        finally:
            os.close(root)


def object_digest(objects: StagedObjects, key: str, maximum: int) -> tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    with objects.reader(key) as stream:
        while block := stream.read(64 * 1024):
            size += len(block)
            if size > maximum:
                raise ValueError("compressed_bytes")
            digest.update(block)
    return size, digest.hexdigest()

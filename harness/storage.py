"""Local single-writer ownership and durable atomic JSON replacement."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading


class StateConflict(RuntimeError):
    pass


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class StateLock:
    def __init__(self, state_path: Path):
        self.path = state_path.with_name(state_path.name + ".lock")
        self._owner = None
        self._guard = threading.RLock()

    @contextmanager
    def acquire(self):
        if not self._guard.acquire(blocking=False):
            raise StateConflict(f"State is owned by another thread: {self.path}")
        try:
            if self._owner == threading.get_ident():
                yield self
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise StateConflict(f"State is owned by another Patron process: {self.path}") from exc
                self._owner = threading.get_ident()
                try:
                    yield self
                finally:
                    self._owner = None
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._guard.release()

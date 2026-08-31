from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


_SECRET_REF = re.compile(r"\{\{secret:([A-Za-z0-9_.-]{1,100})\}\}")
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _shared_lock(path: Path) -> threading.RLock:
    """Return one process-local lock for every physical vault data path.

    DPN AI normally owns one SecretVault instance, but tests, maintenance tools,
    and future services may construct more than one object for the same vault.
    Sharing the lock by resolved data path prevents lost updates between those
    instances as well as between threads using one instance.
    """
    key = os.path.normcase(str(path.absolute()))
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


class SecretVault:
    """Encrypted local secret store. Secret values are never returned by list operations."""

    def __init__(self, key_path: Path, data_path: Path):
        self.key_path = key_path
        self.data_path = data_path
        self._lock = _shared_lock(self.data_path)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self._reject_unsafe_paths()
        with self._lock:
            if not self.key_path.exists():
                key = Fernet.generate_key()
                try:
                    fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(key)
                        handle.flush()
                        os.fsync(handle.fileno())
            self._reject_unsafe_paths()
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            self.fernet = Fernet(self.key_path.read_bytes().strip())

    def _reject_unsafe_paths(self) -> None:
        for label, path in (("vault key", self.key_path), ("vault data", self.data_path)):
            if path.is_symlink():
                raise ValueError(f"Secret {label} path cannot be a symlink")
            parent = path.parent
            if parent.is_symlink():
                raise ValueError(f"Secret {label} parent directory cannot be a symlink")
            # Reject a symlink anywhere in an already-existing ancestor chain.
            current = parent
            while current != current.parent:
                if current.exists() and current.is_symlink():
                    raise ValueError(f"Secret {label} path cannot traverse a symlink")
                current = current.parent

    def _load(self) -> dict[str, str]:
        self._reject_unsafe_paths()
        if not self.data_path.exists():
            return {}
        try:
            data = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Secret vault data is unreadable or corrupted; refusing to continue") from exc
        if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            raise ValueError("Secret vault data has an invalid structure; refusing to continue")
        return data

    def _save(self, data: dict[str, str]) -> None:
        self._reject_unsafe_paths()
        payload = json.dumps(data, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.data_path.name}.", suffix=".tmp", dir=self.data_path.parent)
        temp_path = Path(temp_name)
        try:
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            # A symlink could be planted after the earlier check but before
            # replace(). Recheck the destination immediately before the atomic
            # replacement so DPN AI never intentionally follows one.
            if self.data_path.is_symlink():
                raise ValueError("Secret vault data path cannot be a symlink")
            os.replace(temp_path, self.data_path)
            try:
                os.chmod(self.data_path, 0o600)
            except OSError:
                pass
            if os.name == "posix":
                try:
                    dir_fd = os.open(self.data_path.parent, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except OSError:
                    pass
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def set(self, name: str, value: str) -> dict[str, Any]:
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
            return {"ok": False, "error": "Invalid secret name"}
        with self._lock:
            data = self._load()
            data[name] = self.fernet.encrypt(value.encode("utf-8")).decode("ascii")
            self._save(data)
        return {"ok": True, "name": name}

    def get_value(self, name: str) -> str:
        with self._lock:
            token = self._load().get(name)
            if not token:
                raise KeyError(f"Secret not found: {name}")
            try:
                return self.fernet.decrypt(token.encode("ascii")).decode("utf-8")
            except InvalidToken as exc:
                raise ValueError(f"Secret cannot be decrypted: {name}") from exc

    def delete(self, name: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            existed = name in data
            if existed:
                data.pop(name, None)
                self._save(data)
        return {"ok": True, "deleted": existed}

    def list(self) -> dict[str, Any]:
        with self._lock:
            return {"ok": True, "secrets": sorted(self._load())}

    def resolve(self, value: Any) -> Any:
        # RLock is intentional: nested structures may recurse and each secret
        # substitution calls get_value(), which acquires the same shared lock.
        with self._lock:
            if isinstance(value, str):
                return _SECRET_REF.sub(lambda match: self.get_value(match.group(1)), value)
            if isinstance(value, list):
                return [self.resolve(item) for item in value]
            if isinstance(value, dict):
                return {key: self.resolve(item) for key, item in value.items()}
            return value

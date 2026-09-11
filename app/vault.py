from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


_SECRET_REF = re.compile(r"\{\{secret:([A-Za-z0-9_.-]{1,100})\}\}")
_DPAPI_PREFIX = b"DPN-AI-DPAPI1:"
_LOCKS_GUARD = threading.Lock()


def _windows_dpapi_protect(payload: bytes) -> bytes:
    """Protect bytes to the current Windows user without storing another key."""
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is unavailable on this platform")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    input_blob = DATA_BLOB(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = DATA_BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "DPN AI SecretVault master key",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "Windows DPAPI could not protect the DPN AI vault key")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _windows_dpapi_unprotect(payload: bytes) -> bytes:
    """Unprotect bytes previously bound to the current Windows user."""
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is unavailable on this platform")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    input_blob = DATA_BLOB(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = DATA_BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "Windows DPAPI could not unprotect the DPN AI vault key")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _encode_master_key_for_storage(key: bytes) -> bytes:
    if os.name != "nt":
        return key
    protected = _windows_dpapi_protect(key)
    return _DPAPI_PREFIX + base64.b64encode(protected)


def _decode_master_key_from_storage(stored: bytes) -> tuple[bytes, bool]:
    """Return (raw Fernet key, needs_windows_migration)."""
    if stored.startswith(_DPAPI_PREFIX):
        if os.name != "nt":
            raise ValueError("This vault key is protected by Windows DPAPI and can only be opened by its Windows user")
        encoded = stored[len(_DPAPI_PREFIX):]
        try:
            protected = base64.b64decode(encoded, validate=True)
            key = _windows_dpapi_unprotect(protected)
        except (ValueError, OSError) as exc:
            raise ValueError("Windows could not unlock the DPN AI SecretVault master key") from exc
        return key, False
    return stored, os.name == "nt"

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
                raw_key = Fernet.generate_key()
                stored_key = _encode_master_key_for_storage(raw_key)
                try:
                    fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(stored_key)
                        handle.flush()
                        os.fsync(handle.fileno())
            self._reject_unsafe_paths()
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass

            stored_key = self.key_path.read_bytes().strip()
            raw_key, migrate_windows_key = _decode_master_key_from_storage(stored_key)
            try:
                self.fernet = Fernet(raw_key)
            except (TypeError, ValueError) as exc:
                raise ValueError("Secret vault master key is invalid; refusing to continue") from exc

            # Legacy Windows vaults stored the Fernet key directly because chmod
            # does not provide a Unix-style owner-only boundary on NTFS. Once the
            # existing key has been validated, rewrap it with current-user DPAPI
            # and atomically replace only the key file. Vault ciphertext remains
            # unchanged because the underlying Fernet key does not rotate.
            if migrate_windows_key:
                self._replace_key_file(_encode_master_key_for_storage(raw_key))

    def _replace_key_file(self, payload: bytes) -> None:
        self._reject_unsafe_paths()
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.key_path.name}.", suffix=".tmp", dir=self.key_path.parent)
        temp_path = Path(temp_name)
        try:
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if self.key_path.is_symlink():
                raise ValueError("Secret vault key path cannot be a symlink")
            os.replace(temp_path, self.key_path)
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

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

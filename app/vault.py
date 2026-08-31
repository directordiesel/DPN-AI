from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


_SECRET_REF = re.compile(r"\{\{secret:([A-Za-z0-9_.-]{1,100})\}\}")


class SecretVault:
    """Encrypted local secret store. Secret values are never returned by list operations."""

    def __init__(self, key_path: Path, data_path: Path):
        self.key_path = key_path
        self.data_path = data_path
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
        self.fernet = Fernet(self.key_path.read_bytes().strip())

    def _load(self) -> dict[str, str]:
        if not self.data_path.exists():
            return {}
        try:
            data = json.loads(self.data_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self.data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(self.data_path, 0o600)
        except OSError:
            pass

    def set(self, name: str, value: str) -> dict[str, Any]:
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
            return {"ok": False, "error": "Invalid secret name"}
        data = self._load()
        data[name] = self.fernet.encrypt(value.encode("utf-8")).decode("ascii")
        self._save(data)
        return {"ok": True, "name": name}

    def get_value(self, name: str) -> str:
        token = self._load().get(name)
        if not token:
            raise KeyError(f"Secret not found: {name}")
        try:
            return self.fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(f"Secret cannot be decrypted: {name}") from exc

    def delete(self, name: str) -> dict[str, Any]:
        data = self._load()
        existed = name in data
        data.pop(name, None)
        self._save(data)
        return {"ok": True, "deleted": existed}

    def list(self) -> dict[str, Any]:
        return {"ok": True, "secrets": sorted(self._load())}

    def resolve(self, value: Any) -> Any:
        if isinstance(value, str):
            return _SECRET_REF.sub(lambda match: self.get_value(match.group(1)), value)
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: self.resolve(item) for key, item in value.items()}
        return value
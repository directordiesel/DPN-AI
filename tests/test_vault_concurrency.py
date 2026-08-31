from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.vault import SecretVault


def test_two_vault_instances_share_mutation_lock(tmp_path: Path) -> None:
    key = tmp_path / "data" / "vault.key"
    data = tmp_path / "data" / "vault.json"
    first = SecretVault(key, data)
    second = SecretVault(key, data)

    assert first._lock is second._lock

    first_inside_save = threading.Event()
    release_first_save = threading.Event()
    second_entered_load = threading.Event()
    errors: list[BaseException] = []

    original_first_save = first._save
    original_second_load = second._load

    def blocked_save(values):
        first_inside_save.set()
        if not release_first_save.wait(timeout=5):
            raise TimeoutError("test did not release first vault save")
        return original_first_save(values)

    def observed_load():
        second_entered_load.set()
        return original_second_load()

    first._save = blocked_save  # type: ignore[method-assign]
    second._load = observed_load  # type: ignore[method-assign]

    def write(vault: SecretVault, name: str, value: str) -> None:
        try:
            vault.set(name, value)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread_one = threading.Thread(target=write, args=(first, "approval.one", "alpha"))
    thread_two = threading.Thread(target=write, args=(second, "approval.two", "beta"))
    thread_one.start()
    assert first_inside_save.wait(timeout=5)
    thread_two.start()

    # While the first load-modify-save transaction holds the shared RLock, the
    # second instance must not even enter its load phase.
    assert second_entered_load.wait(timeout=0.2) is False
    release_first_save.set()
    thread_one.join(timeout=5)
    thread_two.join(timeout=5)

    assert not thread_one.is_alive()
    assert not thread_two.is_alive()
    assert errors == []
    assert second_entered_load.is_set()
    assert first.get_value("approval.one") == "alpha"
    assert first.get_value("approval.two") == "beta"


def test_delete_does_not_rewrite_vault_when_secret_missing(tmp_path: Path) -> None:
    vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
    vault.set("keep", "value")
    before = vault.data_path.read_bytes()
    result = vault.delete("absent")
    assert result == {"ok": True, "deleted": False}
    assert vault.data_path.read_bytes() == before


def test_vault_rejects_symlinked_data_file(tmp_path: Path) -> None:
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "vault.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="symlink"):
        SecretVault(tmp_path / "vault.key", link)


def test_vault_rejects_symlinked_key_file(tmp_path: Path) -> None:
    real_key_vault = SecretVault(tmp_path / "real.key", tmp_path / "seed.json")
    real_key = real_key_vault.key_path
    linked_key = tmp_path / "linked.key"
    try:
        linked_key.symlink_to(real_key)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="symlink"):
        SecretVault(linked_key, tmp_path / "other.json")

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "validate_release_request.py"
SPEC = importlib.util.spec_from_file_location("validate_release_request", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_stable_release_requires_exact_tag_and_stable_flag():
    assert module.validate_release_request(
        repository_version="9.0.0",
        requested_tag="v9.0.0",
        prerelease=False,
    ) == "v9.0.0"


def test_release_rejects_loose_or_mismatched_tag():
    with pytest.raises(ValueError, match="exactly match"):
        module.validate_release_request(
            repository_version="9.0.0",
            requested_tag="v9",
            prerelease=False,
        )

    with pytest.raises(ValueError, match="exactly match"):
        module.validate_release_request(
            repository_version="9.0.0",
            requested_tag="v9.0.1",
            prerelease=False,
        )


def test_stable_version_cannot_be_marked_prerelease():
    with pytest.raises(ValueError, match="expected false"):
        module.validate_release_request(
            repository_version="9.0.0",
            requested_tag="v9.0.0",
            prerelease=True,
        )


def test_prerelease_version_requires_prerelease_flag():
    assert module.validate_release_request(
        repository_version="9.1.0-rc.1",
        requested_tag="v9.1.0-rc.1",
        prerelease=True,
    ) == "v9.1.0-rc.1"

    with pytest.raises(ValueError, match="expected true"):
        module.validate_release_request(
            repository_version="9.1.0-rc.1",
            requested_tag="v9.1.0-rc.1",
            prerelease=False,
        )


def test_invalid_repository_semver_fails_closed():
    for invalid in ("9", "9.0", "09.0.0", "9.0.0-01", ""):
        with pytest.raises(ValueError):
            module.validate_release_request(
                repository_version=invalid,
                requested_tag=f"v{invalid}",
                prerelease=False,
            )


def test_parse_bool_is_strict_but_case_insensitive():
    assert module.parse_bool("true") is True
    assert module.parse_bool("FALSE") is False
    with pytest.raises(ValueError, match="exactly true or false"):
        module.parse_bool("1")

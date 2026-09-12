#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import re
import sys
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)$")
INCLUDE_RE = re.compile(r"^(?:-r|--requirement)\s+(.+)$")
RELEASE_PYTHON = (3, 12, 10)


def _logical_lines(path: Path) -> list[str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"requirements file is missing or unsafe: {path}")
    result: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            result.append(line)
    return result


def load_lock(path: Path) -> dict[str, str]:
    locked: dict[str, str] = {}
    for line in _logical_lines(path):
        match = PIN_RE.fullmatch(line)
        if not match:
            raise ValueError(f"release lock contains a non-exact requirement: {line}")
        name, raw_version = match.groups()
        canonical = canonicalize_name(name)
        if canonical in locked:
            raise ValueError(f"release lock contains a duplicate package: {name}")
        try:
            version = str(Version(raw_version))
        except InvalidVersion as exc:
            raise ValueError(f"release lock contains an invalid version: {line}") from exc
        if version != raw_version:
            raise ValueError(f"release lock version is not canonical: {line}")
        locked[canonical] = version
    if not locked:
        raise ValueError("release lock is empty")
    return locked


def load_declared(path: Path, *, seen: set[Path] | None = None) -> list[Requirement]:
    resolved = path.resolve()
    visited = seen if seen is not None else set()
    if resolved in visited:
        return []
    visited.add(resolved)
    declared: list[Requirement] = []
    for line in _logical_lines(path):
        include = INCLUDE_RE.fullmatch(line)
        if include:
            child = (path.parent / include.group(1).strip()).resolve()
            declared.extend(load_declared(child, seen=visited))
            continue
        if line.startswith("-"):
            raise ValueError(f"unsupported requirements option in {path}: {line}")
        try:
            requirement = Requirement(line)
        except InvalidRequirement as exc:
            raise ValueError(f"invalid requirement in {path}: {line}") from exc
        if requirement.url is not None:
            raise ValueError(f"direct URL dependencies are not allowed in release requirements: {line}")
        declared.append(requirement)
    return declared


def verify_declared_requirements(locked: dict[str, str], declared: list[Requirement]) -> None:
    failures: list[str] = []
    for requirement in declared:
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        name = canonicalize_name(requirement.name)
        version = locked.get(name)
        if version is None:
            failures.append(f"{requirement.name}: missing from release lock")
            continue
        if requirement.specifier and Version(version) not in requirement.specifier:
            failures.append(f"{requirement.name}: locked {version} does not satisfy {requirement.specifier}")
    if failures:
        raise ValueError("release lock does not satisfy declared requirements: " + "; ".join(failures))


def verify_installed(locked: dict[str, str]) -> None:
    failures: list[str] = []
    installed: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            installed[canonicalize_name(name)] = distribution.version
    for name, expected in locked.items():
        actual = installed.get(name)
        if actual != expected:
            failures.append(f"{name}: expected {expected}, installed {actual or 'missing'}")
    unexpected = sorted(set(installed) - set(locked) - {"pip"})
    if unexpected:
        failures.append("unexpected distributions in release environment: " + ", ".join(unexpected))
    if failures:
        raise ValueError("installed release environment does not match lock: " + "; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DPN AI's exact production release dependency lock.")
    parser.add_argument("--lock", type=Path, default=Path("requirements-release.lock"))
    parser.add_argument("--requirements", type=Path, default=Path("requirements-build.txt"))
    parser.add_argument("--verify-installed", action="store_true")
    parser.add_argument("--require-windows-python312", action="store_true")
    args = parser.parse_args()

    if args.require_windows_python312:
        if sys.platform != "win32" or sys.version_info[:3] != RELEASE_PYTHON:
            required = ".".join(str(part) for part in RELEASE_PYTHON)
            actual = ".".join(str(part) for part in sys.version_info[:3])
            raise SystemExit(
                f"Production release builds require Windows and CPython {required}; got {sys.platform} CPython {actual}."
            )

    locked = load_lock(args.lock)
    declared = load_declared(args.requirements)
    verify_declared_requirements(locked, declared)
    if args.verify_installed:
        verify_installed(locked)
    print(f"Release dependency lock PASS: {len(locked)} exact packages; {len(declared)} declared requirements validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version


def logical_requirements(path: Path) -> list[Requirement]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"requirements file is missing or unsafe: {path}")
    requirements: list[Requirement] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        if requirement.url is not None:
            raise ValueError(f"direct URL dependency is not allowed: {line}")
        if len(requirement.specifier) != 1 or "==" not in str(requirement.specifier):
            raise ValueError(f"release requirement must be exactly pinned: {line}")
        requirements.append(requirement)
    if not requirements:
        raise ValueError("release requirements are empty")
    return requirements


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_wheels(requirements_path: Path, wheelhouse: Path) -> list[Path]:
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--no-deps",
        "--only-binary=:all:",
        "--dest",
        str(wheelhouse),
        "-r",
        str(requirements_path),
    ]
    subprocess.run(command, check=True)
    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda path: path.name.lower())
    if not wheels:
        raise ValueError("pip produced no release wheels")
    unexpected = sorted(path.name for path in wheelhouse.iterdir() if path.is_file() and path.suffix != ".whl")
    if unexpected:
        raise ValueError("release wheelhouse contains non-wheel artifacts: " + ", ".join(unexpected))
    return wheels


def build_hash_lock(requirements_path: Path, wheels: list[Path]) -> str:
    requirements = logical_requirements(requirements_path)
    expected = {
        canonicalize_name(requirement.name): (
            requirement.name,
            next(iter(requirement.specifier)).version,
        )
        for requirement in requirements
    }
    resolved: dict[str, tuple[str, str, str]] = {}

    for wheel in wheels:
        name, version, _build, _tags = parse_wheel_filename(wheel.name)
        canonical = canonicalize_name(name)
        if canonical not in expected:
            raise ValueError(f"unexpected wheel in release wheelhouse: {wheel.name}")
        expected_name, expected_version = expected[canonical]
        if Version(str(version)) != Version(expected_version):
            raise ValueError(
                f"wheel version mismatch for {expected_name}: expected {expected_version}, got {version}"
            )
        if canonical in resolved:
            raise ValueError(f"multiple wheels resolved for release dependency: {expected_name}")
        resolved[canonical] = (expected_name, expected_version, sha256_file(wheel))

    missing = sorted(set(expected) - set(resolved))
    if missing:
        raise ValueError("release wheelhouse is missing dependencies: " + ", ".join(missing))

    lines = [
        "# DPN AI Windows CPython 3.12 x64 production wheel hash lock",
        "# Generated from requirements-release.lock on the GitHub-hosted Windows release toolchain.",
        "# Production installs must use --require-hashes --no-deps --only-binary=:all:.",
    ]
    for requirement in requirements:
        canonical = canonicalize_name(requirement.name)
        name, version, digest = resolved[canonical]
        lines.append(f"{name}=={version} --hash=sha256:{digest}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify the DPN AI Windows release wheel hash lock.")
    parser.add_argument("--requirements", type=Path, default=Path("requirements-release.lock"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()

    if sys.platform != "win32" or sys.version_info[:3] != (3, 12, 10):
        raise SystemExit("Windows release wheel hashing requires Windows CPython 3.12.10.")

    with tempfile.TemporaryDirectory(prefix="dpn-release-wheelhouse-") as temp_dir:
        wheelhouse = Path(temp_dir)
        wheels = resolve_wheels(args.requirements, wheelhouse)
        generated = build_hash_lock(args.requirements, wheels)

    if args.check:
        if args.output.is_symlink() or not args.output.is_file():
            raise SystemExit(f"Committed release wheel hash lock is missing or unsafe: {args.output}")
        committed = args.output.read_text(encoding="utf-8")
        if committed != generated:
            if args.emit:
                print("DPN_RELEASE_HASH_LOCK_BEGIN")
                print(generated, end="")
                print("DPN_RELEASE_HASH_LOCK_END")
            raise SystemExit("Committed release wheel hash lock does not match freshly resolved Windows wheels.")
        print(f"Release wheel hash lock PASS: {len(logical_requirements(args.requirements))} dependencies.")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generated, encoding="utf-8")
    if args.emit:
        print("DPN_RELEASE_HASH_LOCK_BEGIN")
        print(generated, end="")
        print("DPN_RELEASE_HASH_LOCK_END")
    print(f"Generated release wheel hash lock: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

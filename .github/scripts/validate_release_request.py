from __future__ import annotations

import argparse
import re

SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("prerelease must be exactly true or false")


def validate_release_request(*, repository_version: str, requested_tag: str, prerelease: bool) -> str:
    version = repository_version.strip()
    if not version:
        raise ValueError("repository VERSION is empty")
    if SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"repository VERSION is not valid SemVer: {version!r}")

    expected_tag = f"v{version}"
    if requested_tag != expected_tag:
        raise ValueError(
            f"release tag {requested_tag!r} does not exactly match repository VERSION; expected {expected_tag!r}"
        )

    parsed = SEMVER_RE.fullmatch(version)
    assert parsed is not None
    version_is_prerelease = parsed.group("prerelease") is not None
    if version_is_prerelease != prerelease:
        expected = "true" if version_is_prerelease else "false"
        raise ValueError(
            f"prerelease flag is inconsistent with VERSION {version!r}; expected {expected}"
        )

    return expected_tag


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a DPN AI release dispatch against repository VERSION.")
    parser.add_argument("--version", required=True, help="Repository VERSION value")
    parser.add_argument("--tag", required=True, help="Requested Git tag, including leading v")
    parser.add_argument("--prerelease", required=True, help="GitHub dispatch prerelease boolean")
    args = parser.parse_args()

    try:
        validated = validate_release_request(
            repository_version=args.version,
            requested_tag=args.tag,
            prerelease=parse_bool(args.prerelease),
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(f"Validated release request: {validated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

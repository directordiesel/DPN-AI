#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

REPOSITORY = "directordiesel/DPN-AI"
KEY_ID = "release-ed25519-v1"


def build_trust_root(public_key_hex: str) -> dict[str, object]:
    value = str(public_key_hex or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("DPN_UPDATE_ED25519_PUBLIC_KEY_HEX must be exactly 64 hexadecimal characters")
    raw = bytes.fromhex(value)
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "key_id": KEY_ID,
        "ed25519_public_key_hex": value,
        "public_key_sha256": hashlib.sha256(raw).hexdigest(),
    }


def write_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the public DPN AI desktop update trust root.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_trust_root(os.getenv("DPN_UPDATE_ED25519_PUBLIC_KEY_HEX", ""))
    write_atomic(args.output, payload)
    print(f"Update trust root prepared for {payload['repository']} using {payload['key_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""DPN AI installer runtime probe.

Kept as a standalone file so Windows PowerShell 5.1 never has to quote or
re-parse a multiline Python program passed through ``python -c``.
"""
from __future__ import annotations

import struct
import sys


def main() -> int:
    version = sys.version_info
    bits = struct.calcsize("P") * 8
    executable = sys.executable
    supported = version >= (3, 11) and bits == 64
    status = "DPN_PYTHON_OK" if supported else "DPN_PYTHON_UNSUPPORTED"
    print(
        f"{status}|{version.major}.{version.minor}.{version.micro}|{bits}|{executable}",
        flush=True,
    )
    return 0 if supported else 9


if __name__ == "__main__":
    raise SystemExit(main())
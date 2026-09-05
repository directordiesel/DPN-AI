"""DPN AI v8 desktop launcher entrypoint.

This entrypoint is intended to be packaged as a Windows GUI executable. It starts
the supervised local DPN AI service without opening a browser or console window.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from desktop.platform import DesktopMode, DesktopRuntimePolicy, ServiceEndpoint
from desktop.supervisor import DesktopServiceSupervisor, SupervisorConfig


def _health_check(endpoint: ServiceEndpoint) -> bool:
    url = f"http://{endpoint.host}:{endpoint.port}/health"
    try:
        with urlopen(Request(url, method="GET"), timeout=1.0) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DPN AI Desktop Platform launcher")
    parser.add_argument("--safe-mode", action="store_true", help="Start local-only safe mode")
    parser.add_argument("--diagnostic", action="store_true", help="Start diagnostic mode")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.safe_mode and args.diagnostic:
        raise SystemExit("safe mode and diagnostic mode are mutually exclusive")

    mode = DesktopMode.SAFE if args.safe_mode else DesktopMode.DIAGNOSTIC if args.diagnostic else DesktopMode.NORMAL
    endpoint = ServiceEndpoint(port=args.port)
    policy = DesktopRuntimePolicy(
        mode=mode,
        endpoint=endpoint,
        allow_remote=False,
        allow_cloud=mode is DesktopMode.NORMAL,
    )
    repository_root = Path(__file__).resolve().parents[1]
    supervisor = DesktopServiceSupervisor(
        SupervisorConfig(repository_root=repository_root),
        policy,
        health_check=lambda: _health_check(endpoint),
    )

    try:
        snapshot = supervisor.start()
    except Exception:
        return 2
    if snapshot.state.value != "healthy":
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())

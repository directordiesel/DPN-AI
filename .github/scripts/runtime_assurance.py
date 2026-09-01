#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.getenv("DPN_ASSURANCE_PORT", "18787"))
TOKEN = "DPN-PHASE3-RUNTIME-ASSURANCE-TOKEN"
BASE_URL = f"http://127.0.0.1:{PORT}"


def request(path: str, *, token: str | None = None) -> tuple[int, bytes, dict[str, str]]:
    headers = {}
    if token is not None:
        headers["X-DPN-Token"] = token
    req = urllib.request.Request(BASE_URL + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def wait_ready(proc: subprocess.Popen[str], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"DPN AI exited during startup with code {proc.returncode}\n{last}")
        try:
            code, body, _ = request("/api/health", token=TOKEN)
            if code == 200:
                payload = json.loads(body.decode("utf-8"))
                if payload.get("app") != "DPN AI":
                    raise RuntimeError("health payload did not identify DPN AI")
                return
            last = f"health returned {code}: {body[:300]!r}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"DPN AI did not become ready: {last}")


def start(env: dict[str, str]) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_ready(proc)
    return proc


def stop(proc: subprocess.Popen[str]) -> str:
    if proc.poll() is None:
        if os.name == "nt":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    output = proc.stdout.read() if proc.stdout else ""
    if proc.returncode not in (0, -signal.SIGTERM if os.name != "nt" else 1):
        raise RuntimeError(f"unexpected DPN AI shutdown code {proc.returncode}\n{output}")
    return output


def expect_corrupt_db_failure(env: dict[str, str], database: Path) -> None:
    backup = database.with_suffix(".phase3-backup")
    shutil.copy2(database, backup)
    database.write_bytes(b"this-is-not-a-sqlite-database\x00phase3")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import app.main"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("corrupt database import did not fail closed")
    output = proc.stdout.read() if proc.stdout else ""
    if proc.returncode == 0:
        raise RuntimeError(f"corrupt database was accepted/replaced instead of failing closed\n{output}")
    if database.read_bytes() == b"":
        raise RuntimeError("corrupt database was unexpectedly truncated")
    shutil.copy2(backup, database)
    backup.unlink(missing_ok=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dpn-ai-phase3-") as temp:
        temp_root = Path(temp)
        data_dir = temp_root / "data"
        workspace_dir = temp_root / "workspace"
        skills_dir = temp_root / "skills"
        plugins_dir = temp_root / "plugins"
        voice_dir = temp_root / "voices"
        for directory in (data_dir, workspace_dir, skills_dir, plugins_dir, voice_dir):
            directory.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update({
            "DPN_HOST": "127.0.0.1",
            "DPN_PORT": str(PORT),
            "DPN_ACCESS_TOKEN": TOKEN,
            "DPN_DATA_DIR": str(data_dir),
            "DPN_WORKSPACE_DIR": str(workspace_dir),
            "DPN_SKILLS_DIR": str(skills_dir),
            "DPN_PLUGINS_DIR": str(plugins_dir),
            "DPN_VOICE_DIR": str(voice_dir),
            "DPN_VAULT_KEY": str(data_dir / "vault.key"),
            "DPN_KEEP_MODEL_LOADED": "0",
            "DPN_ALLOW_WEB": "0",
            "DPN_ALLOW_COMMANDS": "0",
            "DPN_ALLOW_CONNECTORS": "0",
            "DPN_ALLOW_MCP": "0",
        })

        first = start(env)
        code, _, _ = request("/api/health")
        if code != 401:
            raise RuntimeError(f"missing-token health request returned {code}, expected 401")
        code, _, _ = request("/api/health", token="wrong-token")
        if code != 401:
            raise RuntimeError(f"wrong-token health request returned {code}, expected 401")
        code, body, _ = request("/api/health", token=TOKEN)
        if code != 200 or json.loads(body.decode("utf-8")).get("version") is None:
            raise RuntimeError("authorized health request failed")
        code, body, headers = request("/")
        if code != 200 or b"DPN" not in body.upper():
            raise RuntimeError("static dashboard smoke test failed")
        stop(first)

        database = data_dir / "dpn_ai.sqlite3"
        if not database.is_file() or database.stat().st_size == 0:
            raise RuntimeError("runtime database was not created")

        second = start(env)
        code, _, _ = request("/api/health", token=TOKEN)
        if code != 200:
            raise RuntimeError("restart health check failed")
        stop(second)

        expect_corrupt_db_failure(env, database)

        recovered = start(env)
        code, _, _ = request("/api/health", token=TOKEN)
        if code != 200:
            raise RuntimeError("restored database did not recover successfully")
        stop(recovered)

        repo_runtime_db = ROOT / "data" / "dpn_ai.sqlite3"
        if repo_runtime_db.exists():
            raise RuntimeError("runtime assurance leaked database state into repository data/")

    print("DPN AI Phase 3 runtime/recovery assurance PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

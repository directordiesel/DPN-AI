#!/usr/bin/env python3
"""DPN Security Gate v2.

High-confidence repository security checks intended to block dangerous source,
tracked secrets/runtime state, unsafe symlinks, weak cryptography, and risky
command/deserialization primitives before code reaches main.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml",
    ".toml", ".ini", ".cfg", ".conf", ".env", ".md", ".txt", ".html", ".css", ".sh",
    ".ps1", ".bat", ".cmd", ".sql",
}
CODE_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
SKIP_PREFIXES = (".git/", ".venv/", "venv/", "node_modules/", "dist/", "build/", "vendor/")
TEST_PREFIXES = ("tests/", "test/", "fixtures/", "examples/")
ENV_TEMPLATE_NAMES = {".env.example", ".env.sample", ".env.template"}

SENSITIVE_PATH_RE = re.compile(
    r"(^|/)(\.env|\.env\..+|FIRST_RUN_LOGIN\.txt|id_rsa|id_ed25519|.*\.(?:p12|pfx|key|pem)|"
    r"(?:vault|master)[^/]*\.key|data/.*\.(?:sqlite|sqlite3|db|enc)|backups?/.*)$",
    re.IGNORECASE,
)
PRIVATE_KEY_MARKERS = (
    "-----BEGIN " + "PRIVATE KEY-----",
    "-----BEGIN RSA " + "PRIVATE KEY-----",
    "-----BEGIN EC " + "PRIVATE KEY-----",
    "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
)
TOKEN_PATTERNS = (
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*[\"']([^\"']{12,})[\"']"
)
PLACEHOLDER_WORDS = ("example", "placeholder", "changeme", "change-me", "dummy", "sample", "test-only", "your_")
JS_DANGEROUS = (
    ("dynamic eval", re.compile(r"\beval\s*\(")),
    ("dynamic Function constructor", re.compile(r"\bnew\s+Function\s*\(")),
    ("child_process exec", re.compile(r"\b(?:exec|execSync)\s*\(")),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT)


def tracked_files() -> list[str]:
    return [p for p in git("ls-files").splitlines() if p and not p.startswith(SKIP_PREFIXES)]


def read_text(path: str) -> str | None:
    p = ROOT / path
    if p.suffix.lower() not in TEXT_EXTENSIONS and p.name not in {"Dockerfile", "Makefile"}:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def line_for(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def is_test_path(path: str) -> bool:
    return path.startswith(TEST_PREFIXES) or "/tests/" in path or "/fixtures/" in path


def scan_paths(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if Path(path).name.lower() in ENV_TEMPLATE_NAMES:
            continue
        if SENSITIVE_PATH_RE.search(path):
            findings.append(Finding(path, 1, "tracked-sensitive-file", "sensitive/runtime file must not be tracked"))

    stage = git("ls-files", "--stage")
    for row in stage.splitlines():
        parts = row.split(maxsplit=3)
        if len(parts) != 4 or parts[0] != "120000":
            continue
        path = parts[3]
        try:
            target = (ROOT / path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        normalized = os.path.normpath(os.path.join(os.path.dirname(path), target))
        if os.path.isabs(target) or normalized == ".." or normalized.startswith("../"):
            findings.append(Finding(path, 1, "unsafe-symlink", f"symlink escapes repository: {target}"))
    return findings


def scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for marker in PRIVATE_KEY_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            findings.append(Finding(path, line_for(text, idx), "private-key", "private key material is tracked"))

    for label, pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(Finding(path, line_for(text, match.start()), "credential-token", f"possible {label} is tracked"))

    if path.endswith(tuple(CODE_EXTENSIONS)) and not is_test_path(path):
        for match in CREDENTIAL_ASSIGNMENT_RE.finditer(text):
            value = match.group(2).lower()
            if not any(word in value for word in PLACEHOLDER_WORDS):
                findings.append(
                    Finding(path, line_for(text, match.start()), "hardcoded-credential", f"hard-coded {match.group(1)}-like value")
                )

    if Path(path).suffix.lower() in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"} and not is_test_path(path):
        for rule, pattern in JS_DANGEROUS:
            for match in pattern.finditer(text):
                findings.append(Finding(path, line_for(text, match.start()), rule, "dangerous dynamic execution primitive"))
    return findings


def dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def scan_python(path: str, text: str) -> list[Finding]:
    if is_test_path(path):
        return []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return []  # syntax belongs to the normal CI compile gate

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func)
        line = getattr(node, "lineno", 1)
        if name in {"eval", "exec"}:
            findings.append(Finding(path, line, "dynamic-python-exec", f"{name}() is not allowed in production code"))
        elif name == "os.system":
            findings.append(Finding(path, line, "os-system", "use subprocess with an argument array instead of os.system()"))
        elif name in {"pickle.load", "pickle.loads", "marshal.load", "marshal.loads"}:
            findings.append(Finding(path, line, "unsafe-deserialization", f"{name}() can execute or load unsafe data"))
        elif name in {"hashlib.md5", "hashlib.sha1"}:
            findings.append(Finding(path, line, "weak-crypto", f"{name}() is prohibited; use SHA-256 or stronger"))
        elif name.startswith("subprocess."):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    findings.append(Finding(path, line, "subprocess-shell", "subprocess shell=True is prohibited"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github", action="store_true", help="emit GitHub Actions annotations")
    args = parser.parse_args()

    try:
        paths = tracked_files()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"DPN Security Gate: unable to enumerate tracked files: {exc}", file=sys.stderr)
        return 2

    findings = scan_paths(paths)
    scanned = 0
    for path in paths:
        text = read_text(path)
        if text is None:
            continue
        scanned += 1
        findings.extend(scan_text(path, text))
        if path.endswith(".py"):
            findings.extend(scan_python(path, text))

    unique = sorted(set(findings), key=lambda f: (f.path, f.line, f.rule, f.message))
    if unique:
        for f in unique:
            if args.github:
                safe = f.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                print(f"::error file={f.path},line={f.line},title=DPN Security Gate [{f.rule}]::{safe}")
            else:
                print(f"{f.path}:{f.line}: [{f.rule}] {f.message}")
        print(f"DPN Security Gate v2: FAILED — {len(unique)} finding(s) across {scanned} text file(s).")
        return 1

    print(f"DPN Security Gate v2: PASS — {scanned} tracked text file(s) scanned; no blocking findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

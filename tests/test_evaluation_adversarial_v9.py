import hashlib
import math

import pytest

from app.api_v2_contracts import APIV2ContractError, APIV2Envelope, decode_cursor, encode_cursor, validate_envelope
from app.evaluation_v9 import EvaluationCase, EvaluationError, MAX_EVALUATION_CASES, run_evaluations
from app.recovery_verification_v9 import RecoveryFileEntry, RecoveryManifest, validate_manifest


def test_evaluation_harness_reports_pass_fail_and_secret_free_errors():
    secret = "TOP-SECRET-CREDENTIAL"

    def explode() -> bool:
        raise RuntimeError(secret)

    summary = run_evaluations(
        (
            EvaluationCase("api-pass", "api", lambda: True),
            EvaluationCase("regression-fail", "regression", lambda: False),
            EvaluationCase("security-error", "security", explode),
        )
    )

    assert summary.total == 3
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.errors == 1
    assert summary.pass_rate == pytest.approx(1 / 3)
    payload = summary.payload()
    assert secret not in repr(payload)
    assert payload["results"][2]["error_type"] == "RuntimeError"


def test_evaluation_harness_rejects_duplicate_names_and_resource_abuse():
    duplicate = EvaluationCase("same", "api", lambda: True)
    with pytest.raises(EvaluationError, match="duplicate"):
        run_evaluations((duplicate, duplicate))
    with pytest.raises(EvaluationError, match="max_cases"):
        run_evaluations((), max_cases=True)
    with pytest.raises(EvaluationError, match="configured limit"):
        run_evaluations(
            tuple(EvaluationCase(f"case-{index}", "regression", lambda: True) for index in range(3)),
            max_cases=2,
        )
    assert MAX_EVALUATION_CASES == 1000


def test_api_v2_cursor_mutations_fail_closed():
    token = encode_cursor(sequence=9, stream="chat.events")
    mutations = (
        token[:-1] + ("A" if token[-1] != "A" else "B"),
        "%%%not-base64%%%",
        "A" * 2049,
        "",
    )
    for mutated in mutations:
        with pytest.raises(APIV2ContractError):
            decode_cursor(mutated)


def test_api_v2_envelope_rejects_nonfinite_and_malformed_values():
    cases = (
        APIV2Envelope("2.0", 0, "Chat.Delta", {}, {}),
        APIV2Envelope("2.0", -1, "chat.delta", {}, {}),
        APIV2Envelope("2.0", 0, "chat.delta", {"score": math.inf}, {}),
        APIV2Envelope("2.0", 0, "chat.delta", {"score": math.nan}, {}),
        APIV2Envelope("1.0", 0, "chat.delta", {}, {}),
    )
    for envelope in cases:
        with pytest.raises(APIV2ContractError):
            validate_envelope(envelope)


def test_recovery_manifest_path_adversaries_fail_closed():
    digest = hashlib.sha256(b"x").hexdigest()
    malicious_paths = (
        "../escape.txt",
        "/absolute.txt",
        "C:/windows/system32/file.txt",
        "folder/../escape.txt",
        "folder/./file.txt",
        "",
        "bad\x00name.txt",
    )
    for path in malicious_paths:
        manifest = RecoveryManifest(
            schema_version=1,
            app_version="9.0.0",
            files=(RecoveryFileEntry(path=path, sha256=digest, size=1),),
        )
        result = validate_manifest(manifest)
        assert result.ok is False
        assert result.errors


def test_recovery_manifest_detects_duplicate_and_invalid_digest_mutations():
    digest = hashlib.sha256(b"x").hexdigest()
    manifest = RecoveryManifest(
        schema_version=1,
        app_version="9.0.0",
        files=(
            RecoveryFileEntry(path="safe/file.txt", sha256=digest, size=1),
            RecoveryFileEntry(path="safe/file.txt", sha256=digest, size=1),
            RecoveryFileEntry(path="safe/other.txt", sha256="A" * 64, size=1),
        ),
    )
    result = validate_manifest(manifest)
    assert result.ok is False
    assert any("duplicate recovery path" in error for error in result.errors)
    assert any("invalid SHA-256 digest" in error for error in result.errors)

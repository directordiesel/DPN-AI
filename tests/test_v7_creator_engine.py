from plugins.creator_engine_v7 import build_creation_plan, evaluate_creation_evidence


def test_creation_plan_requires_objective():
    result = build_creation_plan("")
    assert result["ok"] is False


def test_creation_plan_normalizes_and_bounds_artifacts():
    result = build_creation_plan(
        "Create a client launch package",
        artifacts=[
            {"kind": "document", "name": "proposal", "purpose": "scope"},
            {"kind": "spreadsheet", "name": "roi", "purpose": "financial model", "depends_on": ["proposal"]},
            {"kind": "unknown", "name": "fallback"},
        ],
        brand={"theme": "black-purple"},
        max_artifacts=2,
    )
    assert result["ok"] is True
    assert result["engine"] == "dpn-creator-engine-v7"
    assert len(result["artifacts"]) == 2
    assert result["artifacts"][0]["kind"] == "document"
    assert result["artifacts"][1]["kind"] == "spreadsheet"
    assert result["brand"]["theme"] == "black-purple"
    assert result["policy"]["open_and_inspect_outputs"] is True
    assert result["policy"]["no_fake_validation"] is True


def test_creation_evidence_rejects_missing_or_uninspected_outputs():
    result = evaluate_creation_evidence([
        {"path": "workspace/generated/report.pdf", "kind": "pdf", "exists": True, "inspected": False, "valid": True, "evidence": "pdf parser"},
    ])
    assert result["ready"] is False
    assert result["failed_or_unverified"] == ["workspace/generated/report.pdf"]


def test_creation_evidence_accepts_verified_outputs():
    result = evaluate_creation_evidence([
        {"path": "workspace/generated/report.pdf", "kind": "pdf", "exists": True, "inspected": True, "valid": True, "evidence": {"pages": 4}},
        {"path": "workspace/generated/budget.xlsx", "kind": "spreadsheet", "exists": True, "inspected": True, "valid": True, "evidence": {"sheets": 3}},
    ])
    assert result["ready"] is True
    assert all(item["passed"] for item in result["artifacts"])


def test_creation_evidence_requires_at_least_one_artifact():
    result = evaluate_creation_evidence([])
    assert result["ready"] is False

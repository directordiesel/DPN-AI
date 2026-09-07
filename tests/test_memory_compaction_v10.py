from __future__ import annotations

import json

import pytest

from app.advanced_layered_memory_v10 import AdvancedLayeredMemory
from app.memory_compaction_v10 import MemoryCompactionError, MemoryCompactionService
from app.memory_service import MemoryService


class FakeDB:
    def __init__(self):
        self.semantic_items: list[dict] = []
        self.fail_list = False

    def list_semantic_items(self, namespace, limit=5000):
        if self.fail_list:
            raise RuntimeError("db down")
        return [item for item in self.semantic_items if item.get("namespace") == namespace][:limit]


class FakeSemantic:
    pass


def item(memory_id, *, namespace="project:p1", layer="semantic", key="region", content="Detroit", source_type="test", content_hash=None):
    return {
        "id": memory_id,
        "namespace": namespace,
        "content": content,
        "metadata": {
            "v10_memory_schema": 1,
            "v10_layer": layer,
            "v10_logical_key": key,
            "v10_content_hash": content_hash,
            "v10_provenance": {"source_type": source_type},
        },
    }


def receipt(memory_id, replacement, targets, *, namespace="project:p1", layer="semantic", key="region"):
    payload = {
        "schema_version": 1,
        "decision": "supersedes",
        "layer": layer,
        "logical_key": key,
        "replacement_memory_id": replacement,
        "superseded_memory_ids": list(targets),
        "reason": "newer verified evidence",
    }
    return item(
        memory_id,
        namespace=namespace,
        layer="procedural",
        key=f"supersession:{key}",
        content=json.dumps(payload),
        source_type="memory_supersession",
    )


@pytest.fixture
def service():
    db = FakeDB()
    runtime = AdvancedLayeredMemory(MemoryService(db, FakeSemantic()))
    return MemoryCompactionService(runtime), db


def test_exact_duplicate_versions_collapse_to_one_canonical_read_identity(service):
    compact, db = service
    hash_value = "samehash"
    db.semantic_items = [
        item("m2", content="Detroit", content_hash=hash_value),
        item("m1", content="Detroit", content_hash=hash_value),
    ]
    report = compact.analyze("project:p1")
    assert report.canonical_items == ("m1",)
    assert report.duplicate_groups == (("m1", "m2"),)
    assert report.preferred_memory_ids == ("m1",)
    assert report.recovery_required is False


def test_valid_supersession_hides_old_version_from_preferred_view_without_deleting_it(service):
    compact, db = service
    db.semantic_items = [
        item("old", content="Detroit"),
        item("new", content="Chicago"),
        receipt("r1", "new", ["old"]),
    ]
    report = compact.analyze("project:p1")
    assert "old" in report.superseded_memory_ids
    assert "new" in report.preferred_memory_ids
    assert "old" not in report.preferred_memory_ids
    assert {entry["id"] for entry in db.semantic_items} == {"old", "new", "r1"}
    assert report.recovery_required is False
    assert report.to_dict()["destructive_mutation"] is False


def test_cross_lineage_receipt_is_ignored_and_flagged_for_recovery(service):
    compact, db = service
    db.semantic_items = [
        item("old", key="region", content="Detroit"),
        item("new", key="timezone", content="Eastern"),
        receipt("r1", "new", ["old"], key="region"),
    ]
    report = compact.analyze("project:p1")
    assert report.invalid_receipt_ids == ("r1",)
    assert report.recovery_required is True
    assert set(report.preferred_memory_ids) == {"old", "new"}


def test_dangling_receipt_never_changes_preferred_view(service):
    compact, db = service
    db.semantic_items = [
        item("old"),
        receipt("r1", "missing", ["old"]),
    ]
    report = compact.analyze("project:p1")
    assert report.dangling_receipt_ids == ("r1",)
    assert report.preferred_memory_ids == ("old",)
    assert report.recovery_required is True


def test_cycle_is_detected_and_cycle_nodes_are_not_marked_superseded(service):
    compact, db = service
    db.semantic_items = [
        item("a", content="A"),
        item("b", content="B"),
        receipt("r1", "b", ["a"]),
        receipt("r2", "a", ["b"]),
    ]
    report = compact.analyze("project:p1")
    assert report.cycle_memory_ids == ("a", "b")
    assert report.superseded_memory_ids == ()
    assert set(report.preferred_memory_ids) == {"a", "b"}
    assert report.recovery_required is True


def test_malformed_supersession_receipt_is_fail_closed(service):
    compact, db = service
    broken = item("r1", layer="procedural", key="supersession:region", content="not-json", source_type="memory_supersession")
    db.semantic_items = [item("old"), broken]
    report = compact.analyze("project:p1")
    assert report.invalid_receipt_ids == ("r1",)
    assert report.preferred_memory_ids == ("old",)
    assert report.recovery_required is True


def test_storage_inspection_failure_raises_explicit_error(service):
    compact, db = service
    db.fail_list = True
    with pytest.raises(MemoryCompactionError, match="could not be inspected"):
        compact.analyze("project:p1")

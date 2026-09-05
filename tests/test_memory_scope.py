import pytest

from app.memory_scope import MemoryScope, ScopedMemory


def test_global_project_and_conversation_scope_ids_are_isolated():
    assert ScopedMemory.scope_id(MemoryScope.GLOBAL) == "global"
    assert ScopedMemory.scope_id(MemoryScope.PROJECT, project_id="p1") == "project:p1"
    assert ScopedMemory.scope_id(MemoryScope.CONVERSATION, conversation_id="c1") == "conversation:c1"


def test_project_scope_requires_project_id():
    with pytest.raises(ValueError, match="project_id"):
        ScopedMemory.scope_id(MemoryScope.PROJECT)


def test_conversation_scope_requires_conversation_id():
    with pytest.raises(ValueError, match="conversation_id"):
        ScopedMemory.scope_id(MemoryScope.CONVERSATION)


def test_memory_id_is_stable_within_scope_and_distinct_across_scopes():
    global_record = ScopedMemory.build("preferred_model", "alpha")
    project_record = ScopedMemory.build("preferred_model", "alpha", scope="project", project_id="p1")
    project_record_again = ScopedMemory.build("preferred_model", "beta", scope="project", project_id="p1")

    assert global_record.memory_id != project_record.memory_id
    assert project_record.memory_id == project_record_again.memory_id


def test_visible_namespaces_only_include_explicit_active_scopes():
    assert ScopedMemory.visible_namespaces() == ["global"]
    assert ScopedMemory.visible_namespaces(project_id="p1") == ["global", "project:p1"]
    assert ScopedMemory.visible_namespaces(project_id="p1", conversation_id="c1") == [
        "global",
        "project:p1",
        "conversation:c1",
    ]

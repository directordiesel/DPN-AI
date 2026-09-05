from app.repository_engineer import RepositoryEngineer, RepositoryFile, ValidationRun


def test_repository_engineer_retries_until_validation_passes():
    calls = {"patch": 0, "validate": 0}

    def inspector(objective):
        return [RepositoryFile(path="app/example.py", size_bytes=100, language="python")]

    def diagnoser(objective, previous, attempt):
        return f"attempt {attempt} diagnosis"

    def patcher(objective, diagnosis, attempt):
        calls["patch"] += 1
        return ["app/example.py"]

    def validator(commands):
        calls["validate"] += 1
        ok = calls["validate"] >= 2
        return [ValidationRun(command=command, ok=ok, error="failing" if not ok else "") for command in commands]

    result = RepositoryEngineer(inspector, diagnoser, patcher, validator, max_attempts=3).run("fix it", ["pytest -q"])

    assert result["ok"] is True
    assert calls == {"patch": 2, "validate": 2}
    assert result["changed_paths"] == ["app/example.py"]
    assert len(result["attempts"]) == 2


def test_repository_engineer_fails_closed_after_attempt_limit():
    def inspector(objective):
        return []

    def diagnoser(objective, previous, attempt):
        return "still failing"

    def patcher(objective, diagnosis, attempt):
        return [f"app/change_{attempt}.py"]

    def validator(commands):
        return [ValidationRun(command=command, ok=False, error="red") for command in commands]

    result = RepositoryEngineer(inspector, diagnoser, patcher, validator, max_attempts=2).run("repair", ["pytest -q"])

    assert result["ok"] is False
    assert result["failure"] == "validation remained red after bounded repair attempts"
    assert len(result["attempts"]) == 2


def test_repository_engineer_rejects_unsafe_changed_paths():
    def inspector(objective):
        return []

    def diagnoser(objective, previous, attempt):
        return "x"

    def patcher(objective, diagnosis, attempt):
        return ["../outside.py"]

    def validator(commands):
        raise AssertionError("validation should not run")

    engineer = RepositoryEngineer(inspector, diagnoser, patcher, validator)
    try:
        engineer.run("unsafe", ["pytest -q"])
    except ValueError as exc:
        assert "escapes repository root" in str(exc)
    else:
        raise AssertionError("unsafe path was accepted")


def test_repository_engineer_requires_all_validation_results():
    def inspector(objective):
        return []

    def diagnoser(objective, previous, attempt):
        return "x"

    def patcher(objective, diagnosis, attempt):
        return []

    def validator(commands):
        return [ValidationRun(command=commands[0], ok=True)]

    engineer = RepositoryEngineer(inspector, diagnoser, patcher, validator)
    try:
        engineer.run("validate", ["compile", "pytest"])
    except ValueError as exc:
        assert "every required validation command" in str(exc)
    else:
        raise AssertionError("partial validation result set was accepted")

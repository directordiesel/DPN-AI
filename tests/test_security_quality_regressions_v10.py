from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
MODEL_GATEWAY = (ROOT / "app" / "model_gateway.py").read_text(encoding="utf-8")
SKILLS = (ROOT / "app" / "skills.py").read_text(encoding="utf-8")
BROWSER = (ROOT / "app" / "browser_adapter.py").read_text(encoding="utf-8")
CODEQL = (ROOT / ".github" / "workflows" / "codeql-advanced.yml").read_text(encoding="utf-8")
DEPENDABOT = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_api_token_comparison_is_constant_time():
    assert "hmac.compare_digest(supplied, settings.access_token)" in MAIN
    assert "supplied != settings.access_token" not in MAIN


def test_unhandled_server_errors_do_not_disclose_exception_details_to_clients():
    assert "DPN AI encountered an internal error. Error ID" in MAIN
    assert "sanitize_for_persistence(raw_detail)" in MAIN
    assert 'f"DPN AI encountered {type(exc).__name__}' not in MAIN


def test_user_supplied_json_errors_are_generic_and_bounded():
    assert "except (UnicodeDecodeError, json.JSONDecodeError) as exc:" in MAIN
    assert 'detail="Invalid JSON workflow"' in MAIN
    assert 'detail=f"Invalid JSON workflow: {exc}"' not in MAIN


def test_optional_dependency_detection_does_not_swallow_runtime_failures():
    assert BROWSER.count("except ImportError:") >= 2
    assert "except Exception:" not in BROWSER


def test_skill_listing_only_swallows_expected_parse_and_io_failures():
    assert "except (OSError, UnicodeError, json.JSONDecodeError):" in SKILLS


def test_model_gateway_redacts_upstream_provider_errors():
    assert "sanitize_for_persistence(response.text[:1000])" in MODEL_GATEWAY
    assert "except (OSError, ValueError):" in MODEL_GATEWAY
    assert "except (OllamaError, httpx.HTTPError, OSError, ValueError) as exc:" in MODEL_GATEWAY


def test_codeql_runs_extended_security_and_quality_queries():
    assert "queries: security-extended,security-and-quality" in CODEQL
    for language in ("python", "actions", "javascript-typescript", "java-kotlin"):
        assert f"language: {language}" in CODEQL


def test_dependabot_covers_all_shipped_dependency_ecosystems():
    for ecosystem in ("pip", "github-actions", "gradle", "docker"):
        assert f'package-ecosystem: "{ecosystem}"' in DEPENDABOT
    assert 'directory: "/mobile/android"' in DEPENDABOT


def test_container_runtime_drops_root_privileges():
    assert "adduser --system --ingroup dpnai" in DOCKERFILE
    assert "USER dpnai" in DOCKERFILE
    assert "chown -R dpnai:dpnai /opt/dpn-ai" in DOCKERFILE

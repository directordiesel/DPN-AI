from app.capability_readiness_v9 import build_capability_registry
from app.config import Settings


def _by_name(registry):
    return {item.name: item for item in registry.capabilities}


def test_unconfigured_optional_providers_never_claim_live():
    settings = Settings(
        compatible_api_url="",
        allow_external_models_default=True,
        allow_images_default=True,
    )
    registry = build_capability_registry(
        settings,
        environ={"DPN_VISION_MODEL": "", "DPN_COMFYUI_EDIT_WORKFLOW": ""},
        verified_live={"external_models": True, "vision": True, "image_editing": True},
    )
    values = _by_name(registry)
    assert values["external_models"].configured is False
    assert values["external_models"].live is False
    assert values["vision"].configured is False
    assert values["vision"].live is False
    assert values["image_editing"].configured is False
    assert values["image_editing"].live is False


def test_permission_disabled_capability_never_claims_live_even_when_configured():
    settings = Settings(
        compatible_api_url="https://provider.invalid/v1",
        allow_external_models_default=False,
        allow_images_default=False,
    )
    registry = build_capability_registry(
        settings,
        environ={
            "DPN_VISION_MODEL": "ollama:vision-model",
            "DPN_COMFYUI_EDIT_WORKFLOW": "data/edit.json",
        },
        verified_live={"external_models": True, "vision": True, "image_editing": True},
    )
    values = _by_name(registry)
    for name in ("external_models", "vision", "image_editing"):
        assert values[name].configured is True
        assert values[name].permission_enabled is False
        assert values[name].live is False


def test_verified_live_requires_all_readiness_preconditions():
    settings = Settings(
        compatible_api_url="https://provider.invalid/v1",
        allow_external_models_default=True,
        allow_images_default=True,
        allow_automations_default=True,
    )
    registry = build_capability_registry(
        settings,
        environ={
            "DPN_VISION_MODEL": "ollama:vision-model",
            "DPN_COMFYUI_EDIT_WORKFLOW": "data/edit.json",
        },
        verified_live={
            "external_models": True,
            "vision": True,
            "image_editing": True,
            "automations": True,
        },
    )
    values = _by_name(registry)
    assert values["external_models"].live is True
    assert values["vision"].live is True
    assert values["image_editing"].live is True
    assert values["automations"].live is True


def test_configuration_does_not_imply_live_without_verified_health_result():
    settings = Settings(
        compatible_api_url="https://provider.invalid/v1",
        allow_external_models_default=True,
        allow_images_default=True,
    )
    registry = build_capability_registry(
        settings,
        environ={
            "DPN_VISION_MODEL": "ollama:vision-model",
            "DPN_COMFYUI_EDIT_WORKFLOW": "data/edit.json",
        },
    )
    values = _by_name(registry)
    assert values["external_models"].configured is True
    assert values["vision"].configured is True
    assert values["image_editing"].configured is True
    assert not any(item.live for item in registry.capabilities)


def test_registry_payload_is_bounded_structured_and_secret_free():
    settings = Settings(
        compatible_api_url="https://secret-host.invalid/v1",
        compatible_api_secret="DO_NOT_EXPOSE_THIS_SECRET_NAME",
        access_token="DO_NOT_EXPOSE_THIS_ACCESS_TOKEN",
        allow_external_models_default=True,
    )
    payload = build_capability_registry(settings, environ={}).payload()
    assert payload["summary"]["total"] == len(payload["capabilities"])
    text = repr(payload)
    assert "DO_NOT_EXPOSE_THIS_SECRET_NAME" not in text
    assert "DO_NOT_EXPOSE_THIS_ACCESS_TOKEN" not in text
    assert "secret-host.invalid" not in text


def test_registry_order_is_deterministic():
    settings = Settings()
    first = build_capability_registry(settings, environ={}).payload()
    second = build_capability_registry(settings, environ={}).payload()
    assert first == second
    names = [item["name"] for item in first["capabilities"]]
    assert names == [
        "local_models",
        "external_models",
        "vision",
        "image_editing",
        "automations",
        "desktop_control",
        "voice",
        "connectors",
        "mcp",
        "host_sandbox",
    ]


def test_invalid_settings_type_is_rejected():
    try:
        build_capability_registry(object(), environ={})
    except TypeError as exc:
        assert "Settings" in str(exc)
    else:
        raise AssertionError("non-Settings values must fail closed")

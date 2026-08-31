# DPN AI Local Plugins

Place trusted Python files directly in this directory. DPN AI loads each `*.py` file at startup and calls `register(registry)`.

Review `examples/` for FiveM workspace and Discord webhook examples. Files ending in `.example` are disabled.

```python
def register(registry):
    registry.register(
        name="my_tool",
        description="Describe exactly what this tool does.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        function=lambda value: {"ok": True, "result": value.upper()},
        risk="read",
    )
```

Plugins execute with the same local permissions as DPN AI. Only install code you trust. Restart DPN AI after adding or changing a plugin.
# DPN AI v5 Model Gateway

## Purpose

The model gateway lets one DPN AI installation use multiple model runtimes. Ollama is the private default. An OpenAI-compatible server can provide a different local or explicitly approved remote model.

## Routing

- Bare model name: configured default provider
- `ollama:model`: force Ollama
- `compatible:model`: force the compatible endpoint
- `openai:model`: compatible-provider alias

Planner, worker, reviewer, embedding, and specialist routes may each use different prefixes.

## Compatible endpoint settings

```text
DPN_DEFAULT_PROVIDER=compatible
DPN_COMPATIBLE_API_URL=http://127.0.0.1:1234
DPN_COMPATIBLE_API_SECRET=MODEL_PROVIDER_KEY
DPN_ALLOW_EXTERNAL_MODELS=false
```

The base URL may be a server root or end in `/v1`.

Store the key through the encrypted vault. DPN AI adds a Bearer authorization header only when the configured secret exists.

## Security

- Localhost and private-network compatible servers are allowed by default.
- Public/external endpoints are rejected until `allow_external_models` is enabled.
- External use sends prompts, selected attachment context, and tool schemas to that provider.
- Tool execution still occurs through DPN AI and remains subject to local gates and approvals.
- A provider may not support every tool, image, reasoning, or embedding feature even when its API is compatible.

## Compatibility expectations

The endpoint should implement:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings` when semantic memory uses that provider
- OpenAI-style function/tool calls for agent operations
- Image URL data inputs for multimodal requests when vision is needed

DPN AI normalizes returned tool arguments into the internal tool-call format.
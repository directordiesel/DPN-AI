# DPN AI v5.0.6 Intelligence, Documents, Editing and Speed Fix

## Problems corrected

### DPN AI behaved like basic chat

The normal Direct path relied on the selected local model to decide whether to call tools. A model could answer a document request in prose and never create the requested file. The document specialist also advertised `create_document`, while the real registered tool was `create_word_document`.

V5.0.6 fixes the registry and adds a deterministic artifact builder. The AI still gets the first opportunity to create a tailored file through its tools. If it does not, DPN AI converts the completed content into the requested Office/PDF deliverable automatically.

### Responses were slow

Every Direct request could be followed by a second reviewer-model invocation. Simple prompts also carried more history, tools and reasoning than necessary. V5.0.6 classifies each request and uses:

- a streaming no-tool fast path for normal conversation;
- task-focused tools for operational work;
- adaptive reasoning depth;
- adaptive verification;
- automatic mission escalation only for complex requests;
- persistent model residency where Ollama supports it.

### The strongest model was not automatic

The old interface defaulted to one configured model. V5.0.6 can inspect installed models, exclude embedding models, rank generative models by size and family capability, account for vision/coding requirements, and route the operation to the strongest candidate.

### Submitted prompts could not be corrected

V5.0.6 assigns IDs to stored messages and lets the user edit a previous prompt. The selected message and all later turns are removed before regeneration, preventing stale answers from contaminating the revised branch.

## Patch safety

The in-place patch replaces only application/runtime assets and version metadata. It does not copy or delete:

- `.env`
- `data`
- `workspace`
- `plugins`
- installed Ollama models
- installed Piper voice models
- conversations, projects, memories, tasks or audit history

Changed files are backed up before installation.

## Limits

DPN AI can only select among models that are actually installed or configured. Running the largest installed model may improve reasoning but can increase memory use and total completion time. Streaming improves perceived latency by displaying output immediately; it cannot make insufficient hardware execute a large model at the speed of a smaller one.
# DPN AI v5 Universal Capability Matrix

| Area | Built in | Optional dependency or service | Key control |
|---|---:|---|---|
| Local chat and tool use | Yes | Ollama model | Model/tool limits |
| Compatible model gateway | Yes | Compatible server | Local-only by default |
| Male and female local voice | Yes | Piper voice models | Voice gate |
| Local transcription | Yes | faster-whisper | Voice gate |
| Images and vision | Yes | Vision model | Attachment limits |
| Local image generation | Adapter | ComfyUI | Image gate |
| Audio/video processing | Yes | FFmpeg for full support | Workspace/output bounds |
| Word/PDF/Excel/PowerPoint | Yes | Core Python packages | Workspace boundary |
| Software/FiveM development | Yes | Project runtimes | Command gate |
| Web research | Yes | Internet connection | Web gate |
| Browser control | Adapter | Playwright | External approval |
| Desktop control | Adapter | pyautogui and desktop session | Desktop approval |
| Cognitive goal contracts | Yes | None | Deterministic normalization |
| Multi-agent missions | Yes | Planner/worker/reviewer models | Mission budgets |
| Background job queue | Yes | App must remain open | Cancellation/retry |
| Provenance knowledge graph | Yes | None | Source/confidence metadata |
| Code sandbox | Yes | Docker recommended | No network; resource limits |
| Capability Forge | Yes | None | Stage/validate/approve/restart |
| MCP client bridge | Adapter | `requirements-mcp.txt` | Empty allowlist and audit |
| HTTP connectors | Yes | Target API | Encrypted secrets/allowlist |
| Scheduled automations | Yes | App must remain open | Automation gate |
| Recovery snapshots | Yes | Disk space | SHA-256 manifest |

No general assistant has unlimited access to every application, service, device, credential, paid model, or private dataset. DPN AI v5 handles missing capability through explicit adapters, plugins, connectors, or MCP servers rather than claiming unsupported access.
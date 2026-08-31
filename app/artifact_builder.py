from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactIntent:
    kinds: tuple[str, ...]
    title: str

    @property
    def requested(self) -> bool:
        return bool(self.kinds)

    @property
    def tool_names(self) -> set[str]:
        mapping = {
            "docx": "create_word_document",
            "pdf": "create_pdf",
            "xlsx": "create_spreadsheet",
            "pptx": "create_presentation",
        }
        return {mapping[kind] for kind in self.kinds if kind in mapping}


_CREATE_WORDS = (
    "create", "make", "build", "generate", "write", "prepare", "produce", "turn this into",
    "export", "save as", "put this in", "give me a",
)


def _clean_title(prompt: str) -> str:
    text = " ".join((prompt or "").replace("\n", " ").split())
    text = re.sub(
        r"(?i)\b(create|make|build|generate|write|prepare|produce|export|save|turn this into|give me)\b",
        "",
        text,
    )
    text = re.sub(
        r"(?i)\b(a|an|the|word|docx|document|pdf|report|excel|xlsx|spreadsheet|workbook|powerpoint|pptx|presentation|slides?)\b",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip(" .,:;-_")
    if not text:
        return "DPN AI Deliverable"
    return text[:90].strip().title()


def detect_artifact_intent(prompt: str) -> ArtifactIntent:
    text = " ".join((prompt or "").lower().split())
    creation = any(word in text for word in _CREATE_WORDS)
    explicit = any(token in text for token in (
        "word document", "docx", "pdf", "spreadsheet", "excel", "xlsx", "workbook",
        "powerpoint", "pptx", "presentation", "slide deck", "slides", "document package",
        "business package", "deliverables",
    ))
    if not creation and not explicit:
        return ArtifactIntent((), _clean_title(prompt))

    kinds: list[str] = []
    if any(token in text for token in ("word document", "docx", "word file")):
        kinds.append("docx")
    if re.search(r"\bpdf\b", text):
        kinds.append("pdf")
    if any(token in text for token in ("spreadsheet", "excel", "xlsx", "workbook")):
        kinds.append("xlsx")
    if any(token in text for token in ("powerpoint", "pptx", "presentation", "slide deck", "slides")):
        kinds.append("pptx")

    package_request = any(token in text for token in (
        "all formats", "complete package", "business package", "document package", "full package",
        "word, pdf, excel", "word pdf excel", "all documents", "deliverables",
    ))
    if package_request:
        kinds = ["docx", "pdf", "xlsx", "pptx"]
    elif not kinds and any(token in text for token in ("document", "report", "proposal", "sop", "guide", "plan")):
        kinds = ["docx"]

    return ArtifactIntent(tuple(dict.fromkeys(kinds)), _clean_title(prompt))


def _strip_markdown(value: str) -> str:
    value = re.sub(r"```[\s\S]*?```", "", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", value)
    value = re.sub(r"[*_~]", "", value)
    return value.strip()


def markdown_sections(content: str, fallback_title: str) -> list[dict[str, Any]]:
    text = (content or "").strip()
    if not text:
        return [{"heading": "Overview", "body": "This deliverable was requested through DPN AI."}]
    sections: list[dict[str, Any]] = []
    heading = "Overview"
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        cleaned = "\n".join(body).strip()
        if cleaned:
            sections.append({"heading": heading, "body": _strip_markdown(cleaned)})
        body = []

    for raw in text.splitlines():
        match = re.match(r"^#{1,3}\s+(.+)$", raw.strip())
        if match:
            flush()
            heading = _strip_markdown(match.group(1))[:120] or fallback_title
        else:
            body.append(raw)
    flush()
    if not sections:
        sections.append({"heading": fallback_title, "body": _strip_markdown(text)})
    return sections[:40]


def presentation_slides(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slides: list[dict[str, Any]] = []
    for section in sections[:20]:
        body = str(section.get("body") or "")
        bullets = []
        for paragraph in re.split(r"\n+|(?<=[.!?])\s+", body):
            item = paragraph.strip(" -•\t")
            if item:
                bullets.append(item[:320])
        if not bullets:
            bullets = ["DPN AI generated deliverable"]
        slides.append({"title": str(section.get("heading") or "Overview")[:100], "bullets": bullets[:7]})
    return slides or [{"title": "Overview", "bullets": ["DPN AI generated deliverable"]}]


def spreadsheet_sheets(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[str]] = [["Section", "Content"]]
    for section in sections:
        heading = str(section.get("heading") or "Section")
        body = str(section.get("body") or "")
        paragraphs = [item.strip(" -•\t") for item in re.split(r"\n+", body) if item.strip()]
        if not paragraphs:
            rows.append([heading, ""])
        else:
            for index, paragraph in enumerate(paragraphs):
                rows.append([heading if index == 0 else "", paragraph])
    return [{"name": "DPN AI Deliverable", "rows": rows[:5000]}]


def build_arguments(kind: str, intent: ArtifactIntent, content: str) -> tuple[str, dict[str, Any]]:
    title = intent.title or "DPN AI Deliverable"
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", title).strip(" ._") or "DPN_AI_Deliverable"
    sections = markdown_sections(content, title)
    if kind == "docx":
        return "create_word_document", {"filename": f"{safe_stem}.docx", "title": title, "sections": sections, "author": "DPN AI"}
    if kind == "pdf":
        return "create_pdf", {"filename": f"{safe_stem}.pdf", "title": title, "sections": sections}
    if kind == "xlsx":
        return "create_spreadsheet", {"filename": f"{safe_stem}.xlsx", "title": title, "sheets": spreadsheet_sheets(sections)}
    if kind == "pptx":
        return "create_presentation", {"filename": f"{safe_stem}.pptx", "title": title, "slides": presentation_slides(sections)}
    raise ValueError(f"Unsupported artifact kind: {kind}")
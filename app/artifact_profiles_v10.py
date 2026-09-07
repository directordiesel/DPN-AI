from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ArtifactProfile:
    profile_id: str
    artifact_type: str
    max_items: int
    min_quality_score: float = 1.0
    description: str = ""


@dataclass(frozen=True)
class ArtifactProfileEvaluation:
    profile_id: str
    artifact_type: str
    ready: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "artifact_type": self.artifact_type,
            "ready": self.ready,
            "checks": list(self.checks),
            "failures": list(self.failures),
            "metrics": dict(self.metrics),
        }


PROFESSIONAL_ARTIFACT_PROFILES: Mapping[str, ArtifactProfile] = {
    "professional_report_docx": ArtifactProfile(
        profile_id="professional_report_docx",
        artifact_type="docx",
        max_items=24,
        description="Professional Word report with titled, non-empty structured sections.",
    ),
    "formal_report_pdf": ArtifactProfile(
        profile_id="formal_report_pdf",
        artifact_type="pdf",
        max_items=24,
        description="Formal PDF report with titled, non-empty structured sections.",
    ),
    "analytical_workbook_xlsx": ArtifactProfile(
        profile_id="analytical_workbook_xlsx",
        artifact_type="xlsx",
        max_items=12,
        description="Analytical workbook with named sheets, headers, bounded formulas and charts.",
    ),
    "executive_deck_pptx": ArtifactProfile(
        profile_id="executive_deck_pptx",
        artifact_type="pptx",
        max_items=40,
        description="Executive widescreen presentation with bounded, titled content slides.",
    ),
}

DEFAULT_PROFILE_BY_TYPE: Mapping[str, str] = {
    "docx": "professional_report_docx",
    "pdf": "formal_report_pdf",
    "xlsx": "analytical_workbook_xlsx",
    "pptx": "executive_deck_pptx",
}


def get_artifact_profile(profile_id: str | None, artifact_type: str) -> ArtifactProfile:
    normalized_type = artifact_type.strip().lower().lstrip(".")
    selected = (profile_id or DEFAULT_PROFILE_BY_TYPE.get(normalized_type, "")).strip()
    profile = PROFESSIONAL_ARTIFACT_PROFILES.get(selected)
    if profile is None:
        raise ValueError(f"unknown professional artifact profile: {selected or '<none>'}")
    if profile.artifact_type != normalized_type:
        raise ValueError(
            f"artifact profile {profile.profile_id} is for {profile.artifact_type}, not {normalized_type or '<unknown>'}"
        )
    return profile


def _nonempty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _section_has_content(section: Mapping[str, Any]) -> bool:
    body = section.get("body")
    table = section.get("table")
    if isinstance(body, list):
        if any(_nonempty(item) for item in body):
            return True
    elif _nonempty(body):
        return True
    if isinstance(table, list) and table:
        return any(any(_nonempty(cell) for cell in (row if isinstance(row, list) else [row])) for row in table)
    return False


def evaluate_artifact_profile_request(
    *,
    profile_id: str | None,
    artifact_type: str,
    title: str,
    items: Sequence[Mapping[str, Any]],
) -> ArtifactProfileEvaluation:
    profile = get_artifact_profile(profile_id, artifact_type)
    checks: list[str] = []
    failures: list[str] = []
    metrics: dict[str, Any] = {"items": len(items), "max_items": profile.max_items}

    if _nonempty(title):
        checks.append("artifact title is present")
    else:
        failures.append("artifact title is required")

    if items:
        checks.append("artifact request contains content items")
    else:
        failures.append("artifact request requires at least one content item")

    if len(items) <= profile.max_items:
        checks.append("artifact request stays within profile item bound")
    else:
        failures.append(f"artifact request exceeds profile item bound of {profile.max_items}")

    if profile.artifact_type in {"docx", "pdf"}:
        missing_headings = [index for index, item in enumerate(items, start=1) if not _nonempty(item.get("heading"))]
        empty_sections = [index for index, item in enumerate(items, start=1) if not _section_has_content(item)]
        metrics.update({"missing_headings": len(missing_headings), "empty_sections": len(empty_sections)})
        if not missing_headings:
            checks.append("all report sections have headings")
        else:
            failures.append("one or more report sections are missing headings")
        if not empty_sections:
            checks.append("all report sections contain body or table content")
        else:
            failures.append("one or more report sections are empty")

    elif profile.artifact_type == "xlsx":
        names = [str(item.get("name", "")).strip()[:31] for item in items]
        normalized_names = [name.casefold() for name in names if name]
        missing_names = sum(1 for name in names if not name)
        duplicate_names = len(normalized_names) - len(set(normalized_names))
        missing_rows = 0
        overwide_sheets = 0
        formula_count = 0
        chart_count = 0
        for item in items:
            rows = item.get("rows", [])
            if not isinstance(rows, list) or not rows:
                missing_rows += 1
                continue
            first = rows[0] if isinstance(rows[0], list) else [rows[0]]
            if not any(_nonempty(value) for value in first):
                missing_rows += 1
            if len(first) > 64:
                overwide_sheets += 1
            formulas = item.get("formulas", {})
            if isinstance(formulas, dict):
                formula_count += len(formulas)
            charts = item.get("charts", [])
            if isinstance(charts, list):
                chart_count += len(charts)
        metrics.update(
            {
                "missing_sheet_names": missing_names,
                "duplicate_sheet_names": duplicate_names,
                "missing_header_rows": missing_rows,
                "overwide_sheets": overwide_sheets,
                "formulas": formula_count,
                "charts": chart_count,
            }
        )
        if not missing_names and not duplicate_names:
            checks.append("workbook sheet names are present and unique")
        else:
            failures.append("workbook sheet names must be present and unique")
        if not missing_rows:
            checks.append("all workbook sheets contain a populated header row")
        else:
            failures.append("one or more workbook sheets lack a populated header row")
        if not overwide_sheets:
            checks.append("workbook headers stay within 64-column profile bound")
        else:
            failures.append("one or more workbook sheets exceed 64 header columns")
        if formula_count <= 200:
            checks.append("workbook formulas stay within bounded profile allowance")
        else:
            failures.append("workbook exceeds 200 formula profile allowance")
        if chart_count <= 8 * max(1, len(items)):
            checks.append("workbook charts stay within per-sheet profile allowance")
        else:
            failures.append("workbook exceeds chart profile allowance")

    else:
        missing_titles = 0
        empty_slides = 0
        overfull_slides = 0
        for item in items:
            if not _nonempty(item.get("title")):
                missing_titles += 1
            bullets = item.get("bullets")
            if isinstance(bullets, list):
                meaningful = [value for value in bullets if _nonempty(value)]
                if not meaningful:
                    empty_slides += 1
                if len(meaningful) > 8:
                    overfull_slides += 1
            elif not _nonempty(item.get("body")):
                empty_slides += 1
        metrics.update(
            {
                "missing_slide_titles": missing_titles,
                "empty_slides": empty_slides,
                "overfull_slides": overfull_slides,
            }
        )
        if not missing_titles:
            checks.append("all presentation slides have titles")
        else:
            failures.append("one or more presentation slides are missing titles")
        if not empty_slides:
            checks.append("all presentation slides contain content")
        else:
            failures.append("one or more presentation slides are empty")
        if not overfull_slides:
            checks.append("presentation slides stay within eight-bullet profile bound")
        else:
            failures.append("one or more presentation slides exceed eight bullets")

    return ArtifactProfileEvaluation(
        profile_id=profile.profile_id,
        artifact_type=profile.artifact_type,
        ready=not failures and bool(checks),
        checks=tuple(checks),
        failures=tuple(failures),
        metrics=metrics,
    )


__all__ = [
    "ArtifactProfile",
    "ArtifactProfileEvaluation",
    "DEFAULT_PROFILE_BY_TYPE",
    "PROFESSIONAL_ARTIFACT_PROFILES",
    "evaluate_artifact_profile_request",
    "get_artifact_profile",
]

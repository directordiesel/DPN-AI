from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook
from openpyxl.chart import BarChart, LineChart, Reference

from app.artifact_acceptance_v10 import inspect_artifact_acceptance
from app.artifact_profiles_v10 import ArtifactProfileEvaluation, evaluate_artifact_profile_request
from app.artifact_quality_v10 import inspect_artifact_quality
from app.artifact_validation import validate_artifact
from app.tools.documents import DocumentFactory


class ArtifactStudio:
    """Advanced artifact orchestration over the stable DocumentFactory API."""

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.factory = DocumentFactory(self.workspace)

    @staticmethod
    def _profile_failure(artifact_type: str, evaluation: ArtifactProfileEvaluation) -> dict[str, Any]:
        return {
            "ok": False,
            "type": artifact_type,
            "error": "artifact profile preflight failed",
            "profile": evaluation.to_dict(),
            "professional_ready": False,
        }

    def _finalize(
        self,
        result: dict[str, Any],
        *,
        required_items: Iterable[str],
        profile: ArtifactProfileEvaluation,
    ) -> dict[str, Any]:
        if not result.get("ok") or not result.get("path"):
            return {**result, "profile": profile.to_dict(), "professional_ready": False}
        target = self.workspace / str(result["path"])
        validation = validate_artifact(target, self.workspace)
        quality = inspect_artifact_quality(target, self.workspace)
        acceptance = inspect_artifact_acceptance(target, self.workspace, required_items=required_items)
        professional_ready = bool(
            profile.ready and validation.valid and quality.professional_ready and acceptance.accepted
        )
        return {
            **result,
            "profile": profile.to_dict(),
            "validation": validation.to_dict(),
            "quality": quality.to_dict(),
            "acceptance": acceptance.to_dict(),
            "professional_ready": professional_ready,
        }

    def create_document(
        self,
        filename: str,
        title: str,
        sections: list[dict[str, Any]],
        author: str = "DPN AI",
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        profile = evaluate_artifact_profile_request(
            profile_id=profile_id,
            artifact_type="docx",
            title=title,
            items=sections,
        )
        if not profile.ready:
            return self._profile_failure("docx", profile)
        required = [title, *(str(section.get("heading", "")).strip() for section in sections)]
        return self._finalize(
            self.factory.create_docx(filename, title, sections, author=author),
            required_items=required,
            profile=profile,
        )

    def create_pdf(
        self,
        filename: str,
        title: str,
        sections: list[dict[str, Any]],
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        profile = evaluate_artifact_profile_request(
            profile_id=profile_id,
            artifact_type="pdf",
            title=title,
            items=sections,
        )
        if not profile.ready:
            return self._profile_failure("pdf", profile)
        required = [title, *(str(section.get("heading", "")).strip() for section in sections)]
        return self._finalize(
            self.factory.create_pdf(filename, title, sections),
            required_items=required,
            profile=profile,
        )

    def create_presentation(
        self,
        filename: str,
        title: str,
        slides: list[dict[str, Any]],
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        profile = evaluate_artifact_profile_request(
            profile_id=profile_id,
            artifact_type="pptx",
            title=title,
            items=slides,
        )
        if not profile.ready:
            return self._profile_failure("pptx", profile)
        required = [title, *(str(slide.get("title", "")).strip() for slide in slides)]
        return self._finalize(
            self.factory.create_pptx(filename, title, slides),
            required_items=required,
            profile=profile,
        )

    def create_spreadsheet(
        self,
        filename: str,
        title: str,
        sheets: list[dict[str, Any]],
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        profile = evaluate_artifact_profile_request(
            profile_id=profile_id,
            artifact_type="xlsx",
            title=title,
            items=sheets,
        )
        if not profile.ready:
            return self._profile_failure("xlsx", profile)

        result = self.factory.create_xlsx(filename, title, sheets)
        if not result.get("ok") or not result.get("path"):
            return {**result, "profile": profile.to_dict(), "professional_ready": False}

        target = (self.workspace / str(result["path"])).resolve()
        target.relative_to(self.workspace)
        workbook = load_workbook(target)

        for sheet_spec in sheets:
            name = str(sheet_spec.get("name", ""))[:31]
            if not name or name not in workbook.sheetnames:
                continue
            ws = workbook[name]

            formulas = sheet_spec.get("formulas", {})
            if isinstance(formulas, dict):
                for cell_ref, formula in formulas.items():
                    ref = str(cell_ref).strip().upper()
                    value = str(formula).strip()
                    if not ref or not value:
                        continue
                    ws[ref] = value if value.startswith("=") else f"={value}"

            charts = sheet_spec.get("charts", [])
            if not isinstance(charts, list):
                continue
            for chart_spec in charts[:8]:
                if not isinstance(chart_spec, dict):
                    continue
                chart_type = str(chart_spec.get("type", "bar")).lower()
                chart = LineChart() if chart_type == "line" else BarChart()
                chart.title = str(chart_spec.get("title", "Chart"))[:120]
                chart.y_axis.title = str(chart_spec.get("y_axis", ""))[:80]
                chart.x_axis.title = str(chart_spec.get("x_axis", ""))[:80]

                min_col = max(1, int(chart_spec.get("min_col", 2)))
                max_col = max(min_col, int(chart_spec.get("max_col", ws.max_column)))
                min_row = max(1, int(chart_spec.get("min_row", 1)))
                max_row = max(min_row + 1, int(chart_spec.get("max_row", ws.max_row)))
                category_col = max(1, int(chart_spec.get("category_col", 1)))
                data = Reference(ws, min_col=min_col, max_col=max_col, min_row=min_row, max_row=max_row)
                categories = Reference(ws, min_col=category_col, min_row=min_row + 1, max_row=max_row)
                chart.add_data(data, titles_from_data=True)
                chart.set_categories(categories)
                chart.height = min(15, max(5, float(chart_spec.get("height", 7.5))))
                chart.width = min(25, max(8, float(chart_spec.get("width", 12))))
                ws.add_chart(chart, str(chart_spec.get("anchor", "H2")))

        workbook.save(target)

        required: list[str] = []
        for sheet in sheets:
            name = str(sheet.get("name", "")).strip()
            if name:
                required.append(name[:31])
            rows = sheet.get("rows", [])
            if isinstance(rows, list) and rows:
                header = rows[0] if isinstance(rows[0], list) else [rows[0]]
                required.extend(str(value).strip() for value in header if str(value).strip())
        return self._finalize(result, required_items=required, profile=profile)

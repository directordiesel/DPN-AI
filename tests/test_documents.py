from pathlib import Path

from app.tools.documents import DocumentFactory


def test_document_factory_creates_all_formats(tmp_path: Path) -> None:
    factory = DocumentFactory(tmp_path)
    outputs = [
        factory.create_docx("report", "DPN Report", [{"heading": "Summary", "body": "Ready"}]),
        factory.create_pdf("report", "DPN Report", [{"heading": "Summary", "body": "Ready"}]),
        factory.create_xlsx("report", "DPN Report", [{"name": "Data", "rows": [["Metric", "Value"], ["Ready", 1]]}]),
        factory.create_pptx("report", "DPN Report", [{"title": "Summary", "bullets": ["Ready"]}]),
    ]
    for result in outputs:
        assert result["ok"] is True
        assert (tmp_path / result["path"]).is_file()
from datetime import datetime, timezone

from app.research_intelligence import ClaimEvidence, ResearchIntelligence


def test_normalize_url_removes_tracking_and_stabilizes_query_order():
    value = ResearchIntelligence.normalize_url(
        "HTTPS://Example.com/path/?utm_source=x&b=2&a=1&fbclid=z"
    )
    assert value == "https://example.com/path?a=1&b=2"


def test_source_ranking_prefers_authoritative_relevant_recent_sources():
    engine = ResearchIntelligence()
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    sources = engine.build_sources(
        "space weather forecast",
        [
            {
                "title": "Forecast",
                "url": "https://www.noaa.gov/space-weather",
                "snippet": "space weather forecast",
                "published_at": "2026-09-04T12:00:00Z",
            },
            {
                "title": "Blog",
                "url": "https://example.com/opinion",
                "snippet": "space weather forecast",
                "published_at": "2020-01-01T00:00:00Z",
            },
        ],
        now=now,
    )
    assert sources[0].domain == "www.noaa.gov"
    assert sources[0].quality_score > sources[1].quality_score


def test_duplicate_urls_collapse_after_tracking_normalization():
    engine = ResearchIntelligence()
    sources = engine.build_sources(
        "alpha beta",
        [
            {"title": "A", "url": "https://example.com/x?utm_source=a", "snippet": "alpha beta"},
            {"title": "B", "url": "https://example.com/x?utm_source=b", "content": "alpha beta full content"},
        ],
    )
    assert len(sources) == 1
    assert sources[0].content == "alpha beta full content"


def test_bundle_has_stable_citation_refs_and_respects_budget():
    engine = ResearchIntelligence(max_content_chars=2000)
    result = engine.evidence_bundle(
        "alpha beta",
        [
            {
                "title": "Reference",
                "url": "https://docs.python.org/3/",
                "content": "alpha beta " + ("x" * 4000),
            }
        ],
    )
    assert result["ok"] is True
    assert result["citations"][0]["ref"] == "R1"
    assert len(result["context"]) <= 2000


def test_conflict_detection_requires_multiple_meaningful_stances():
    conflicts = ResearchIntelligence.detect_conflicts(
        [
            ClaimEvidence("The launch is Tuesday", "supports", ("a",), 0.9),
            ClaimEvidence("The launch is Tuesday", "refutes", ("b",), 0.8),
            ClaimEvidence("Other claim", "unknown", ("c",), 0.5),
        ]
    )
    assert conflicts == [
        {
            "claim": "The launch is Tuesday",
            "stances": {"supports": ["a"], "refutes": ["b"]},
            "status": "conflict",
        }
    ]


def test_empty_query_fails_closed():
    engine = ResearchIntelligence()
    result = engine.evidence_bundle("   ", [])
    assert result["ok"] is False
    assert result["sources"] == []

from datetime import datetime, timezone

from app.research_intelligence import ClaimEvidence, ResearchIntelligence


def test_normalize_url_removes_tracking_and_stabilizes_query_order():
    value = ResearchIntelligence.normalize_url(
        "HTTPS://Example.com/path/?utm_source=x&b=2&a=1&fbclid=z"
    )
    assert value == "https://example.com/path?a=1&b=2"


def test_normalize_url_rejects_non_web_schemes_and_invalid_ports():
    assert ResearchIntelligence.normalize_url("file:///etc/passwd") == ""
    assert ResearchIntelligence.normalize_url("ftp://example.com/archive") == ""
    assert ResearchIntelligence.normalize_url("https://example.com:bad/path") == ""


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


def test_authority_matching_rejects_lookalike_domains_but_accepts_subdomains():
    assert ResearchIntelligence.authority_for_domain("reuters.com") == 0.88
    assert ResearchIntelligence.authority_for_domain("www.reuters.com") == 0.88
    assert ResearchIntelligence.authority_for_domain("evil-reuters.com") == 0.58
    assert ResearchIntelligence.authority_for_domain("reuters.com.evil.example") == 0.58
    assert ResearchIntelligence.authority_for_domain("docs.python.org") == 0.84
    assert ResearchIntelligence.authority_for_domain("fake-docs.python.org.example") == 0.58


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


def test_build_sources_drops_non_http_evidence():
    engine = ResearchIntelligence()
    sources = engine.build_sources(
        "secret file",
        [
            {"title": "Local file", "url": "file:///etc/passwd", "content": "secret file"},
            {"title": "Public", "url": "https://example.com/public", "content": "secret file"},
        ],
    )
    assert [source.url for source in sources] == ["https://example.com/public"]


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
    assert result["context_chars"] == len(result["context"])


def test_bundle_exposes_source_quality_components_and_truncation_evidence():
    engine = ResearchIntelligence(max_content_chars=2000)
    result = engine.evidence_bundle(
        "python documentation",
        [
            {
                "title": "Python Documentation",
                "url": "https://docs.python.org/3/",
                "content": "python documentation " + ("reference " * 400),
                "published_at": "2026-09-04T00:00:00Z",
            }
        ],
    )
    citation = result["citations"][0]
    assert citation["quality_tier"] in {"high", "medium", "low"}
    assert citation["authority_score"] == 0.84
    assert 0.0 < citation["freshness_score"] <= 1.0
    assert 0.0 < citation["relevance_score"] <= 1.0
    assert citation["source_chars"] > citation["excerpt_chars"]
    assert citation["truncated"] is True


def test_quality_tier_has_deterministic_thresholds():
    assert ResearchIntelligence.quality_tier(0.90) == "high"
    assert ResearchIntelligence.quality_tier(0.70) == "medium"
    assert ResearchIntelligence.quality_tier(0.40) == "low"


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


def test_conflict_detection_normalizes_common_stance_aliases():
    conflicts = ResearchIntelligence.detect_conflicts(
        [
            ClaimEvidence("Service is restored", "confirmed", ("a",), 0.9),
            ClaimEvidence("Service is restored", "denies", ("b",), 0.8),
        ]
    )
    assert conflicts == [
        {
            "claim": "Service is restored",
            "stances": {"supports": ["a"], "refutes": ["b"]},
            "status": "conflict",
        }
    ]


def test_low_confidence_claim_does_not_create_false_conflict():
    conflicts = ResearchIntelligence.detect_conflicts(
        [
            ClaimEvidence("Service is restored", "supports", ("a",), 0.95),
            ClaimEvidence("Service is restored", "refutes", ("b",), 0.2),
        ]
    )
    assert conflicts == []


def test_empty_query_fails_closed():
    engine = ResearchIntelligence()
    result = engine.evidence_bundle("   ", [])
    assert result["ok"] is False
    assert result["sources"] == []

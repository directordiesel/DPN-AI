from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    title: str
    url: str
    domain: str
    snippet: str = ""
    content: str = ""
    published_at: str | None = None
    source_type: str = "web"
    authority_score: float = 0.5
    freshness_score: float = 0.5
    relevance_score: float = 0.5
    quality_score: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClaimEvidence:
    claim: str
    stance: str
    source_ids: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "stance": self.stance,
            "source_ids": list(self.source_ids),
            "confidence": self.confidence,
        }


class ResearchIntelligence:
    """Deterministic evidence ranking for web research.

    This layer never treats a model statement as evidence. It normalizes and
    deduplicates web sources, scores source quality/freshness, builds stable
    citation identifiers, and exposes explicit claim conflicts for downstream
    research agents and reports.
    """

    def __init__(self, *, max_sources: int = 20, max_content_chars: int = 80_000) -> None:
        if not 1 <= max_sources <= 100:
            raise ValueError("max_sources must be between 1 and 100")
        if max_content_chars < 2_000:
            raise ValueError("max_content_chars must be at least 2000")
        self.max_sources = max_sources
        self.max_content_chars = max_content_chars

    @staticmethod
    def normalize_url(url: str) -> str:
        raw = (url or "").strip()
        parsed = urlparse(raw)
        scheme = parsed.scheme.lower() or "https"
        if scheme not in {"http", "https"}:
            return ""
        hostname = (parsed.hostname or "").lower().strip(".")
        if not hostname:
            return ""
        try:
            port = parsed.port
        except ValueError:
            return ""
        netloc = hostname
        if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
            netloc = f"{hostname}:{port}"
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        if path != "/":
            path = path.rstrip("/")
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_KEYS and not key.lower().startswith(_TRACKING_PREFIXES)
        ]
        query.sort()
        return urlunparse((scheme, netloc, path, "", urlencode(query), ""))

    @staticmethod
    def _domain(url: str) -> str:
        return (urlparse(url).hostname or "").lower()

    @staticmethod
    def _source_id(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _is_domain_or_subdomain(domain: str, trusted_domain: str) -> bool:
        domain = (domain or "").lower().strip(".")
        trusted_domain = (trusted_domain or "").lower().strip(".")
        return bool(domain and trusted_domain and (domain == trusted_domain or domain.endswith(f".{trusted_domain}")))

    @classmethod
    def authority_for_domain(cls, domain: str) -> float:
        domain = (domain or "").lower().strip(".")
        if not domain:
            return 0.2
        if domain.endswith(".gov") or domain.endswith(".mil"):
            return 0.96
        if domain.endswith(".edu"):
            return 0.90
        if domain.endswith(".int"):
            return 0.90
        if any(cls._is_domain_or_subdomain(domain, trusted) for trusted in ("who.int", "un.org", "oecd.org", "worldbank.org")):
            return 0.93
        if any(cls._is_domain_or_subdomain(domain, trusted) for trusted in ("reuters.com", "apnews.com")):
            return 0.88
        if any(cls._is_domain_or_subdomain(domain, trusted) for trusted in ("github.com", "docs.python.org", "developer.mozilla.org")):
            return 0.84
        return 0.58

    @staticmethod
    def freshness_score(published_at: str | None, *, now: datetime | None = None, half_life_days: float = 180.0) -> float:
        if not published_at:
            return 0.5
        try:
            value = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.45
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        age_days = max(0.0, (now - value.astimezone(timezone.utc)).total_seconds() / 86400.0)
        half_life_days = max(1.0, float(half_life_days))
        return round(max(0.05, math.pow(0.5, age_days / half_life_days)), 6)

    @staticmethod
    def relevance_score(query: str, text: str) -> float:
        query_terms = {term for term in re.findall(r"[a-z0-9]{3,}", (query or "").lower())}
        if not query_terms:
            return 0.5
        text_terms = set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))
        overlap = len(query_terms & text_terms) / len(query_terms)
        return round(max(0.05, min(1.0, overlap)), 6)

    @staticmethod
    def quality_score(authority: float, freshness: float, relevance: float, has_content: bool) -> float:
        content_bonus = 0.05 if has_content else 0.0
        return round(min(1.0, authority * 0.45 + freshness * 0.20 + relevance * 0.35 + content_bonus), 6)

    def build_sources(self, query: str, raw_sources: list[dict[str, Any]], *, now: datetime | None = None) -> list[ResearchSource]:
        deduped: dict[str, ResearchSource] = {}
        for item in raw_sources:
            url = self.normalize_url(str(item.get("url") or ""))
            domain = self._domain(url)
            if not domain:
                continue
            title = str(item.get("title") or domain).strip()
            snippet = str(item.get("snippet") or "").strip()
            content = str(item.get("content") or "").strip()
            published_at = item.get("published_at") or item.get("date")
            authority = self.authority_for_domain(domain)
            freshness = self.freshness_score(str(published_at) if published_at else None, now=now)
            relevance = self.relevance_score(query, f"{title}\n{snippet}\n{content[:12000]}")
            quality = self.quality_score(authority, freshness, relevance, bool(content))
            source = ResearchSource(
                source_id=self._source_id(url),
                title=title,
                url=url,
                domain=domain,
                snippet=snippet,
                content=content,
                published_at=str(published_at) if published_at else None,
                source_type=str(item.get("source_type") or "web"),
                authority_score=authority,
                freshness_score=freshness,
                relevance_score=relevance,
                quality_score=quality,
                metadata=dict(item.get("metadata") or {}),
            )
            existing = deduped.get(url)
            if existing is None or source.quality_score > existing.quality_score or len(source.content) > len(existing.content):
                deduped[url] = source
        ranked = sorted(deduped.values(), key=lambda item: (-item.quality_score, item.domain, item.url))
        return ranked[: self.max_sources]

    def evidence_bundle(self, query: str, raw_sources: list[dict[str, Any]]) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"ok": False, "error": "query is required", "sources": [], "citations": [], "context": ""}
        sources = self.build_sources(query, raw_sources)
        context_parts: list[str] = []
        citations: list[dict[str, Any]] = []
        used = 0
        for index, source in enumerate(sources, start=1):
            label = f"[R{index}] {source.title} — {source.domain}"
            body = (source.content or source.snippet).strip()
            remaining = self.max_content_chars - used
            if remaining <= 0:
                break
            block = f"{label}\nURL: {source.url}\n{body}".strip()
            if len(block) > remaining:
                block = block[:remaining]
            if not block:
                continue
            context_parts.append(block)
            citations.append({
                "ref": f"R{index}",
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
                "domain": source.domain,
                "quality_score": source.quality_score,
                "published_at": source.published_at,
            })
            used += len(block) + 2
        return {
            "ok": True,
            "query": query,
            "sources": [item.to_dict() for item in sources],
            "citations": citations,
            "context": "\n\n".join(context_parts),
            "context_chars": min(used, self.max_content_chars),
        }

    @staticmethod
    def detect_conflicts(claims: list[ClaimEvidence | dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, list[str]]] = {}
        display_claims: dict[str, str] = {}
        for raw in claims:
            item = raw if isinstance(raw, ClaimEvidence) else ClaimEvidence(
                claim=str(raw.get("claim") or ""),
                stance=str(raw.get("stance") or "unknown"),
                source_ids=tuple(str(value) for value in raw.get("source_ids", []) if value),
                confidence=float(raw.get("confidence", 0.5)),
            )
            normalized_claim = re.sub(r"\s+", " ", item.claim.strip().lower())
            if not normalized_claim:
                continue
            stance = item.stance.strip().lower() or "unknown"
            grouped.setdefault(normalized_claim, {}).setdefault(stance, []).extend(item.source_ids)
            display_claims.setdefault(normalized_claim, item.claim.strip())
        conflicts: list[dict[str, Any]] = []
        for normalized_claim, stances in grouped.items():
            meaningful = {key: sorted(set(values)) for key, values in stances.items() if key not in {"unknown", "unclear"}}
            if len(meaningful) > 1:
                conflicts.append({
                    "claim": display_claims[normalized_claim],
                    "stances": meaningful,
                    "status": "conflict",
                })
        return conflicts

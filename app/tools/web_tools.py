from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from app.network_security import NetworkSecurityError, resolve_url_endpoint, verify_httpx_response_peer
from app.persistence_security import sanitize_for_persistence


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 DPN-AI/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REDIRECTS = 5


def _safe_public_url(url: str) -> tuple[bool, str]:
    try:
        resolve_url_endpoint(url, allow_private=False)
    except NetworkSecurityError as exc:
        return False, str(exc)
    return True, ""


async def _bounded_public_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
) -> tuple[bytes, str, str]:
    current = str(url)
    for redirect_count in range(MAX_REDIRECTS + 1):
        endpoint = resolve_url_endpoint(current, allow_private=False)
        async with client.stream("GET", current) as response:
            verify_httpx_response_peer(response, endpoint)
            if response.is_redirect:
                if redirect_count >= MAX_REDIRECTS:
                    raise NetworkSecurityError("Too many redirects")
                location = response.headers.get("location")
                if not location:
                    raise NetworkSecurityError("Redirect response did not include a Location header")
                current = urljoin(str(response.url), location)
                continue

            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared:
                try:
                    if int(declared) > max_bytes:
                        raise NetworkSecurityError("Response exceeds the allowed size")
                except ValueError as exc:
                    raise NetworkSecurityError("Response has an invalid Content-Length") from exc

            content_type = response.headers.get("content-type", "")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise NetworkSecurityError("Response exceeds the allowed size")
            return bytes(body), str(response.url), content_type
    raise NetworkSecurityError("Too many redirects")


async def search_web(query: str, max_results: int = 6) -> dict[str, Any]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=20,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            body, _, _ = await _bounded_public_get(client, url, max_bytes=MAX_RESPONSE_BYTES)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        detail = str(sanitize_for_persistence(str(exc)))
        return {"ok": False, "error": f"Web search failed: {detail}"}

    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
    results: list[dict[str, str]] = []
    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        if not link:
            continue
        snippet_node = result.select_one(".result__snippet")
        href = link.get("href", "")
        results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": href,
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
        if len(results) >= max(1, min(max_results, 10)):
            break
    return {"ok": True, "query": query, "results": results}


async def fetch_web_page(url: str, max_chars: int = 20_000) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=25,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            body, final_url, content_type = await _bounded_public_get(
                client,
                url,
                max_bytes=MAX_RESPONSE_BYTES,
            )
        if "text" not in content_type and "json" not in content_type and "xml" not in content_type:
            return {"ok": False, "error": f"Unsupported content type: {content_type}"}
        text_body = body.decode("utf-8", errors="replace")
    except (httpx.HTTPError, OSError, ValueError) as exc:
        detail = str(sanitize_for_persistence(str(exc)))
        return {"ok": False, "error": f"Page fetch failed: {detail}"}

    soup = BeautifulSoup(text_body, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        element.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else final_url
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return {
        "ok": True,
        "url": final_url,
        "title": title,
        "content": text[:max(1000, min(max_chars, 50_000))],
    }

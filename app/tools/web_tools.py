from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 DPN-AI/1.0"


def _safe_public_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "Only public http/https URLs are allowed"
    if parsed.username or parsed.password:
        return False, "URLs with embedded credentials are blocked"
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return False, "Local network URLs are blocked"
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return False, "Private or reserved network addresses are blocked"
    except socket.gaierror:
        return False, "Hostname could not be resolved"
    return True, ""


async def search_web(query: str, max_results: int = 6) -> dict[str, Any]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Web search failed: {exc}"}
    soup = BeautifulSoup(response.text, "html.parser")
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
    safe, reason = _safe_public_url(url)
    if not safe:
        return {"ok": False, "error": reason}
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(url)
            response.raise_for_status()
            if int(response.headers.get("content-length", "0") or 0) > 2_000_000:
                return {"ok": False, "error": "Page is larger than the 2 MB safety limit"}
            content_type = response.headers.get("content-type", "")
            if "text" not in content_type and "json" not in content_type and "xml" not in content_type:
                return {"ok": False, "error": f"Unsupported content type: {content_type}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Page fetch failed: {exc}"}
    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        element.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return {"ok": True, "url": str(response.url), "title": title, "content": text[:max(1000, min(max_chars, 50_000))]}
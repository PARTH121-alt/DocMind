"""Fetch a web page and reduce it to clean text.

Users supply arbitrary URLs, so the fetcher is treated as a trust boundary:

* Only http/https.
* The hostname is resolved and every resulting IP is checked against the
  private, loopback, link-local and reserved ranges. This blocks SSRF against
  cloud metadata endpoints (169.254.169.254), internal admin panels and
  localhost, and re-checks after redirects.
* Redirects are followed manually so each hop is validated.
* Responses are size- and time-bounded, and non-HTML content is rejected.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Origin/1.0 (https://github.com/PARTH121-alt/DocMind; document Q&A assistant)"
)

MAX_BYTES = 3_000_000
FETCH_TIMEOUT = 20.0
MAX_REDIRECTS = 4

ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/xml")


class FetchError(RuntimeError):
    """Raised when a URL cannot be safely or successfully fetched."""


@dataclass
class FetchedPage:
    url: str
    final_url: str
    title: str
    text: str
    status: int
    content_type: str


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when an IP must not be fetched."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> None:
    """Validate a URL for outbound fetching.

    Raises FetchError if the scheme is unsupported or the host resolves to a
    non-public address. Called for the initial URL *and* every redirect target.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"Only http and https URLs are supported (got '{parsed.scheme}').")

    host = parsed.hostname
    if not host:
        raise FetchError("The URL has no hostname.")

    # Reject literal IPs outright if they are non-public.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_is_blocked(literal):
            raise FetchError(f"Refusing to fetch a private or reserved address ({host}).")
        return

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve '{host}': {exc}") from exc

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise FetchError(
                f"Refusing to fetch '{host}': it resolves to the private or "
                f"reserved address {ip}."
            )


def _extract(html: str, base_url: str) -> tuple[str, str]:
    """Return (title, cleaned text) from an HTML document."""
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=base_url,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            output_format="txt",
        )
        metadata = trafilatura.extract_metadata(html, default_url=base_url)
        title = (metadata.title if metadata else None) or ""
        if text:
            return title.strip(), text.strip()
    except Exception as exc:  # pragma: no cover - extractor is best-effort
        logger.debug("trafilatura failed: %s", exc)

    # Fallback: strip markup with lxml and keep paragraph text.
    try:
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(html)
        for bad in tree.xpath("//script|//style|//noscript|//nav|//footer|//header|//aside|//form"):
            bad.getparent().remove(bad)
        title = (tree.findtext(".//title") or "").strip()
        chunks = [
            " ".join(t.split())
            for t in tree.xpath("//p//text() | //h1//text() | //h2//text() | //h3//text() | //li//text()")
            if t and t.strip()
        ]
        return title, "\n".join(chunks)
    except Exception as exc:
        raise FetchError(f"Could not parse the page as HTML: {exc}") from exc


def fetch_url(url: str, *, max_chars: int | None = None) -> FetchedPage:
    """Fetch a single page safely and return its extracted text."""
    url = url.strip()
    assert_public_url(url)

    max_chars = max_chars or settings.max_web_chars
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en;q=0.9",
    }

    current = url
    with httpx.Client(follow_redirects=False, timeout=FETCH_TIMEOUT, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = client.get(current)
            except httpx.HTTPError as exc:
                raise FetchError(f"Request to {current} failed: {exc}") from exc

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("Redirect response had no Location header.")
                # Validate the next hop before following it.
                current = urljoin(current, location)
                assert_public_url(current)
                continue

            if response.status_code >= 400:
                raise FetchError(
                    f"{current} returned HTTP {response.status_code}."
                )

            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and not any(content_type.startswith(t) for t in ALLOWED_CONTENT_TYPES):
                raise FetchError(
                    f"Unsupported content type '{content_type}'. Only web pages and plain "
                    "text can be analysed."
                )

            raw = response.content
            if len(raw) > MAX_BYTES:
                raise FetchError(
                    f"Page is too large ({len(raw) // 1024}KB, limit {MAX_BYTES // 1024}KB)."
                )

            if content_type.startswith("text/plain"):
                title = urlparse(current).hostname or current
                text = raw.decode("utf-8", errors="replace")
            else:
                html = raw.decode(response.encoding or "utf-8", errors="replace")
                title, text = _extract(html, current)

            if not text.strip():
                raise FetchError("No readable text was found on that page.")

            return FetchedPage(
                url=url,
                final_url=current,
                title=title or (urlparse(current).hostname or current),
                text=text[:max_chars],
                status=response.status_code,
                content_type=content_type,
            )

    raise FetchError("Too many redirects.")
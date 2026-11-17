"""SSRF-hardened product page ingestion.

Fetching user-supplied URLs from a server is a classic SSRF vector, so every hop:
  * allows only http/https on default ports, with no embedded credentials;
  * resolves DNS once and rejects the URL if ANY address is not globally routable
    (loopback, private, link-local/cloud metadata, carrier-grade NAT, multicast, reserved);
  * connects to that pinned IP (Host header + TLS SNI keep virtual hosting and certificate
    verification intact), so a second DNS answer cannot rebind to an internal address;
  * follows redirects manually, re-validating each location;
  * streams bodies under a byte cap and an overall timeout.
Page content is untrusted data: it is passed to the copywriter as data, never as instructions.
"""
import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import httpx
from app.core.config import get_settings
from app.services.ai.provider import GenerationError
from app.services.storage.local import decode_image, save_still

MAX_HTML_BYTES = 2 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; SocialStudioPreview/1.0; product preview fetcher)"
Resolver = Callable[[str, int], list[str]]


class UrlRejected(ValueError):
    """A URL that must not be fetched; the message is safe to show users."""


@dataclass
class Fetched:
    url: str
    content_type: str
    body: bytes


def system_resolver(host: str, port: int) -> list[str]:
    try:
        return list({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except (socket.gaierror, UnicodeError) as exc:
        raise UrlRejected("That website address could not be found.") from exc


def validate_url(raw: str) -> tuple[str, str, int]:
    """Return (normalized url, ascii hostname, port) or raise UrlRejected."""
    raw = raw.strip()
    if not raw or len(raw) > 2048:
        raise UrlRejected("Enter a product page URL up to 2048 characters.")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise UrlRejected("Enter a valid http:// or https:// product URL.") from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UrlRejected("Enter a valid http:// or https:// product URL.")
    if parts.username or parts.password:
        raise UrlRejected("URLs with embedded credentials are not allowed.")
    default = 443 if parts.scheme == "https" else 80
    if port not in (None, default):
        raise UrlRejected("Only standard web ports are supported for product URLs.")
    try:
        host = parts.hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UrlRejected("That website address is not valid.") from exc
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UrlRejected("Only public websites can be used as product URLs.")
    return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, "")), host, default


def public_address(host: str, port: int, resolver: Resolver = system_resolver) -> str:
    addresses = resolver(host, port)
    if not addresses:
        raise UrlRejected("That website address could not be found.")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        # Reject if any answer is internal: a mixed answer set is a rebinding signal.
        if not ip.is_global or ip.is_multicast:
            raise UrlRejected("Only public websites can be used as product URLs.")
    return sorted(addresses)[0]


def check_url(raw: str, resolver: Resolver = system_resolver) -> str:
    url, host, port = validate_url(raw)
    public_address(host, port, resolver)
    return url


def fetch(raw: str, accept: str, max_bytes: int, *, resolver: Resolver = system_resolver,
          transport: httpx.BaseTransport | None = None) -> Fetched:
    settings = get_settings()
    url = raw
    timeout = httpx.Timeout(settings.url_fetch_timeout_seconds)
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
        for _ in range(settings.url_max_redirects + 1):
            url, host, port = validate_url(url)
            ip = public_address(host, port, resolver)
            parts = urlsplit(url)
            pinned = urlunsplit((parts.scheme, f"[{ip}]" if ":" in ip else ip, parts.path, parts.query, ""))
            headers = {"Host": host, "User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity"}
            try:
                with client.stream("GET", pinned, headers=headers, extensions={"sni_hostname": host}) as response:
                    if response.status_code in (301, 302, 303, 307, 308) and "location" in response.headers:
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code in (401, 403, 429):
                        raise GenerationError("URL_BLOCKED", "That website blocked automated access. "
                                              "Upload the product image or video instead.")
                    if response.status_code != 200:
                        raise GenerationError("URL_FETCH_FAILED", f"The product page returned HTTP {response.status_code}. "
                                              "Check the URL or upload the product image instead.")
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > max_bytes:
                        raise GenerationError("URL_TOO_LARGE", "The linked file is too large to process.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise GenerationError("URL_TOO_LARGE", "The linked file is too large to process.")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    return Fetched(url, content_type, bytes(body))
            except httpx.TimeoutException as exc:
                raise GenerationError("URL_TIMEOUT", "The product page took too long to respond. Try again or upload "
                                      "the product image instead.", transient=True) from exc
            except httpx.HTTPError as exc:
                raise GenerationError("URL_FETCH_FAILED", "The product page could not be reached. Check the URL "
                                      "or upload the product image instead.", transient=True) from exc
    raise GenerationError("URL_FETCH_FAILED", "The product page redirected too many times.")


class ProductPageParser(HTMLParser):
    """Collects Open Graph / Twitter / standard metadata from untrusted HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.image_src = ""
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and values.get("content") and key not in self.meta:
                self.meta[key] = values["content"].strip()
        elif tag == "link" and "image_src" in values.get("rel", "").lower() and not self.image_src:
            self.image_src = values.get("href", "").strip()
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 300:
            self.title += data


def clean(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


def ingest_url(source_url: str, directory: Path, *, resolver: Resolver = system_resolver,
               transport: httpx.BaseTransport | None = None) -> tuple[str, dict]:
    """Fetch a product page (or direct image URL), save the product image, and return metadata."""
    max_image = get_settings().max_upload_size_mb * 1024 * 1024
    try:
        page = fetch(source_url, "text/html,application/xhtml+xml,image/*;q=0.8", max(MAX_HTML_BYTES, max_image),
                     resolver=resolver, transport=transport)
    except UrlRejected as exc:
        raise GenerationError("URL_REJECTED", str(exc)) from exc
    metadata = {"page_url": page.url, "title": "", "description": "", "site_name": "", "image_url": page.url}
    if page.content_type.startswith("image/"):
        image = page
    elif page.content_type in {"text/html", "application/xhtml+xml"}:
        parser = ProductPageParser()
        parser.feed(page.body[:MAX_HTML_BYTES].decode("utf-8", errors="replace"))
        meta = parser.meta
        metadata.update(
            title=clean(meta.get("og:title") or meta.get("twitter:title") or parser.title, 200),
            description=clean(meta.get("og:description") or meta.get("twitter:description")
                              or meta.get("description", ""), 500),
            site_name=clean(meta.get("og:site_name", ""), 80))
        candidate = (meta.get("og:image:secure_url") or meta.get("og:image") or meta.get("og:image:url")
                     or meta.get("twitter:image") or meta.get("twitter:image:src") or parser.image_src)
        if not candidate:
            raise GenerationError("URL_NO_IMAGE", "No product image was found on that page. "
                                  "Upload the product image instead.")
        metadata["image_url"] = urljoin(page.url, candidate)[:2048]
        try:
            image = fetch(metadata["image_url"], "image/*", max_image, resolver=resolver, transport=transport)
        except UrlRejected as exc:
            raise GenerationError("URL_NO_IMAGE", "The page's product image is not on a public address. "
                                  "Upload the product image instead.") from exc
    else:
        raise GenerationError("URL_UNSUPPORTED", "That URL is not a product web page or image. "
                              "Use a product page link or upload the image instead.")
    try:
        canvas = decode_image(image.body)
    except ValueError as exc:
        raise GenerationError("URL_NO_IMAGE", "The product image on that page could not be read. "
                              "Upload the product image instead.") from exc
    return save_still(canvas, directory), metadata

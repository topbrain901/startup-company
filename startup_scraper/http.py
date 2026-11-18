from __future__ import annotations

import http.client
import json
import random
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


class HttpClient:
    def __init__(self, user_agent: str = "StartupFundingCollector/1.0", timeout: int = 45):
        self.user_agent = user_agent
        self.timeout = timeout

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        retries: int = 3,
    ) -> bytes:
        request_headers = {"User-Agent": self.user_agent, "Accept-Encoding": "identity"}
        request_headers.update(headers or {})
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                    detail = exc.read().decode("utf-8", "replace")[:1000]
                    raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == retries:
                    raise RuntimeError(f"Request failed for {url}: {exc}") from exc
                delay = 2**attempt
            time.sleep(delay + random.random() * 0.25)
        raise AssertionError("unreachable")

    def json(self, url: str, **kwargs: Any) -> Any:
        return json.loads(self.request(url, **kwargs))


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int
    content_type: str = ""
    body: bytes = b""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and self.error is None

    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class HostThrottle:
    """Minimum interval between requests to the same host, shared across worker threads."""

    default_interval: float = 0.5
    intervals: dict[str, float] = field(default_factory=dict)
    _next: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def wait(self, host: str) -> None:
        interval = self.intervals.get(host, self.default_interval)
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next.get(host, 0.0))
            self._next[host] = slot + interval
        if slot > now:
            time.sleep(slot - now)


class WebClient:
    """Polite, non-raising HTTP client used by enrichment.

    - identifies itself with a bot user agent and honours robots.txt for HTML pages
    - rate-limits per host, caps response size, and never raises on HTTP errors
    """

    def __init__(
        self,
        user_agent: str = "Mozilla/5.0 (compatible; FundingRadarBot/1.0)",
        timeout: float = 8,
        max_bytes: int = 1_500_000,
        throttle: HostThrottle | None = None,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.throttle = throttle or HostThrottle(
            intervals={
                "www.ycombinator.com": 0.6,
                "www.wikidata.org": 0.3,
                "rdap.org": 1.0,
                "boards-api.greenhouse.io": 0.3,
                "api.lever.co": 0.3,
                "api.ashbyhq.com": 0.3,
            }
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()
        self._insecure = ssl.create_default_context()
        self._insecure.check_hostname = False
        self._insecure.verify_mode = ssl.CERT_NONE

    def fetch(
        self,
        url: str,
        *,
        accept: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        max_bytes: int | None = None,
        respect_robots: bool = True,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return FetchResult(url=url, status=0, error="invalid url")
        if respect_robots and not self.allowed(url):
            return FetchResult(url=url, status=0, error="blocked by robots.txt")
        self.throttle.wait(parsed.hostname)
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.8",
            "Accept-Encoding": "identity",
        }
        request_headers.update(headers or {})
        request = urllib.request.Request(url, headers=request_headers)
        limit = max_bytes or self.max_bytes
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                try:
                    body = response.read(limit)
                except http.client.IncompleteRead as exc:
                    body = exc.partial  # truncated responses still carry usable HTML
                return FetchResult(
                    url=response.geturl(),
                    status=response.status,
                    content_type=response.headers.get("Content-Type", ""),
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            return FetchResult(url=exc.geturl() or url, status=exc.code, error=f"HTTP {exc.code}")
        except urllib.error.URLError as exc:
            reason = exc.reason
            # Small-company sites often have broken certificate chains; the page content is
            # still useful for verification, and nothing sensitive is sent.
            if isinstance(reason, ssl.SSLError):
                try:
                    with urllib.request.urlopen(request, timeout=self.timeout, context=self._insecure) as response:
                        return FetchResult(
                            url=response.geturl(),
                            status=response.status,
                            content_type=response.headers.get("Content-Type", ""),
                            body=response.read(limit),
                        )
                except Exception as retry_exc:  # noqa: BLE001 - network failures are data here
                    return FetchResult(url=url, status=0, error=str(retry_exc)[:200])
            return FetchResult(url=url, status=0, error=str(reason)[:200])
        except (TimeoutError, socket.timeout, ConnectionError, OSError, ValueError, http.client.HTTPException) as exc:
            return FetchResult(url=url, status=0, error=str(exc)[:200] or exc.__class__.__name__)

    def fetch_json(self, url: str, *, max_bytes: int = 8_000_000) -> Any | None:
        result = self.fetch(url, accept="application/json", max_bytes=max_bytes, respect_robots=False)
        if not result.ok:
            return None
        try:
            return result.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with self._robots_lock:
            cached = self._robots.get(origin, False)
        if cached is False:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            result = self.fetch(f"{origin}/robots.txt", accept="text/plain", max_bytes=300_000, respect_robots=False)
            if result.status in {401, 403}:
                parser.disallow_all = True  # type: ignore[union-attr]
            elif result.ok and "html" not in result.content_type.lower():
                parser.parse(result.text().splitlines())  # type: ignore[union-attr]
            else:
                parser = None  # no robots.txt: everything allowed
            with self._robots_lock:
                self._robots[origin] = parser
            cached = parser
        if cached is None:
            return True
        return cached.can_fetch(self.user_agent, url) and cached.can_fetch("FundingRadarBot", url)


PUBLIC_RESOLVERS = ("1.1.1.1", "8.8.8.8")
_dns_cache: dict[str, bool] = {}
_dns_lock = threading.Lock()
_udp_dns_works: bool | None = None


def _udp_query(host: str, server: str, timeout: float = 2.0) -> bool | None:
    """Minimal DNS A-record query. True = has answers, False = NXDOMAIN/no data, None = no reply."""
    try:
        labels = host.encode("idna").split(b".")
    except UnicodeError:
        return False
    query_id = random.randint(0, 0xFFFF)
    packet = query_id.to_bytes(2, "big") + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    packet += b"".join(len(label).to_bytes(1, "big") + label for label in labels if label) + b"\x00\x00\x01\x00\x01"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (server, 53))
            while True:
                data, _ = sock.recvfrom(4096)
                if len(data) >= 12 and int.from_bytes(data[:2], "big") == query_id:
                    break
        except OSError:
            return None
    rcode = data[3] & 0x0F
    answers = int.from_bytes(data[6:8], "big")
    return rcode == 0 and answers > 0


def _doh_query(host: str) -> bool | None:
    try:
        request = urllib.request.Request(
            f"https://dns.google/resolve?type=A&name={host}", headers={"Accept": "application/dns-json"}
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            data = json.loads(response.read())
        return data.get("Status") == 0 and bool(data.get("Answer"))
    except Exception:  # noqa: BLE001
        return None


def resolves(host: str) -> bool:
    """Whether a hostname has an A record. Uses public resolvers directly because the OS
    resolver can take ~10s per non-existent name (notably on Windows)."""
    global _udp_dns_works
    host = host.strip(".").lower()
    if not host or "." not in host:
        return False
    with _dns_lock:
        if host in _dns_cache:
            return _dns_cache[host]
    answer: bool | None = None
    if _udp_dns_works is not False:
        for server in PUBLIC_RESOLVERS:
            answer = _udp_query(host, server)
            if answer is not None:
                _udp_dns_works = True
                break
        if answer is None and _udp_dns_works is None:
            _udp_dns_works = False  # outbound DNS blocked on this network; stop trying
    if answer is None:
        answer = _doh_query(host)
    if answer is None:
        try:
            answer = bool(socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP))
        except (socket.gaierror, UnicodeError, OSError):
            answer = False
    with _dns_lock:
        if len(_dns_cache) > 50_000:
            _dns_cache.clear()
        _dns_cache[host] = answer
    return answer

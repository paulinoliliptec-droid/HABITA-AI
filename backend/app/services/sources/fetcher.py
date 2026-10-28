"""The only way HABITA fetches official source content.

Callers pass a registry source's verified URL; nothing derived from model output
ever reaches here (no tool takes a URL). Every request and every redirect hop:

- must be https on port 443, without credentials, to an exact allowlisted host;
- must resolve only to public (global) IP addresses: private, loopback,
  link-local (incl. cloud metadata), multicast and reserved ranges are refused;
- is followed manually (at most ``max_redirects``), re-checking each hop;
- is capped in size and restricted to expected content types.

Residual risk, accepted for HR-003: the IP check happens just before httpx connects
(no IP pinning), so a DNS answer could change in between. The allowlist contains only
official government hosts, whose DNS an attacker does not control.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx

Resolver = Callable[[str], Awaitable[list[str]]]

DEFAULT_TYPES = frozenset({"application/pdf", "text/html", "application/xml", "text/xml", "application/json"})


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    retrieved_at: datetime


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


class SafeFetcher:
    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
        max_bytes: int = 25 * 1024 * 1024,
        max_redirects: int = 3,
        timeout_seconds: float = 60.0,
        allowed_types: frozenset[str] = DEFAULT_TYPES,
    ) -> None:
        self._hosts = frozenset(h.lower() for h in allowed_hosts)
        self._transport = transport
        self._resolve = resolver
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._timeout = timeout_seconds
        self._types = allowed_types

    async def check_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise FetchError("only https URLs can be fetched")
        if parts.username or parts.password:
            raise FetchError("URLs with credentials are refused")
        if parts.port not in (None, 443):
            raise FetchError("only the default https port is allowed")
        host = (parts.hostname or "").lower()
        if host not in self._hosts:
            raise FetchError(f"host {host or '(none)'} is not an allowlisted official host")
        try:
            addresses = await self._resolve(host)
        except OSError:
            raise FetchError(f"could not resolve {host}") from None
        if not addresses:
            raise FetchError(f"could not resolve {host}")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if not ip.is_global or ip.is_multicast:
                raise FetchError(f"{host} resolves to a non-public address")

    async def fetch(self, url: str) -> FetchResult:
        current = url
        async with httpx.AsyncClient(
            transport=self._transport, timeout=self._timeout, follow_redirects=False, trust_env=False,
            headers={"User-Agent": "HABITA-source-ingestion/1.0"},
        ) as client:
            for _ in range(self._max_redirects + 1):
                await self.check_url(current)
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("redirect without a location")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise FetchError(f"HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if content_type not in self._types:
                        raise FetchError(f"unexpected content type {content_type or '(none)'}")
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > self._max_bytes:
                        raise FetchError("document exceeds the size limit")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_bytes:
                            raise FetchError("document exceeds the size limit")
                    return FetchResult(url, current, response.status_code, content_type, bytes(body), datetime.now(UTC))
        raise FetchError("too many redirects")

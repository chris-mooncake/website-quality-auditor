"""
Guards against server-side request forgery (SSRF).

User-supplied URLs are fetched directly by this application (single-page
scans, crawls, and robots.txt lookups), so without a check here a malicious
or careless input, an internal hostname, a cloud metadata address, or a
redirect chain that hops to one, could make the server fetch data it should
never expose. `ensure_public_url` resolves a URL's host and rejects it unless
every resolved address is public and routable. `SafeTransport` applies that
check at the HTTPX transport layer so it also covers redirect hops.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx


class UnsafeUrlError(ValueError):
    """Raised when a URL's host does not resolve to a public address."""


class BlockedUrlError(httpx.RequestError):
    """Raised by SafeTransport when a request targets a non-public address."""


def ensure_public_url(url: str) -> None:
    """Raise UnsafeUrlError unless the URL's host resolves only to public addresses."""

    hostname = urlsplit(url).hostname

    if hostname is None:
        raise UnsafeUrlError("The URL does not have a hostname.")

    try:
        resolved_addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as error:
        raise UnsafeUrlError(f"Could not resolve host {hostname!r}.") from error

    if not resolved_addresses:
        raise UnsafeUrlError(f"Could not resolve host {hostname!r}.")

    for *_rest, sockaddr in resolved_addresses:
        address = ipaddress.ip_address(sockaddr[0])

        if not _is_public_address(address):
            raise UnsafeUrlError(
                f"Host {hostname!r} resolves to a non-public address ({address}) "
                "and cannot be scanned."
            )


def _is_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return whether an address is safe to connect to from this application."""

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped

    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False

    return not getattr(address, "is_site_local", False)


class SafeTransport(httpx.BaseTransport):
    """
    Wrap an HTTPX transport and block requests to non-public hosts.

    HTTPX calls `handle_request` once per hop when following redirects, so
    wrapping the transport (rather than checking only the original URL) also
    re-validates every redirect target. This narrows, but does not fully
    close, DNS-rebinding races: the address checked here could differ from
    the one the wrapped transport ultimately connects to if the hostname's
    DNS record changes between these two calls.
    """

    def __init__(self, wrapped: httpx.BaseTransport) -> None:
        self._wrapped = wrapped

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            ensure_public_url(str(request.url))
        except UnsafeUrlError as error:
            raise BlockedUrlError(str(error), request=request) from error

        return self._wrapped.handle_request(request)

    def close(self) -> None:
        self._wrapped.close()

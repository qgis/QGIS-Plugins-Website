"""
Outbound HTTP that refuses to talk to internal hosts.

The plugin validator fetches author supplied tracker, repository and homepage
urls to check they resolve. Without a guard that lets an author point the
server at its own network: loopback, private ranges, the link local range, and
so on. This module gives back a requests session that validates the real peer
address of every connection, including every redirect hop, so a url that
resolves or redirects to an internal address is refused at connect time rather
than fetched.

The check runs on the socket that is actually connected, read with
``getpeername``, not on a name we resolved ourselves earlier. That closes the
dns rebinding gap where a name resolves to a public address when we look and to
an internal one when requests connects a moment later.
"""

import ipaddress

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import PoolManager


class BlockedAddressError(Exception):
    """Raised when a connection resolves to an address we will not reach."""


def is_blocked_address(host: str) -> bool:
    """
    True when ``host`` is an ip we refuse to connect to: loopback, private
    (RFC1918 and IPv6 unique local), link local (including the cloud metadata
    address 169.254.169.254), reserved, multicast, or the unspecified address.

    Several flags are checked rather than ``is_private`` alone so the policy is
    explicit and does not shift if that property's definition changes.
    """
    # getpeername on an IPv6 socket can return a scoped address (fe80::1%eth0);
    # ip_address does not accept the scope, so drop it before parsing.
    host = host.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not a literal address. We only ever pass the connected peer here, so
        # this should not happen; refuse rather than guess.
        return True
    return any(
        (
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_reserved,
            ip.is_multicast,
            ip.is_unspecified,
        )
    )


def _validate_peer(sock):
    try:
        peer = sock.getpeername()[0]
    except (OSError, AttributeError):
        # No connected socket to inspect means no safe way to continue.
        raise BlockedAddressError("no peer address")
    if is_blocked_address(peer):
        raise BlockedAddressError(peer)


class _GuardedHTTPConnection(HTTPConnection):
    def connect(self):
        super().connect()
        try:
            _validate_peer(self.sock)
        except BlockedAddressError:
            self.close()
            raise


class _GuardedHTTPSConnection(HTTPSConnection):
    def connect(self):
        super().connect()
        try:
            _validate_peer(self.sock)
        except BlockedAddressError:
            self.close()
            raise


class _GuardedHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _GuardedHTTPConnection


class _GuardedHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _GuardedHTTPSConnection


class _GuardedPoolManager(PoolManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = {
            "http": _GuardedHTTPConnectionPool,
            "https": _GuardedHTTPSConnectionPool,
        }


class SafeHTTPAdapter(HTTPAdapter):
    """A requests adapter whose every connection validates its peer address."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = _GuardedPoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


def build_safe_session() -> requests.Session:
    """A session that refuses internal hosts on http and https, redirects too."""
    session = requests.Session()
    adapter = SafeHTTPAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

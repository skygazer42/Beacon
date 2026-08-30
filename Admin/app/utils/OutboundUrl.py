import ipaddress
import os
import socket
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit


class OutboundUrlError(ValueError):
    """Raised when an outbound HTTP URL violates the egress policy."""


_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALWAYS_DENIED_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
    }
)


def _csv_values(*names: str) -> list[str]:
    values: list[str] = []
    for name in names:
        if not name:
            continue
        raw = str(os.environ.get(name, "") or "")
        values.extend(item.strip() for item in raw.split(",") if item.strip())
    return values


def _normalize_host(value: str) -> str:
    host = str(value or "").strip().rstrip(".").lower()
    if not host:
        raise OutboundUrlError("outbound URL host is required")
    if any(ch in host for ch in ("/", "\\", "@", "\x00", "\r", "\n")):
        raise OutboundUrlError("outbound URL host is invalid")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise OutboundUrlError("outbound URL host is invalid") from exc


def _allowed_hosts(env_name: str) -> set[str]:
    hosts: set[str] = set()
    for value in _csv_values("BEACON_OUTBOUND_ALLOWED_HOSTS", env_name):
        if "*" in value:
            raise OutboundUrlError("outbound host allowlists do not support wildcards")
        hosts.add(_normalize_host(value))
    return hosts


def _allowed_networks(env_name: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for value in _csv_values("BEACON_OUTBOUND_ALLOWED_CIDRS", env_name):
        try:
            network = ipaddress.ip_network(value, strict=True)
        except ValueError as exc:
            raise OutboundUrlError(f"invalid outbound CIDR: {value}") from exc
        if network.prefixlen == 0:
            raise OutboundUrlError("outbound CIDR must not allow the entire address space")
        networks.append(network)
    return networks


def _resolve_host_ips(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return {literal}

    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise OutboundUrlError("outbound URL host cannot be resolved") from exc

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for row in rows:
        try:
            addresses.add(ipaddress.ip_address(row[4][0]))
        except (IndexError, TypeError, ValueError):
            continue
    if not addresses:
        raise OutboundUrlError("outbound URL host cannot be resolved")
    return addresses


def _is_in_networks(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def _validate_resolved_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    host_is_explicitly_allowed: bool,
    expected_host: bool,
    allowed_networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address in _ALWAYS_DENIED_IPS or address.is_unspecified or address.is_multicast:
        raise OutboundUrlError("outbound URL resolves to a forbidden address")
    if address.is_loopback:
        if host_is_explicitly_allowed or _is_in_networks(address, allowed_networks):
            return
        raise OutboundUrlError("outbound URL loopback targets require an explicit host or CIDR allowlist")
    if expected_host:
        return
    if _is_in_networks(address, allowed_networks):
        return
    if host_is_explicitly_allowed and not address.is_link_local:
        return
    if not address.is_global:
        raise OutboundUrlError("private outbound targets require an explicit host or CIDR allowlist")


def validate_outbound_http_url(
    value: str,
    *,
    allowed_hosts_env: str = "",
    allowed_cidrs_env: str = "",
    expected_host: str = "",
    require_https: bool = False,
) -> str:
    """Validate and canonicalize an outbound HTTP(S) URL.

    Public destinations are allowed by default. Private destinations must be
    explicitly listed in the supplied environment allowlist. ONVIF callers can
    set ``expected_host`` so device-advertised endpoints cannot pivot to a
    different host.
    """

    canonical = canonicalize_outbound_http_url(value, require_https=require_https)
    parsed = urlsplit(canonical)
    host = _normalize_host(parsed.hostname or "")
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    expected = _normalize_host(expected_host) if expected_host else ""
    if expected and host != expected:
        raise OutboundUrlError("outbound URL host does not match the expected device")

    allowed_hosts = _allowed_hosts(allowed_hosts_env)
    allowed_networks = _allowed_networks(allowed_cidrs_env)
    resolved = _resolve_host_ips(host, port)
    for address in resolved:
        _validate_resolved_address(
            address,
            host_is_explicitly_allowed=host in allowed_hosts,
            expected_host=bool(expected),
            allowed_networks=allowed_networks,
        )

    return canonical


def canonicalize_outbound_http_url(value: str, *, require_https: bool = False) -> str:
    """Perform side-effect-free HTTP URL syntax validation and normalization.

    This helper does not resolve DNS and therefore is not sufficient at a
    network sink. Call :func:`validate_outbound_http_url` immediately before
    every outbound request.
    """

    raw = str(value or "").strip()
    if not raw or len(raw) > 4096:
        raise OutboundUrlError("outbound URL is required")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw) or "\\" in raw:
        raise OutboundUrlError("outbound URL contains invalid characters")

    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise OutboundUrlError("outbound URL is invalid") from exc

    scheme = str(parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES or (require_https and scheme != "https"):
        raise OutboundUrlError("outbound URL must use an allowed HTTP scheme")
    if parsed.username is not None or parsed.password is not None:
        raise OutboundUrlError("credentials are not allowed in outbound URLs")
    if parsed.fragment:
        raise OutboundUrlError("fragments are not allowed in outbound URLs")

    host = _normalize_host(parsed.hostname or "")
    port = int(port or (443 if scheme == "https" else 80))
    if port < 1 or port > 65535:
        raise OutboundUrlError("outbound URL port is invalid")

    display_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    netloc = display_host if port == default_port else f"{display_host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))

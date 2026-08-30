from urllib.parse import unquote, urlsplit, urlunsplit


def _clean_url(value) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 2048:
        return ""
    if any(ord(char) < 32 or ord(char) == 127 for char in raw) or "\\" in raw:
        return ""
    return raw


def _local_url(raw: str, *, allowed_prefixes) -> str:
    if not raw.startswith("/") or raw.startswith("//"):
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return ""
    # Local branding assets are generated with plain URL-safe paths. Reject
    # percent-encoded paths rather than leaving decoding differences between
    # the browser, reverse proxy, and application server exploitable.
    if "%" in parsed.path:
        return ""
    decoded_path = unquote(parsed.path)
    if (
        "\\" in decoded_path
        or not decoded_path.startswith("/")
        or any(ord(char) < 32 or ord(char) == 127 for char in decoded_path)
    ):
        return ""
    if any(part in (".", "..") for part in decoded_path.split("/")):
        return ""
    if allowed_prefixes and not any(decoded_path.startswith(prefix) for prefix in allowed_prefixes):
        return ""
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))


def normalize_ui_url(value, *, allow_external: bool, allowed_local_prefixes=("/",)) -> str:
    """Return a browser-safe local path or credential-free HTTPS URL."""

    raw = _clean_url(value)
    if not raw:
        return ""
    if raw.startswith("/"):
        return _local_url(raw, allowed_prefixes=tuple(allowed_local_prefixes or ()))
    if not allow_external:
        return ""
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return ""
        if parsed.username or parsed.password:
            return ""
        # Accessing .port also rejects malformed/out-of-range ports.
        _ = parsed.port
    except (TypeError, ValueError):
        return ""
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def normalize_ui_image_url(value) -> str:
    return normalize_ui_url(
        value,
        allow_external=True,
        allowed_local_prefixes=("/static/", "/managed-upload/"),
    )


def normalize_ui_link_url(value) -> str:
    return normalize_ui_url(value, allow_external=True, allowed_local_prefixes=("/",))


def normalize_ui_static_asset_url(value) -> str:
    return normalize_ui_url(value, allow_external=False, allowed_local_prefixes=("/static/",))

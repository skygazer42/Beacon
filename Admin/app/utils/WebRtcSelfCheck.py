import logging
import re
import socket



logger = logging.getLogger(__name__)
_ICE_URL_RE = re.compile(
    r"^(?P<scheme>stun|turn|turns):(?P<host>[^:/?#]+)(?::(?P<port>\d+))?(?:\?transport=(?P<transport>udp|tcp))?$",
    re.IGNORECASE,
)


def _default_ice_port(scheme: str) -> int:
    """返回默认ICE端口。"""
    return 5349 if scheme == "turns" else 3478


def _parse_ice_port(value, *, scheme: str):
    """解析ICE端口。"""
    default = _default_ice_port(scheme)
    try:
        port = int(value or default)
    except Exception:
        port = default
    if port < 1 or port > 65535:
        return None
    return port


def _normalize_ice_transport(value, *, scheme: str) -> str:
    """执行归一化ICE`transport`。"""
    transport = str(value or ("tcp" if scheme == "turns" else "udp")).lower()
    return transport if transport in ("udp", "tcp") else "udp"


def parse_ice_url(value):
    """解析ICEURL。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    match = _ICE_URL_RE.match(raw)
    if not match:
        return None

    scheme = str(match.group("scheme") or "").lower()
    host = str(match.group("host") or "").strip()
    if not host:
        return None

    port = _parse_ice_port(match.group("port"), scheme=scheme)
    if port is None:
        return None

    transport = _normalize_ice_transport(match.group("transport"), scheme=scheme)

    return {
        "raw": raw,
        "scheme": scheme,
        "host": host,
        "port": port,
        "transport": transport,
    }


def _resolve_host(host, port):
    """解析并返回主机。"""
    try:
        result = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return {"ok": True, "detail": f"resolved {len(result)} addr(s)"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _tcp_connect(host, port, timeout):
    """处理TCP连接。"""
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        return {"ok": True, "detail": "tcp connect ok"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}
    finally:
        try:
            if sock is not None:
                sock.close()
        except Exception:
            logger.debug("suppressed exception in app/utils/WebRtcSelfCheck.py:85", exc_info=True)


def _webrtc_selfcheck_timeout_seconds(config) -> int:
    """返回`webrtc``selfcheck`超时时间秒数。"""
    timeout = int(getattr(config, "webrtcSelfCheckTimeoutSeconds", 3) or 3)
    if timeout < 1:
        return 1
    if timeout > 30:
        return 30
    return timeout


def _stun_urls_from_config(config) -> list:
    """从配置中提取 STUN URL 列表。"""
    return [str(x or "").strip() for x in (getattr(config, "webrtcStunUrls", []) or []) if str(x or "").strip()]


def _append_stun_checks(checks: list, stun_urls: list) -> None:
    """追加STUN检查项。"""
    for idx, raw in enumerate(stun_urls):
        parsed = parse_ice_url(raw)
        syntax_ok = bool(parsed and str(parsed.get("scheme")) == "stun")
        checks.append(
            {
                "name": f"stun[{idx}].syntax",
                "ok": syntax_ok,
                "detail": "ok" if syntax_ok else "invalid ICE url",
            }
        )
        if parsed:
            checks.append(
                {
                    "name": f"stun[{idx}].resolve",
                    **_resolve_host(str(parsed["host"]), int(parsed["port"])),
                }
            )


def _turn_config_from_config(config):
    """从配置获取TURN配置。"""
    turn_url = str(getattr(config, "webrtcTurnUrl", "") or "").strip()
    turn_username = str(getattr(config, "webrtcTurnUsername", "") or "").strip()
    turn_password = str(getattr(config, "webrtcTurnPassword", "") or "").strip()
    return turn_url, turn_username, turn_password


def _append_turn_checks(checks: list, turn_url: str, timeout: int) -> None:
    """追加 TURN 检查项。"""
    if not turn_url:
        return

    parsed_turn = parse_ice_url(turn_url)
    syntax_ok = bool(parsed_turn and str(parsed_turn.get("scheme")) in ("turn", "turns"))
    checks.append(
        {
            "name": "turn.syntax",
            "ok": syntax_ok,
            "detail": "ok" if syntax_ok else "invalid ICE url",
        }
    )
    if not parsed_turn:
        return

    checks.append(
        {
            "name": "turn.resolve",
            **_resolve_host(str(parsed_turn["host"]), int(parsed_turn["port"])),
        }
    )
    if str(parsed_turn.get("transport")) == "tcp" or str(parsed_turn.get("scheme")) == "turns":
        checks.append(
            {
                "name": "turn.tcp_connect",
                **_tcp_connect(str(parsed_turn["host"]), int(parsed_turn["port"]), timeout),
            }
        )


def build_webrtc_selfcheck_report(config, zlm, *, app="", name="", public_host=""):
    """构建`webrtc``selfcheck``report`。"""
    timeout = _webrtc_selfcheck_timeout_seconds(config)
    stun_urls = _stun_urls_from_config(config)
    checks = []
    _append_stun_checks(checks, stun_urls)

    turn_url, turn_username, turn_password = _turn_config_from_config(config)
    turn = {
        "url": turn_url,
        "username_set": bool(turn_username),
        "password_set": bool(turn_password),
    }
    _append_turn_checks(checks, turn_url, timeout)

    return {
        "stun_urls": stun_urls,
        "turn": turn,
        "webrtc_api_url": zlm.get_webrtcApiUrl(app, name, public_host) if app and name else "",
        "webrtc_demo_url": zlm.get_webrtcDemoUrl(app, name, public_host) if app and name else "",
        "checks": checks,
        "overall_ok": bool(checks) and all(bool(item.get("ok")) for item in checks),
    }

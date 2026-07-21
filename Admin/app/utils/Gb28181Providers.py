import logging
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any
from typing import Dict, Optional, Tuple

import requests


logger = logging.getLogger(__name__)

_GB28181_ALLOWED_PLAY_URL_SCHEMES = ("rtsp", "rtsps", "rtmp", "rtmps", "http", "https")


def parse_gb28181_url(url: str) -> Tuple[str, str]:
    """解析`gb28181`URL。
    
    Parse: gb28181://{deviceId}@{channelId}
        Returns: (deviceId, channelId) or ("","") when invalid.
    """
    value = str(url or "").strip()
    if not value:
        return "", ""
    if not value.lower().startswith("gb28181://"):
        return "", ""

    rest = value[len("gb28181://"):]
    if "@" not in rest:
        return "", ""
    device_id, channel_id = rest.split("@", 1)
    device_id = urllib.parse.unquote(str(device_id or "").strip())
    channel_id = urllib.parse.unquote(str(channel_id or "").strip())
    if not device_id or not channel_id:
        return "", ""
    return device_id, channel_id


def _urlencode_gb_id(value: str) -> str:
    # Quote everything (including '/') to prevent template injection when ids are inserted
    # into URL path/query via format().
    """返回`urlencode``gb`ID。"""
    return urllib.parse.quote(str(value or "").strip(), safe="")


def _urlencode_template_value(value: Any) -> str:
    """返回`urlencode``template`值。"""
    return urllib.parse.quote(str(value or "").strip(), safe="")


def _render_template(base_url: str, template: str, device_id: str, channel_id: str, **extra_values: Any) -> str:
    """渲染`template`。"""
    tpl = str(template or "").strip()
    if not tpl:
        return ""

    rendered_values = {
        "deviceId": _urlencode_gb_id(device_id),
        "channelId": _urlencode_gb_id(channel_id),
    }
    for key, value in (extra_values or {}).items():
        rendered_values[str(key)] = _urlencode_template_value(value)

    url = tpl.format(**rendered_values)
    url = str(url or "").strip()

    if not url:
        return ""

    if re.match(r"^https?://", url, flags=re.IGNORECASE):
        return url

    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return url
    if not url.startswith("/"):
        url = "/" + url
    return base + url


def _parse_json_bytes_best_effort(content: bytes) -> Optional[Any]:
    """尽力处理`parse`JSON字节数。"""
    if not content:
        return None

    # Most vendors respond in UTF-8; some ecosystems still use GBK/GB18030 in practice.
    # We decode bytes ourselves to avoid relying on response headers.
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            text = content.decode(enc)
        except UnicodeDecodeError:
            continue

        text = str(text or "").strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except Exception:
            continue

    return None


def _extract_payload_best_effort(res) -> Any:
    """尽力处理提取载荷。"""
    content = getattr(res, "content", None)
    if isinstance(content, (bytes, bytearray)) and content:
        parsed = _parse_json_bytes_best_effort(bytes(content))
        if parsed is not None:
            return parsed

    # Fallback to requests' built-in json decoder (may rely on headers)
    try:
        return res.json()
    except Exception:
        return (getattr(res, "text", "") or "").strip()


def _validate_play_url(play_url: str) -> None:
    """校验播放URL。"""
    value = str(play_url or "").strip()
    if not value:
        raise ValueError("GB28181 provider response missing play_url/url")

    # Reject control chars to avoid log/HTTP header injection in downstream components.
    if any(c in value for c in ("\r", "\n", "\x00")):
        raise ValueError("GB28181 provider response contains invalid characters in play_url")

    # Prevent unexpected schemes such as file://, gopher:// ... which can be dangerous in SSRF chains.
    parsed = urllib.parse.urlparse(value)
    scheme = str(parsed.scheme or "").lower()
    if scheme and scheme not in _GB28181_ALLOWED_PLAY_URL_SCHEMES:
        raise ValueError(f"GB28181 provider returned unsafe play_url scheme: {scheme}")


_PLAY_URL_KEYS = ("play_url", "playUrl", "url", "playURL")


def _pick_first_nonempty_str(mapping: dict, keys: tuple) -> str:
    """选择首个非空字符串。"""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def _extract_play_url(payload) -> str:
    """提取播放URL。
    
    Try to extract play url from json payload (dict).
        Supports common formats:
        - {"play_url": "..."}
        - {"url": "..."}
        - {"data": {"url": "..."}}
        - {"data": {"playUrl": "..."}}
    """
    if isinstance(payload, str):
        return payload.strip()

    if not isinstance(payload, dict):
        return ""

    top = _pick_first_nonempty_str(payload, _PLAY_URL_KEYS)
    if top:
        return top

    data = payload.get("data")
    if isinstance(data, dict):
        nested = _pick_first_nonempty_str(data, _PLAY_URL_KEYS)
        if nested:
            return nested

        # some APIs nest deeper
        data2 = data.get("data")
        if isinstance(data2, dict):
            nested2 = _pick_first_nonempty_str(data2, ("play_url", "playUrl", "url"))
            if nested2:
                return nested2

    return ""


@dataclass
class Gb28181PlayResult:
    play_url: str
    session_id: str = ""


class Gb28181ProviderBase:
    def __init__(self, timeout_seconds: int = 8):
        """处理`init`。"""
        self.timeout_seconds = int(timeout_seconds or 8)
        if self.timeout_seconds < 1:
            self.timeout_seconds = 1
        if self.timeout_seconds > 60:
            self.timeout_seconds = 60

    def start_play(self, device_id: str, channel_id: str) -> Gb28181PlayResult:
        """启动播放。"""
        raise NotImplementedError

    def stop_play(self, device_id: str, channel_id: str) -> None:
        """停止播放。"""
        raise NotImplementedError

    def ptz_control(
        self,
        device_id: str,
        channel_id: str,
        action: str,
        *,
        speed: int = 32,
        preset_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """处理云台控制。"""
        raise NotImplementedError


class TemplateHttpProvider(Gb28181ProviderBase):
    """
    A generic "HTTP template" provider.
    Useful for WVP or custom/self-built platforms.
    """

    def __init__(
        self,
        base_url: str,
        start_play_url_template: str,
        stop_play_url_template: str,
        ptz_control_url_template: str = "",
        timeout_seconds: int = 8,
        template_values: Optional[Dict[str, Any]] = None,
    ):
        """处理`init`。"""
        super().__init__(timeout_seconds=timeout_seconds)
        self.base_url = str(base_url or "").strip()
        self.start_play_url_template = str(start_play_url_template or "").strip()
        self.stop_play_url_template = str(stop_play_url_template or "").strip()
        self.ptz_control_url_template = str(ptz_control_url_template or "").strip()
        self.template_values = dict(template_values or {})

    def start_play(self, device_id: str, channel_id: str) -> Gb28181PlayResult:
        """启动播放。"""
        url = _render_template(
            self.base_url,
            self.start_play_url_template,
            device_id,
            channel_id,
            **self.template_values,
        )
        if not url:
            raise ValueError("GB28181 provider start_play url is empty")

        res = requests.get(url, timeout=self.timeout_seconds)
        if res.status_code != 200:
            raise RuntimeError(f"GB28181 provider start_play http={res.status_code}")

        payload = _extract_payload_best_effort(res)

        play_url = _extract_play_url(payload)
        _validate_play_url(play_url)

        session_id = ""
        if isinstance(payload, dict):
            session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
            data = payload.get("data")
            if not session_id and isinstance(data, dict):
                session_id = str(data.get("session_id") or data.get("sessionId") or "").strip()

        return Gb28181PlayResult(play_url=play_url, session_id=session_id)

    def stop_play(self, device_id: str, channel_id: str) -> None:
        """停止播放。"""
        url = _render_template(
            self.base_url,
            self.stop_play_url_template,
            device_id,
            channel_id,
            **self.template_values,
        )
        if not url:
            raise ValueError("GB28181 provider stop_play url is empty")

        res = requests.get(url, timeout=self.timeout_seconds)
        if res.status_code != 200:
            raise RuntimeError(f"GB28181 provider stop_play http={res.status_code}")

    def ptz_control(
        self,
        device_id: str,
        channel_id: str,
        action: str,
        *,
        speed: int = 32,
        preset_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """处理云台控制。"""
        url = _render_template(
            self.base_url,
            self.ptz_control_url_template,
            device_id,
            channel_id,
            **self.template_values,
            action=action,
            speed=speed,
            presetIndex="" if preset_index is None else preset_index,
        )
        if not url:
            raise ValueError("GB28181 provider ptz_control url is empty")

        res = requests.get(url, timeout=self.timeout_seconds)
        if res.status_code != 200:
            raise RuntimeError(f"GB28181 provider ptz_control http={res.status_code}")

        payload = _extract_payload_best_effort(res)
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "payload": payload}


def _provider_template_values_from_config(config) -> Dict[str, Any]:
    """从配置获取提供方`template``values`。"""
    return {
        "transportMode": str(getattr(config, "gb28181TransportMode", "") or "").strip(),
        "startupPolicy": str(getattr(config, "gb28181StartupPolicy", "") or "").strip(),
        "requestParamPolicy": str(getattr(config, "gb28181RequestParamPolicy", "") or "").strip(),
        "requestParamAllowlist": str(getattr(config, "gb28181RequestParamAllowlist", "") or "").strip(),
        "requestParamBlocklist": str(getattr(config, "gb28181RequestParamBlocklist", "") or "").strip(),
    }


def get_gb28181_provider(config) -> Optional[Gb28181ProviderBase]:
    """获取`gb28181`提供方。"""
    provider = str(getattr(config, "gb28181Provider", "") or "").strip().lower()
    if not provider:
        provider = "wvp"

    timeout_seconds = int(getattr(config, "gb28181HttpTimeoutSeconds", 8) or 8)
    template_values = _provider_template_values_from_config(config)

    if provider == "wvp":
        return TemplateHttpProvider(
            base_url=str(getattr(config, "gb28181WvpBaseUrl", "") or "").strip(),
            start_play_url_template=str(getattr(config, "gb28181WvpStartPlayUrlTemplate", "") or "").strip(),
            stop_play_url_template=str(getattr(config, "gb28181WvpStopPlayUrlTemplate", "") or "").strip(),
            ptz_control_url_template=str(getattr(config, "gb28181WvpPtzControlUrlTemplate", "") or "").strip(),
            timeout_seconds=timeout_seconds,
            template_values=template_values,
        )
    if provider == "custom":
        return TemplateHttpProvider(
            base_url=str(getattr(config, "gb28181CustomBaseUrl", "") or "").strip(),
            start_play_url_template=str(getattr(config, "gb28181CustomStartPlayUrlTemplate", "") or "").strip(),
            stop_play_url_template=str(getattr(config, "gb28181CustomStopPlayUrlTemplate", "") or "").strip(),
            ptz_control_url_template=str(getattr(config, "gb28181CustomPtzControlUrlTemplate", "") or "").strip(),
            timeout_seconds=timeout_seconds,
            template_values=template_values,
        )

    logger.warning("Unknown BEACON_GB28181_PROVIDER=%s; GB28181 start/stop will fail", provider)
    return None

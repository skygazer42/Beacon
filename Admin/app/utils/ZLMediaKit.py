import logging
from urllib.parse import quote, urlsplit

import requests


logger = logging.getLogger(__name__)


_DISABLE_ENV_PROXY = {
    "http": "",
    "https": "",
    "all": "",
}

_API_NOT_FOUND_CODE = -500  # ZLMediaKit API::NotFound: stream is confirmed missing.

STREAM_PROXY_DELETE_REMOVED = "removed"
STREAM_PROXY_DELETE_CONFIRMED_ABSENT = "confirmed_absent"
STREAM_PROXY_DELETE_UNKNOWN = "unknown"


def _request_kwargs_without_env_proxy(kwargs):
    kwargs.setdefault("proxies", dict(_DISABLE_ENV_PROXY))
    return kwargs


def _requests_get(*args, **kwargs):
    return requests.get(*args, **_request_kwargs_without_env_proxy(kwargs))


def _requests_post(*args, **kwargs):
    return requests.post(*args, **_request_kwargs_without_env_proxy(kwargs))


_LEGACY_PUBLIC_NAMES = {
    "mediaServerState": "media_server_state",
    "get_hlsUrl": "get_hls_url",
    "get_hlsFmp4Url": "get_hls_fmp4_url",
    "get_httpFlvUrl": "get_http_flv_url",
    "get_rtspUrl": "get_rtsp_url",
    "get_wsHost": "get_ws_host",
    "get_wsMp4Url": "get_ws_mp4_url",
    "get_wsFlvUrl": "get_ws_flv_url",
    "get_httpMp4Url": "get_http_mp4_url",
    "get_rtmpUrl": "get_rtmp_url",
    "get_webrtcApiUrl": "get_webrtc_api_url",
    "get_webrtcDemoUrl": "get_webrtc_demo_url",
    "addFFmpegSource": "add_ffmpeg_source",
    "delFFmpegSource": "del_ffmpeg_source",
    "addStreamProxy": "add_stream_proxy",
    "delStreamProxy": "del_stream_proxy",
    "delStreamProxyStatus": "del_stream_proxy_status",
    "getMediaList": "get_media_list",
    "getMediaInfo": "get_media_info",
    "addStreamPusherProxy": "add_stream_pusher_proxy",
}


def _to_int(value, default: int = 0) -> int:
    """处理`to`整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _parse_audio_track(track: dict) -> dict:
    """解析音频`track`。"""
    return {
        "codec_id_name": str(track.get("codec_id_name", "") or "").lower(),
        "channels": _to_int(track.get("channels", 0) or 0, 0),
        "sample_rate": _to_int(track.get("sample_rate", 0) or 0, 0),
        "sample_bit": _to_int(track.get("sample_bit", 0) or 0, 0),
    }


def _fill_media_info_tracks(info: dict, tracks) -> None:
    """处理`fill`媒体信息`tracks`。"""
    if not isinstance(tracks, list):
        return
    for track in tracks:
        if not isinstance(track, dict):
            continue

        codec_type = _to_int(track.get("codec_type", -1), -1)
        if codec_type == 0:
            info["video_codec_name"] = str(track.get("codec_id_name", "") or "").lower()
            info["video_width"] = _to_int(track.get("width", 0) or 0, 0)
            info["video_height"] = _to_int(track.get("height", 0) or 0, 0)
            info["ret"] = True
        elif codec_type == 1:
            info["audio_tracks"].append(_parse_audio_track(track))


def _group_media_rows(media_rows) -> dict:
    """返回分组媒体记录。"""
    grouped_rows = {}
    for media_row in media_rows or []:
        app = media_row.get("app")
        name = media_row.get("stream")
        schema = media_row.get("schema")
        stream_key = f"{app}_{name}"
        grouped_rows.setdefault(stream_key, {})[schema] = media_row
    return grouped_rows


def _configured_scheme(url: str, default: str) -> str:
    """处理`configured``scheme`。"""
    try:
        scheme = urlsplit(str(url or "").strip()).scheme
    except Exception:
        scheme = ""
    return scheme or default


def _format_host_url(scheme: str, host: str, port) -> str:
    """返回`format`主机URL。"""
    return "{scheme}://{host}:{port}".format(scheme=scheme, host=host, port=port)


def _build_schema_clients(media_by_schema: dict):
    """构建`schema``clients`。"""
    schema_clients = []
    primary_row = None
    for schema, media_row in media_by_schema.items():
        schema_clients.append(
            {
                "schema": schema,
                "readerCount": media_row.get("readerCount"),
            }
        )
        if primary_row is None:
            primary_row = media_row
    return primary_row, schema_clients


def _summarize_tracks(tracks) -> dict:
    """处理`summarize``tracks`。"""
    track_summary = {
        "video": "无",
        "video_codec_name": None,
        "video_width": 0,
        "video_height": 0,
        "audio": "无",
    }
    if not isinstance(tracks, list):
        return track_summary

    for track in tracks:
        if not isinstance(track, dict):
            continue
        codec_id_name = str(track.get("codec_id_name", "") or "").lower()
        codec_type = _to_int(track.get("codec_type", -1), -1)
        if codec_type == 0:
            fps = _to_int(track.get("fps", 0) or 0, 0)
            track_summary["video_height"] = _to_int(track.get("height", 0) or 0, 0)
            track_summary["video_width"] = _to_int(track.get("width", 0) or 0, 0)
            track_summary["video_codec_name"] = codec_id_name
            track_summary["video"] = "%s/%d/%dx%d" % (
                codec_id_name,
                fps,
                track_summary["video_width"],
                track_summary["video_height"],
            )
        elif codec_type == 1:
            channels = _to_int(track.get("channels", 0) or 0, 0)
            sample_bit = _to_int(track.get("sample_bit", 0) or 0, 0)
            sample_rate = _to_int(track.get("sample_rate", 0) or 0, 0)
            track_summary["audio"] = "%s/%d/%d/%d" % (
                codec_id_name,
                channels,
                sample_rate,
                sample_bit,
            )
    return track_summary


class ZLMediaKit:
    def __init__(self, config):
        """处理`init`。"""
        self.__config = config
        self.default_stream_app = "live"
        self.default_push_stream_app = "analyzer"
        self.default_user_agent = "Admin"

        self.timeout = 15
        self.media_server_state = False

    def __getattr__(self, name):
        """处理`getattr`。"""
        target_name = _LEGACY_PUBLIC_NAMES.get(name)
        if target_name is None:
            raise AttributeError(f"{type(self).__name__!s} object has no attribute {name!r}")
        return object.__getattribute__(self, target_name)

    def __setattr__(self, name, value):
        """处理`setattr`。"""
        object.__setattr__(self, _LEGACY_PUBLIC_NAMES.get(name, name), value)

    def __delattr__(self, name):
        """处理`delattr`。"""
        object.__delattr__(self, _LEGACY_PUBLIC_NAMES.get(name, name))

    def _public_host(self, public_host: str) -> str:
        """处理公共主机。"""
        raw = str(public_host or "").strip()
        if not raw:
            return ""
        if raw.startswith("["):
            if "]" in raw:
                return raw.split("]")[0].lstrip("[")
            return raw.lstrip("[")
        if ":" in raw:
            return raw.split(":", 1)[0]
        return raw

    def _media_http_host(self, public_host: str = "") -> str:
        """处理媒体HTTP主机。"""
        host = self._public_host(public_host)
        if not host:
            return self.__config.mediaHttpHost
        scheme = _configured_scheme(self.__config.mediaHttpHost, "http")
        return _format_host_url(scheme, host, self.__config.mediaHttpPort)

    def _media_ws_host(self, public_host: str = "") -> str:
        """处理媒体WebSocket主机。"""
        host = self._public_host(public_host)
        if not host:
            return self.__config.mediaWsHost
        scheme = _configured_scheme(self.__config.mediaWsHost, "ws")
        return _format_host_url(scheme, host, self.__config.mediaHttpPort)

    def _media_rtsp_host(self, public_host: str = "") -> str:
        """处理媒体`rtsp`主机。"""
        host = self._public_host(public_host)
        if not host:
            return self.__config.mediaRtspHost
        scheme = _configured_scheme(self.__config.mediaRtspHost, "rtsp")
        return _format_host_url(scheme, host, self.__config.mediaRtspPort)

    def _byte_format(self, value, suffix="bps"):
        """处理`byte``format`。"""
        try:
            size = float(value or 0)
        except Exception:
            size = 0.0
        factor = 1024
        for unit in ["", "K", "M", "G", "T"]:
            if size < factor or unit == "T":
                return f"{size:.2f}{unit}{suffix}"
            size /= factor

    def get_hls_url(self, app, name, public_host: str = ""):
        """获取`hls`URL。"""
        return "%s/%s/%s/hls.m3u8" % (self._media_http_host(public_host), app, name)

    def get_hls_fmp4_url(self, app, name, public_host: str = ""):
        """获取`hls``fmp4`URL。"""
        return "%s/%s/%s/hls.fmp4.m3u8" % (self._media_http_host(public_host), app, name)

    def get_http_flv_url(self, app, name, public_host: str = ""):
        """获取HTTP`flv`URL。"""
        return "%s/%s/%s.live.flv" % (self._media_http_host(public_host), app, name)

    def get_rtsp_url(self, app, name, public_host: str = ""):
        """获取`rtsp`URL。"""
        return "%s/%s/%s" % (self._media_rtsp_host(public_host), app, name)

    def get_ws_host(self, public_host: str = ""):
        """获取WebSocket主机。"""
        return self._media_ws_host(public_host)

    def get_ws_mp4_url(self, app, name, public_host: str = ""):
        """获取WebSocket`mp4`URL。"""
        return "%s/%s/%s.live.mp4" % (self._media_ws_host(public_host), app, name)

    def get_ws_flv_url(self, app, name, public_host: str = ""):
        """获取WebSocket`flv`URL。"""
        return "%s/%s/%s.live.flv" % (self._media_ws_host(public_host), app, name)

    def get_http_mp4_url(self, app, name, public_host: str = ""):
        """获取HTTP`mp4`URL。"""
        return "%s/%s/%s.live.mp4" % (self._media_http_host(public_host), app, name)

    def get_rtmp_url(self, app, name):
        """获取`rtmp`URL。"""
        return "%s/%s/%s" % (self.__config.mediaRtmpHost, app, name)

    def get_webrtc_api_url(self, app, name, public_host: str = "", type: str = "play"):
        """获取`webrtc`APIURL。"""
        app_name = quote(str(app or ""), safe="")
        stream_name = quote(str(name or ""), safe="")
        play_type = quote(str(type or "play"), safe="")
        return "%s/index/api/webrtc?app=%s&stream=%s&type=%s" % (
            self._media_http_host(public_host),
            app_name,
            stream_name,
            play_type,
        )

    def get_webrtc_demo_url(self, app, name, public_host: str = "", type: str = "play"):
        """获取`webrtc``demo`URL。"""
        app_name = quote(str(app or ""), safe="")
        stream_name = quote(str(name or ""), safe="")
        play_type = quote(str(type or "play"), safe="")
        return "%s/webrtc/index.html?app=%s&stream=%s&type=%s" % (
            self._media_http_host(public_host),
            app_name,
            stream_name,
            play_type,
        )

    def add_ffmpeg_source(
        self,
        src_url,
        dst_url,
        ffmpeg_cmd_key="",
        timeout_ms=8000,
        enable_hls=0,
        enable_mp4=0,
    ):
        """处理新增`ffmpeg`来源。"""
        key = None
        try:
            url = "{host}/index/api/addFFmpegSource".format(host=self.__config.mediaHttpHost)
            params = {
                "secret": self.__config.mediaSecret,
                "src_url": src_url,
                "dst_url": dst_url,
                "timeout_ms": timeout_ms,
                "enable_hls": enable_hls,
                "enable_mp4": enable_mp4,
                "ffmpeg_cmd_key": ffmpeg_cmd_key,
            }
            response = _requests_post(
                url,
                headers={"User-Agent": self.default_user_agent},
                json=params,
                timeout=self.timeout,
            )
            if response.status_code == 200:
                response_json = response.json()
                if response_json.get("code") == 0:
                    key = response_json.get("data", {}).get("key")
            self.media_server_state = True
        except Exception as exc:
            self.media_server_state = False
            logger.warning("ZLMediaKit.add_ffmpeg_source() error: %s", exc)
        return key

    def del_ffmpeg_source(self, key):
        """处理`del``ffmpeg`来源。"""
        flag = False
        try:
            url = "{host}/index/api/delFFmpegSource?secret={secret}&key={key}".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret,
                key=key,
            )
            response = _requests_get(
                url,
                headers={"User-Agent": self.default_user_agent},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                response_json = response.json()
                if response_json.get("code") == 0:
                    flag = True if response_json.get("data", {}).get("flag") else False
            self.media_server_state = True
        except Exception as exc:
            self.media_server_state = False
            logger.warning("ZLMediaKit.del_ffmpeg_source() error: %s", exc)
        return flag

    def add_stream_proxy(self, app, name, origin_url, vhost="__defaultVhost__"):
        """处理新增流代理。"""
        key = None
        try:
            url = "{host}/index/api/addStreamProxy".format(host=self.__config.mediaHttpHost)
            params = {
                "secret": self.__config.mediaSecret,
                "vhost": vhost,
                "app": app,
                "stream": name,
                "url": origin_url,
                "rtp_type": 0,
                "enable_hls": 0,
                "enable_mp4": 0,
                "enable_rtmp": 0,
                "enable_ts": 0,
                "enable_audio": 0,
                "add_mute_audio": 0,
            }
            response = _requests_post(
                url,
                headers={"User-Agent": self.default_user_agent},
                json=params,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                response_json = response.json()
                if response_json.get("code") == 0:
                    key = response_json.get("data", {}).get("key")
            self.media_server_state = True
        except Exception as exc:
            self.media_server_state = False
            logger.warning("ZLMediaKit.add_stream_proxy() error: %s", exc)
        return key

    def del_stream_proxy_status(self, app, name, vhost="__defaultVhost__"):
        """Return whether a proxy was removed, confirmed absent, or is unknown."""
        key = "{vhost}/{app}/{name}".format(vhost=vhost, app=app, name=name)
        try:
            url = "{host}/index/api/delStreamProxy?secret={secret}&key={key}".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret,
                key=key,
            )
            response = _requests_get(
                url,
                headers={"User-Agent": self.default_user_agent},
                timeout=self.timeout,
            )
            self.media_server_state = True

            if response.status_code != 200:
                return STREAM_PROXY_DELETE_UNKNOWN, "ZLM 删除代理请求未确认"

            response_json = response.json()
            if not isinstance(response_json, dict) or type(response_json.get("code")) is not int:
                return STREAM_PROXY_DELETE_UNKNOWN, "ZLM 删除代理响应格式错误"
            if response_json["code"] != 0:
                return STREAM_PROXY_DELETE_UNKNOWN, "ZLM 删除代理响应失败"

            data = response_json.get("data")
            if not isinstance(data, dict) or type(data.get("flag")) is not bool:
                return STREAM_PROXY_DELETE_UNKNOWN, "ZLM 删除代理响应格式错误"
            if data["flag"]:
                return STREAM_PROXY_DELETE_REMOVED, "ZLM 代理已删除"
            return STREAM_PROXY_DELETE_CONFIRMED_ABSENT, "ZLM 代理已确认不存在"
        except Exception as exc:
            self.media_server_state = False
            logger.warning(
                "ZLMediaKit.del_stream_proxy_status() failed: exception_type=%s",
                type(exc).__name__,
            )
            return STREAM_PROXY_DELETE_UNKNOWN, "ZLM 删除代理调用异常"

    def del_stream_proxy(self, app, name, vhost="__defaultVhost__"):
        """Preserve the legacy bool contract: only an actual removal is true."""
        status, _message = self.del_stream_proxy_status(app, name, vhost=vhost)
        return status == STREAM_PROXY_DELETE_REMOVED

    def _build_media_list_row(self, stream_key: str, media_by_schema: dict):
        """构建媒体列表记录。"""
        primary_row, schema_clients = _build_schema_clients(media_by_schema)
        if not primary_row:
            return None

        track_summary = _summarize_tracks(primary_row.get("tracks"))
        app = primary_row.get("app")
        name = primary_row.get("stream")

        return {
            "is_online": 1,
            "code": stream_key,
            "an": stream_key,
            "app": app,
            "name": name,
            "produce_speed": self._byte_format(primary_row.get("bytesSpeed")),
            "video": track_summary["video"],
            "video_codec_name": track_summary["video_codec_name"],
            "video_width": track_summary["video_width"],
            "video_height": track_summary["video_height"],
            "audio": track_summary["audio"],
            "originUrl": primary_row.get("originUrl"),
            "originType": primary_row.get("originType"),
            "originTypeStr": primary_row.get("originTypeStr"),
            "clients": primary_row.get("totalReaderCount"),
            "schema_clients": schema_clients,
            "videoUrl": self.get_ws_mp4_url(app, name),
            "wsHost": self.get_ws_host(),
            "wsMp4Url": self.get_ws_mp4_url(app, name),
        }

    def get_media_list(self):
        """获取媒体列表。"""
        media_list = []
        try:
            url = "{host}/index/api/getMediaList?secret={secret}".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret,
            )
            response = _requests_get(
                url,
                headers={"User-Agent": self.default_user_agent},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                response_json = response.json()
                if response_json.get("code") == 0:
                    grouped_rows = _group_media_rows(response_json.get("data"))
                    for stream_key, media_by_schema in grouped_rows.items():
                        media_row = self._build_media_list_row(stream_key, media_by_schema)
                        if media_row:
                            media_list.append(media_row)

            self.media_server_state = True
        except Exception as exc:
            self.media_server_state = False
            logger.warning("ZLMediaKit.get_media_list() error: %s", exc)

        return media_list

    def get_media_info(self, app, name, schema="rtsp", vhost="__defaultVhost__"):
        """获取媒体信息。"""
        info = {
            "ret": False,
            "probe_ok": False,
            "audio_tracks": [],
        }

        try:
            url = "{host}/index/api/getMediaInfo?secret={secret}&schema={schema}&vhost={vhost}&app={app}&stream={name}".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret,
                schema=schema,
                vhost=vhost,
                app=app,
                name=name,
            )

            response = _requests_get(
                url,
                headers={"User-Agent": self.default_user_agent},
                timeout=self.timeout,
            )

            if response.status_code != 200:
                logger.warning("ZLMediaKit.get_media_info() error: status=%d", response.status_code)
                self.media_server_state = True
                return info

            response_json = response.json()
            response_code = _to_int(response_json.get("code", -1), -1)
            if response_code in (0, _API_NOT_FOUND_CODE):
                info["probe_ok"] = True
            if response_code == 0:
                _fill_media_info_tracks(info, response_json.get("tracks"))

            self.media_server_state = True
        except Exception as exc:
            self.media_server_state = False
            logger.warning("ZLMediaKit.get_media_info() error: %s", exc)

        return info

    def add_stream_pusher_proxy(
        self,
        app,
        name,
        schema="rtsp",
        vhost="__defaultVhost__",
        dst_url=None,
        retry_count=60,
        timeout_sec=10,
    ):
        """处理新增流`pusher`代理。"""
        key = None
        message = "开启转推失败|dst_url=%s" % dst_url

        try:
            url = "{host}/index/api/addStreamPusherProxy".format(host=self.__config.mediaHttpHost)
            params = {
                "secret": self.__config.mediaSecret,
                "vhost": vhost,
                "app": app,
                "stream": name,
                "schema": schema,
                "dst_url": dst_url,
                "timeout_sec": timeout_sec,
            }
            if schema == "rtsp":
                params["rtp_type"] = 0
            if retry_count > 0:
                params["retry_count"] = retry_count

            response = _requests_post(
                url,
                headers={"User-Agent": self.default_user_agent},
                json=params,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                response_json = response.json()
                if response_json.get("code") == 0:
                    key = response_json.get("data", {}).get("key")
                    message = "success"
                else:
                    message += "|" + str(response_json.get("msg"))
            else:
                raise RuntimeError("status=%d" % response.status_code)
            self.media_server_state = True

        except Exception as exc:
            self.media_server_state = False
            message += "|" + str(exc)

        return key, message

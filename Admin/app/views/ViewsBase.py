import json
import os
import base64
import logging
from urllib.parse import urlsplit
from app.utils.ZLMediaKit import (
    STREAM_PROXY_DELETE_CONFIRMED_ABSENT,
    STREAM_PROXY_DELETE_REMOVED,
    ZLMediaKit,
)
from app.utils.Analyzer import Analyzer
from app.utils.License import License
from app.utils.DjangoSql import DjangoSql
from app.utils.Config import Config
from app.utils.Gb28181Providers import get_gb28181_provider, parse_gb28181_url
from app.utils.SafeLog import truncate_text
from app.models import Stream
from django.http import HttpResponse


logger = logging.getLogger(__name__)


g_config = Config()
g_zlm = ZLMediaKit(config=g_config)
g_analyzer = Analyzer(g_config.analyzerHost, openApiToken=getattr(g_config, "openApiToken", ""))
g_license = License(g_config)
g_djangoSql = DjangoSql()
g_gb28181_provider = get_gb28181_provider(g_config)
g_session_key_user = "user"
g_pull_stream_types = [
    {
        "id": 1,
        "name": "RTSP"
    },
    {
        "id": 2,
        "name": "RTMP"
    },
    {
        "id": 3,
        "name": "FLV"
    },
    {
        "id": 4,
        "name": "HLS"
    },
    {
        "id": 5,
        "name": "SRT"
    },
    {
        "id": 21,
        "name": "GB28181"
    },
    {
        "id": 31,
        "name": "cRTSP"
    },
    {
        "id": 32,
        "name": "cRTMP"
    }
]
g_audio_types = [
    {
        "type": 0,
        "name": "静音",
    },
    {
        "type": 1,
        "name": "原始音频",
    }
]

def get_user(request):
    """获取用户。"""
    user = request.session.get(g_session_key_user)
    return user
getUser = get_user  # pragma: no cover - compatibility alias

def _get_request_hostname(request) -> str:
    """获取请求`hostname`。
    
    Best-effort extract hostname from the current request.
    
        - Supports "host:port" and IPv6 "[::1]:port" formats.
        - Does not raise.
    """
    try:
        host = str(request.get_host() or "").strip()
        if not host:
            return ""
        return str(urlsplit("//" + host).hostname or "")
    except Exception:
        return ""


def get_public_host_for_urls(request) -> str:
    """
    工业场景：当 config.host=0.0.0.0（绑定全部网卡）时，对外 URL 不能使用 0.0.0.0。
    这里优先使用当前 request 的 hostname 作为“对外访问 host”。
    """
    configured = str(getattr(g_config, "host", "") or "").strip()
    if configured in ("0.0.0.0", "::"):
        h = _get_request_hostname(request)
        if h:
            return h
        # fallback for cases without Host header
        return "127.0.0.1"
    return configured or "127.0.0.1"


def get_stream(app, name, public_host: str = ""):
    """处理`Get`流。"""
    media_info = g_zlm.getMediaInfo(app=app, name=name)
    is_online = 0
    video_codec_name = ""
    video_width = 0
    video_height = 0
    audio_tracks = media_info.get("audio_tracks") or []
    if not isinstance(audio_tracks, list):
        audio_tracks = []
    if media_info.get("ret"):
        is_online = 1
        video_codec_name = media_info.get("video_codec_name")  # 视频编码格式
        video_width = media_info.get("video_width")
        video_height = media_info.get("video_height")

    stream = {
        "is_online": is_online,
        # "code": code,
        "app": app,
        "name": name,
        # "produce_speed": produce_speed,
        # "video": video_str,
        "video_codec_name": video_codec_name,
        "video_width": video_width,
        "video_height": video_height,
        # v4.744: surface audio track meta for the player UI (codec/channels/sample_rate, etc).
        "audio_tracks": audio_tracks,
        # "audio": audio_str,
        # "originUrl": d.get("originUrl"),  # 推流地址
        # "originType": d.get("originType"),  # 推流地址采用的推流协议类型
        # "originTypeStr": d.get("originTypeStr"),  # 推流地址采用的推流协议类型（字符串）
        # "clients": d.get("totalReaderCount"),  # 客户端总数量
        # "schemas_clients": schemas_clients,
        # "videoUrl": g_zlm.get_wsMp4Url(app, name),
        "wsHost": g_zlm.get_wsHost(public_host),
        "wsMp4Url": g_zlm.get_wsMp4Url(app, name, public_host),
        "wsFlvUrl": g_zlm.get_wsFlvUrl(app, name, public_host),
        "httpMp4Url": g_zlm.get_httpMp4Url(app, name, public_host),
        "httpFlvUrl": g_zlm.get_httpFlvUrl(app, name, public_host),
        "rtspUrl": g_zlm.get_rtspUrl(app, name, public_host),
        "hlsUrl": g_zlm.get_hlsUrl(app, name, public_host),
        "hlsFmp4Url": g_zlm.get_hlsFmp4Url(app, name, public_host),
        # WebRTC playback (signaling API + demo page) for low-latency preview.
        "webrtcApiUrl": g_zlm.get_webrtcApiUrl(app, name, public_host, type="play"),
        "webrtcUrl": g_zlm.get_webrtcDemoUrl(app, name, public_host, type="play"),
    }
    return stream
GetStream = get_stream  # pragma: no cover - compatibility alias

def read_all_stream_data():
    """读取全部流数据。"""
    data = g_djangoSql.select("select * from av_stream order by id desc")
    return data
readAllStreamData = read_all_stream_data  # pragma: no cover - compatibility alias


def start_forward_for_stream(stream: Stream):
    """启动转发`for`流。
    
    Start local ZLM forwarding for a Stream row.
        For GB28181 streams, this will:
          gb28181://device@channel -> provider.start_play() -> play_url -> local addStreamProxy(play_url)
        Returns: (ok: bool, msg: str)
    """
    try:
        if int(stream.forward_state or 0) == 1:
            return True, "已在转发中"

        origin_url = str(stream.pull_stream_url or "").strip()

        if int(stream.pull_stream_type or 0) == 21:
            device_id, channel_id = parse_gb28181_url(origin_url)
            if not device_id or not channel_id:
                return False, "GB28181 参数错误：pull_stream_url 格式应为 gb28181://{deviceId}@{channelId}"

            if not g_gb28181_provider:
                return False, "GB28181 provider 未配置（请设置 BEACON_GB28181_* 环境变量）"

            play = g_gb28181_provider.start_play(device_id, channel_id)
            origin_url = str(getattr(play, "play_url", "") or "").strip()
            if not origin_url:
                return False, "GB28181 provider 返回的 play_url 为空"

        key = g_zlm.addStreamProxy(app=stream.app, name=stream.name, origin_url=origin_url)
        if key:
            stream.forward_state = 1
            stream.save()
            return True, "开启转发成功"
        return False, "开启转发失败"
    except Exception as e:
        return False, str(e)


def stop_forward_for_stream(stream: Stream):
    """停止转发`for`流。
    
    Stop local ZLM forwarding for a Stream row.
        Stop order (industrial best-effort):
          1) del local proxy
          2) provider.stop_play (GB28181 only; best-effort)
        Returns: (ok: bool, msg: str)
    """
    try:
        if int(stream.forward_state or 0) == 0:
            return True, "已停止转发"

        delete_result = g_zlm.del_stream_proxy_status(app=stream.app, name=stream.name)
        if type(delete_result) is not tuple or len(delete_result) != 2:
            return False, "停止转发响应格式错误"
        delete_status, delete_message = delete_result
        if not isinstance(delete_status, str) or not isinstance(delete_message, str):
            return False, "停止转发响应字段错误"
        if delete_status not in {
            STREAM_PROXY_DELETE_REMOVED,
            STREAM_PROXY_DELETE_CONFIRMED_ABSENT,
        }:
            return False, "停止转发未确认"

        previous_forward_state = stream.forward_state
        stream.forward_state = 0
        try:
            stream.save()
        except Exception:
            stream.forward_state = previous_forward_state
            raise

        if int(stream.pull_stream_type or 0) == 21:
            origin_url = str(stream.pull_stream_url or "").strip()
            device_id, channel_id = parse_gb28181_url(origin_url)
            if device_id and channel_id and g_gb28181_provider:
                try:
                    g_gb28181_provider.stop_play(device_id, channel_id)
                except Exception:
                    # best-effort: do not fail user stop when provider is down
                    logger.debug("suppressed exception in app/views/ViewsBase.py:227", exc_info=True)

        if delete_status == STREAM_PROXY_DELETE_REMOVED:
            return True, "停止转发成功"
        return True, "已停止转发"
    except Exception as e:
        return False, str(e)


def all_stream_start_forward():
    """处理全部流起始转发。"""
    try:
        media_server_state = bool(getattr(g_zlm, "mediaServerState", False))
        if not media_server_state:
            g_djangoSql.execute("UPDATE av_stream SET forward_state=0")
            return False, "流媒体服务不在线，无法开启转发！"

        online_dict = {}
        for d in g_zlm.getMediaList() or []:
            try:
                app_name = "{app}_{name}".format(app=d["app"], name=d["name"])
            except Exception:
                continue
            online_dict[app_name] = d

        success_count = 0
        error_count = 0
        for stream in Stream.objects.all():
            stream_app_name = "{app}_{name}".format(app=stream.app, name=stream.name)
            if stream_app_name in online_dict:  # 当前流已经在线，不用再次请求转发
                success_count += 1
                continue

            ok, _ = start_forward_for_stream(stream)
            if ok:
                success_count += 1
            else:
                error_count += 1

        msg = "转发成功%d条,转发失败%d条" % (success_count, error_count)
        return bool(success_count > 0), msg
    except Exception as e:
        return False, "开启转发失败：" + str(e)
AllStreamStartForward = all_stream_start_forward  # pragma: no cover - compatibility alias

def f_parse_get_params(request):
    """处理`f``parse``Get`参数。"""
    params = {}
    for k in request.GET:
        params.__setitem__(k, request.GET.get(k))

    return params
f_parseGetParams = f_parse_get_params  # pragma: no cover - compatibility alias


def f_parse_post_params(request):
    """处理`f``parse``Post`参数。"""
    params = {}
    for k in request.POST:
        params.__setitem__(k, request.POST.get(k))

    # 接收json方式上传的参数
    if not params:
        try:
            params = json.loads(request.body.decode('utf-8')) if request.body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            params = {}
        if not isinstance(params, dict):
            params = {}

    return params
f_parsePostParams = f_parse_post_params  # pragma: no cover - compatibility alias


def f_response_json(res):
    """处理`f`响应JSON。"""
    def json_dumps_default(obj):
        """处理JSON`dumps`默认。"""
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        else:
            raise TypeError

    return HttpResponse(json.dumps(res, default=json_dumps_default), content_type="application/json")
f_responseJson = f_response_json  # pragma: no cover - compatibility alias

def f_remove_alarm_and_storage(alarm_id):
    """Thin compatibility wrapper for the shared strict alarm cleaner."""
    from app.utils.AlarmDataCleaner import remove_alarm_data

    removed, _removed_bytes = remove_alarm_data(g_config, alarm_id)
    return removed
f_removeAlarmAndStorage = f_remove_alarm_and_storage  # pragma: no cover - compatibility alias

def f_calcu_file_base64_str(filepath):
    """处理`f`计算文件Base64字符串。"""
    base64_str = "encode error"
    try:
        if not os.path.exists(filepath):
            raise FileNotFoundError("filepath not found")
        with open(filepath, 'rb') as f:
            f_byte = f.read()
        base64_str = base64.b64encode(f_byte)
        base64_str = base64_str.decode("utf-8")  # str类型
    except Exception as e:
        logger.warning(
            "f_calcuFileBase64Str error filepath=%s err=%s",
            truncate_text(str(filepath), max_len=256),
            e,
        )
    return base64_str
f_calcuFileBase64Str = f_calcu_file_base64_str  # pragma: no cover - compatibility alias

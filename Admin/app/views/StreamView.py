# ruff: noqa: F403, F405
# This module historically relies on a large set of globals/helpers from ViewsBase.
from app.views.ViewsBase import *  # NOSONAR
# Admin models are used extensively throughout this file; keep the star import for now.
from app.models import *  # NOSONAR
from django.shortcuts import render, redirect
from app.utils.Utils import buildPageLabels, gen_random_code_s
from app.utils.TalkbackRelay import TalkbackRelayManager
from app.utils.ONVIF import ONVIFClient
import re
import urllib.parse
import logging
import json
from datetime import datetime
from django.db.models import Q

from app.utils.SafeLog import safe_json_dumps
from app.utils.BackgroundServices import get_transcode_manager


logger = logging.getLogger(__name__)
_talkback_relay_manager = TalkbackRelayManager()

MSG_INVALID_PARAMS_CN = "请求参数格式错误"
MSG_METHOD_NOT_SUPPORTED_CN = "请求方法不支持"
MSG_STREAM_CODE_EMPTY_CN = "stream_code 不能为空"
MSG_SESSION_ID_EMPTY_CN = "session_id 不能为空"
MSG_STREAM_NOT_FOUND_CN = "视频流不存在"
MSG_STREAM_NOT_EXIST_CN = "该视频流不存在"

URL_STREAM_INDEX = "/stream/index"
SQL_SELECT_ALL_STREAMS_DESC = "select * from av_stream order by id desc"
STREAM_KEY_FMT = "{app}_{name}"
STREAM_PATH_FMT = "{app}/{name}"

SUPPORTED_PULL_STREAM_PREFIXES = (
    "rtsp://",
    "rtsps://",
    "rtmp://",
    "rtmps://",
    "http://",
    "https://",
    "srt://",
)

GB28181_PTZ_ACTIONS = {
    "up",
    "down",
    "left",
    "right",
    "left_up",
    "right_up",
    "left_down",
    "right_down",
    "zoom_in",
    "zoom_out",
    "stop",
    "preset_call",
    "preset_set",
    "preset_delete",
}

def sanitize_stream_field(value, field_name="field"):
    """
    清理和验证视频流字段，支持特殊字符但过滤危险字符。

    允许：字母、数字、中文、常见符号（-_@.#）。

    对于 `app` / `name` / `code` 字段：
    - 仅允许字母、数字、中文、下划线、横杠
    - 其他字符会被替换为 "_"
    """
    if not value:
        return value

    # 去除首尾空格
    value = value.strip()

    if field_name in ['app', 'name', 'code']:
        safe_pattern = re.compile(r'[^\w\u4e00-\u9fff\-]', re.UNICODE)
        cleaned = safe_pattern.sub('_', value)
        return cleaned

    return value


def is_supported_pull_stream_url(value):
    """判断`supported``pull`流URL。"""
    url = str(value or "").strip().lower()
    return bool(url) and url.startswith(SUPPORTED_PULL_STREAM_PREFIXES)


def _get_talkback_relay_manager():
    """获取对讲`relay``manager`。"""
    return _talkback_relay_manager


def _talkback_bool(value, default: bool = False) -> bool:
    """处理对讲布尔值。"""
    if value is None:
        return bool(default)
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _talkback_int(value, default: int, min_value: int, max_value: int) -> int:
    """处理对讲整数值。"""
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    if parsed < min_value:
        return int(min_value)
    if parsed > max_value:
        return int(max_value)
    return int(parsed)


def _serialize_talkback_config(obj) -> dict:
    """返回`serialize`对讲配置。"""
    return {
        "stream_code": str(getattr(obj, "stream_code", "") or "").strip(),
        "enabled": bool(getattr(obj, "enabled", False)),
        "transport_mode": str(getattr(obj, "transport_mode", "webrtc_to_rtsp") or "webrtc_to_rtsp").strip(),
        "onvif_service_url": str(getattr(obj, "onvif_service_url", "") or "").strip(),
        "onvif_username": str(getattr(obj, "onvif_username", "") or "").strip(),
        "onvif_password_set": bool(str(getattr(obj, "onvif_password", "") or "").strip()),
        "profile_token": str(getattr(obj, "profile_token", "") or "").strip(),
        "backchannel_uri": str(getattr(obj, "backchannel_uri", "") or "").strip(),
        "relay_app": str(getattr(obj, "relay_app", "talkback") or "talkback").strip(),
        "relay_stream_prefix": str(getattr(obj, "relay_stream_prefix", "") or "").strip(),
        "sample_rate": int(getattr(obj, "sample_rate", 16000) or 16000),
        "codec_hint": str(getattr(obj, "codec_hint", "pcma") or "pcma").strip(),
        "remark": str(getattr(obj, "remark", "") or "").strip(),
    }


def _build_default_talkback_config(stream_code: str):
    """构建默认对讲配置。"""
    return StreamTalkbackConfig(
        stream_code=stream_code,
        enabled=False,
        transport_mode="webrtc_to_rtsp",
        relay_app="talkback",
        relay_stream_prefix="",
        sample_rate=16000,
        codec_hint="pcma",
    )


def _build_talkback_stream_name(cfg, session_id: str) -> str:
    """构建对讲流名称。"""
    prefix = str(getattr(cfg, "relay_stream_prefix", "") or "").strip() or str(getattr(cfg, "stream_code", "") or "").strip()
    raw_name = f"{prefix}-{session_id}" if prefix else str(session_id or "").strip()
    return sanitize_stream_field(raw_name, "name")


def _resolve_talkback_backchannel_uri(cfg) -> str:
    """解析并返回对讲`backchannel``uri`。"""
    manual = str(getattr(cfg, "backchannel_uri", "") or "").strip()
    if manual:
        return manual

    service_url = str(getattr(cfg, "onvif_service_url", "") or "").strip()
    if not service_url:
        return ""

    parsed = urllib.parse.urlsplit(service_url)
    host = str(parsed.hostname or "").strip()
    if not host:
        return ""

    port = int(parsed.port or (443 if str(parsed.scheme or "").lower() == "https" else 80))
    client = ONVIFClient(
        host,
        port,
        str(getattr(cfg, "onvif_username", "") or "").strip(),
        str(getattr(cfg, "onvif_password", "") or "").strip(),
    )
    client.device_service_url = service_url
    uri = client.get_backchannel_uri(profile_token=str(getattr(cfg, "profile_token", "") or "").strip())
    return str(uri or "").strip()


def _empty_talkback_player_context(reason: str = "") -> dict:
    """处理空对讲播放器`context`。"""
    return {
        "available": False,
        "stream_code": "",
        "session_id": "",
        "relay_app": "",
        "relay_stream_name": "",
        "push_webrtc_api_url": "",
        "push_webrtc_demo_url": "",
        "push_rtsp_url": "",
        "config_enabled": False,
        "transport_mode": "webrtc_to_rtsp",
        "sample_rate": 16000,
        "codec_hint": "pcma",
        "destination_hint": "",
        "reason": str(reason or "").strip() or "当前播放流未关联 Beacon 视频流编号，无法启用 talkback。",
    }


def _find_stream_row_by_media(app: str, name: str):
    """查找流记录`by`媒体。"""
    return Stream.objects.filter(app=app, name=name).order_by("-id").first()


def _resolve_talkback_config_for_stream(stream_code: str):
    """解析并返回对讲配置`for`流。"""
    cfg = StreamTalkbackConfig.objects.filter(stream_code=stream_code).first()
    return cfg or _build_default_talkback_config(stream_code)


def _talkback_context(stream_row, cfg, *, session_id: str, public_host: str) -> dict:
    """处理对讲`context`。"""
    relay_app = str(getattr(cfg, "relay_app", "talkback") or "talkback").strip() or "talkback"
    relay_stream_name = _build_talkback_stream_name(cfg, session_id)
    destination_hint = str(getattr(cfg, "backchannel_uri", "") or "").strip() or str(getattr(cfg, "onvif_service_url", "") or "").strip()

    return {
        "available": True,
        "stream_code": str(stream_row.code or "").strip(),
        "session_id": session_id,
        "relay_app": relay_app,
        "relay_stream_name": relay_stream_name,
        "push_webrtc_api_url": g_zlm.get_webrtcApiUrl(relay_app, relay_stream_name, public_host, type="push"),
        "push_webrtc_demo_url": g_zlm.get_webrtcDemoUrl(relay_app, relay_stream_name, public_host, type="push"),
        "push_rtsp_url": g_zlm.get_rtspUrl(relay_app, relay_stream_name, public_host),
        "config_enabled": bool(getattr(cfg, "enabled", False)),
        "transport_mode": str(getattr(cfg, "transport_mode", "webrtc_to_rtsp") or "webrtc_to_rtsp").strip(),
        "sample_rate": int(getattr(cfg, "sample_rate", 16000) or 16000),
        "codec_hint": str(getattr(cfg, "codec_hint", "pcma") or "pcma").strip() or "pcma",
        "destination_hint": destination_hint,
        "reason": "",
    }


def _build_talkback_player_context(app: str, name: str, public_host: str = "") -> dict:
    """构建对讲播放器`context`。"""
    app = str(app or "").strip()
    name = str(name or "").strip()
    if not app or not name:
        return _empty_talkback_player_context("请先选择一个有效的视频流。")

    stream_row = _find_stream_row_by_media(app, name)
    if not stream_row:
        return _empty_talkback_player_context("当前播放流未关联 Beacon 视频流编号，无法启用 talkback。")

    session_id = sanitize_stream_field(f"tb-{gen_random_code_s(12)}", "name")
    cfg = _resolve_talkback_config_for_stream(stream_row.code)
    return _talkback_context(stream_row, cfg, session_id=session_id, public_host=public_host)

def _build_stream_index_choices():
    """构建流索引`choices`。"""
    try:
        app_choices = list(Stream.objects.values_list("app", flat=True).distinct().order_by("app"))
    except Exception:
        app_choices = []
    try:
        site_values = Stream.objects.values_list("site_label", flat=True).distinct().order_by("site_label")
        site_choices = [item for item in site_values if str(item or "").strip()]
    except Exception:
        site_choices = []
    return app_choices, site_choices


def _parse_stream_index_pagination(params):
    """解析流索引`pagination`。"""
    try:
        page = int(params.get("p", 1))
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1

    try:
        page_size = int(params.get("ps", 10))
    except (TypeError, ValueError):
        page_size = 10
    if page_size < 1:
        page_size = 10
    if page_size > 50:
        page_size = 50

    return page, page_size


def _apply_stream_index_filters(queryset, *, filter_app: str, filter_site: str, q: str):
    """处理应用流索引`filters`。"""
    qs = queryset
    if filter_app and filter_app.lower() not in ("all", "*"):
        qs = qs.filter(app=filter_app)
    if filter_site and filter_site.lower() not in ("all", "*"):
        qs = qs.filter(site_label=filter_site)
    if q:
        qs = qs.filter(
            Q(code__icontains=q)
            | Q(app__icontains=q)
            | Q(name__icontains=q)
            | Q(nickname__icontains=q)
            | Q(remark__icontains=q)
            | Q(site_label__icontains=q)
            | Q(floor_label__icontains=q)
            | Q(pull_stream_url__icontains=q)
        )
    return qs


def _paginate_stream_index(queryset, *, page: int, page_size: int):
    """执行分页流索引。"""
    from django.core.paginator import InvalidPage, Paginator

    paginator = Paginator(queryset, page_size)
    try:
        current_page = paginator.page(page)
    except InvalidPage:
        page = paginator.num_pages
        current_page = paginator.page(page)
    return current_page, paginator, page


def index(request):
    """渲染默认页面。"""
    params = f_parseGetParams(request)

    filter_app = str(params.get("app", "") or "").strip()
    filter_site = str(params.get("site", "") or "").strip()
    q = str(params.get("q", "") or "").strip()
    app_choices, site_choices = _build_stream_index_choices()
    page, page_size = _parse_stream_index_pagination(params)

    queryset = _apply_stream_index_filters(
        Stream.objects.all().order_by("-id"),
        filter_app=filter_app,
        filter_site=filter_site,
        q=q,
    )
    current_page, paginator, page = _paginate_stream_index(queryset, page=page, page_size=page_size)
    page_labels = buildPageLabels(page=page, page_num=paginator.num_pages)

    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": page_labels
    }

    context = {
        "data": current_page.object_list,
        "pageData": page_data,
        "filter_app": filter_app,
        "filter_site": filter_site,
        "filter_q": q,
        "app_choices": app_choices,
        "site_choices": site_choices,
        "pull_stream_types": g_pull_stream_types,
    }
    return render(request, 'app/stream/web_stream_index.html', context)


def api_open_index(request):

    """处理 `openIndex` 接口请求。"""
    params = f_parseGetParams(request)
    data = []

    page = params.get('p', 1)
    page_size = params.get('ps', 10)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(page_size)
        if page_size > 20 or page_size < 10:
            page_size = 10
    except (TypeError, ValueError):
        page_size = 10

    skip = (page - 1) * page_size
    sql_data = "select * from av_stream order by id desc limit %d,%d " % (
        skip, page_size)
    sql_data_num = "select count(id) as count from av_stream "

    count = g_djangoSql.select(sql_data_num)

    if len(count) > 0:
        count = int(count[0]["count"])

        __data = g_djangoSql.select(sql_data)
        for d in __data:
            d["camera_device_id"] = d["nickname"]
            d["pull_stream_type"] = 1
            d["pull_stream_ip"] = ""
            d["is_audio"] = 0
            d["last_update_time"] = d["last_update_time"].strftime("%Y/%m/%d %H:%M:%S")
            data.append([d])
    else:
        count = 0

    page_num = int(count / page_size)  # 总页数
    if count % page_size > 0:
        page_num += 1
    page_labels = buildPageLabels(page=page, page_num=page_num)
    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": page_num,
        "count": count,
        "pageLabels": page_labels
    }

    res = {
        "code": 1000,
        "msg": "success",
        "data": data,
        "pageData": page_data,
        "extra": {
            "audioTypes": g_audio_types,
            "pullStreamTypes": g_pull_stream_types
        }
    }
    return f_responseJson(res)
api_openIndex = api_open_index  # pragma: no cover - compatibility alias


def _stream_add_int(value, default: int) -> int:
    """处理流新增整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _stream_add_normalize_pull_url(pull_stream_type: int, pull_stream_url: str, gb28181_device_id: str, gb28181_channel_id: str):
    """返回流新增归一化`pull`URL。"""
    pull_stream_type = int(pull_stream_type or 1)
    raw_url = str(pull_stream_url or "").strip()

    if pull_stream_type == 21:  # GB28181
        if not (gb28181_device_id and gb28181_channel_id):
            return False, raw_url
        return True, f"gb28181://{gb28181_device_id}@{gb28181_channel_id}"

    return bool(is_supported_pull_stream_url(raw_url.lower())), raw_url


def _stream_add_parse_form(params: dict) -> dict:
    """处理流新增`parse`表单。"""
    pull_stream_type = _stream_add_int(params.get("pull_stream_type", 1), 1)
    gb28181_device_id = str(params.get("gb28181_device_id", "") or "").strip()
    gb28181_channel_id = str(params.get("gb28181_channel_id", "") or "").strip()
    url_valid, normalized_url = _stream_add_normalize_pull_url(
        pull_stream_type,
        params.get("pull_stream_url", ""),
        gb28181_device_id,
        gb28181_channel_id,
    )

    return {
        "handle": params.get("handle"),
        "code": str(params.get("code") or "").strip(),
        "app": str(params.get("app") or "").strip(),
        "pull_stream_url": str(normalized_url or "").strip(),
        "pull_stream_type": int(pull_stream_type),
        "nickname": str(params.get("nickname") or "").strip(),
        "remark": str(params.get("remark", "") or "").strip(),
        "site_label": str(params.get("site_label") or "").strip(),
        "floor_label": str(params.get("floor_label") or "").strip(),
        "url_valid": bool(url_valid),
    }


def _stream_add_request_user_id(request) -> int:
    """返回流新增请求用户ID。"""
    try:
        user_id = getUser(request).get("id")
    except AttributeError:
        user_id = 0
    return int(user_id or 0)


def _stream_add_sanitize_identifiers(code: str, app: str):
    """处理流新增`sanitize``identifiers`。"""
    safe_code = sanitize_stream_field(str(code or "").strip(), "code")
    safe_app = sanitize_stream_field(str(app or "").strip(), "app") or "live"
    safe_name = safe_code
    return safe_code, safe_app, safe_name


def _stream_add_try_create_stream(request, form: dict):
    """处理流新增`try``create`流。"""
    if not (str(form.get("handle") or "").strip() == "add" and form.get("code") and form.get("nickname") and form.get("url_valid")):
        return False, MSG_INVALID_PARAMS_CN

    user_id = _stream_add_request_user_id(request)
    safe_code, safe_app, safe_name = _stream_add_sanitize_identifiers(form.get("code"), form.get("app"))
    if not safe_code or not safe_app or not safe_name:
        return False, "字段包含不支持的特殊字符"
    if Stream.objects.filter(code=safe_code).exists():
        return False, "摄像头编号已存在，请更换"
    if Stream.objects.filter(app=safe_app, name=safe_name).exists():
        return False, "该视频流名称已存在，请更换编号"

    obj = Stream()
    obj.user_id = user_id
    obj.sort = 0
    obj.code = safe_code
    obj.app = safe_app
    obj.name = safe_name
    obj.pull_stream_url = str(form.get("pull_stream_url") or "").strip()
    obj.pull_stream_type = int(form.get("pull_stream_type") or 1)
    obj.nickname = str(form.get("nickname") or "").strip()
    obj.remark = str(form.get("remark") or "").strip()
    obj.site_label = str(form.get("site_label") or "").strip()
    obj.floor_label = str(form.get("floor_label") or "").strip()
    obj.forward_state = 0  # 默认未开启转发
    obj.create_time = datetime.now()
    obj.last_update_time = datetime.now()
    obj.state = 0
    obj.save()
    return True, "添加成功"


def _stream_add_prefill_remark_items(ip: str, port_raw: str, xaddr: str) -> list:
    """Build ONVIF prefill remark items."""
    items = []
    if ip:
        items.append("onvif_ip=" + ip)
    if port_raw:
        try:
            parsed_port = int(port_raw)
        except Exception:
            logger.debug("ignore invalid ONVIF port prefill: %s", port_raw, exc_info=True)
        else:
            if 1 <= parsed_port <= 65535:
                items.append("onvif_port=" + str(parsed_port))
    if xaddr:
        items.append("onvif_xaddr=" + xaddr)
    return items


def _stream_add_get_context(request) -> dict:
    """处理流新增`get``context`。"""
    params = f_parseGetParams(request)
    ip = str(params.get("ip") or "").strip()
    xaddr = str(params.get("xaddr") or "").strip()
    port_raw = str(params.get("port") or "").strip()
    pref_name = str(params.get("name") or "").strip()
    pref_uri = str(params.get("uri") or "").strip()

    prefill_nickname = pref_name or ip
    prefill_pull_stream_url = pref_uri if is_supported_pull_stream_url(pref_uri) else ""
    prefill_remark_items = _stream_add_prefill_remark_items(ip, port_raw, xaddr)
    prefill_remark = " ".join(prefill_remark_items)
    has_onvif_prefill = bool(ip or xaddr or pref_name or prefill_pull_stream_url)

    context = {}
    code = gen_random_code_s(prefix="cam")
    app = "live"
    name = code
    public_host = get_public_host_for_urls(request)
    context["handle"] = "add"
    context["obj"] = {
        "code": code,
        "app": app,
        "name": name,
        "site_label": "",
        "floor_label": "",
        "rtspUrl": g_zlm.get_rtspUrl(app, name, public_host),
        "hlsUrl": g_zlm.get_hlsUrl(app, name, public_host),
        "httpMp4Url": g_zlm.get_httpMp4Url(app, name, public_host),
        "wsMp4Url": g_zlm.get_wsMp4Url(app, name, public_host),
        "pull_stream_url": prefill_pull_stream_url,
        "nickname": prefill_nickname,
        "remark": prefill_remark,
    }
    context["top_msg"] = "已从 ONVIF 发现页带入设备信息，请补全后提交。" if has_onvif_prefill else ""
    context["data"] = g_djangoSql.select(SQL_SELECT_ALL_STREAMS_DESC)
    return context


def add(request):
    """处理新增。"""
    if "POST" == request.method:
        form = _stream_add_parse_form(f_parsePostParams(request))
        ok, msg = _stream_add_try_create_stream(request, form)
        redirect_url = URL_STREAM_INDEX if ok else "/stream/add"
        return render(request, "app/message.html", {"msg": msg, "is_success": ok, "redirect_url": redirect_url})

    return render(request, "app/stream/web_stream_add.html", _stream_add_get_context(request))


def _stream_edit_parse_form(params: dict) -> dict:
    """处理流编辑`parse`表单。"""
    pull_stream_type = _stream_add_int(params.get("pull_stream_type", 1), 1)
    gb28181_device_id = str(params.get("gb28181_device_id", "") or "").strip()
    gb28181_channel_id = str(params.get("gb28181_channel_id", "") or "").strip()
    url_valid, normalized_url = _stream_add_normalize_pull_url(
        pull_stream_type,
        params.get("pull_stream_url", ""),
        gb28181_device_id,
        gb28181_channel_id,
    )

    return {
        "handle": params.get("handle"),
        "code": str(params.get("code") or "").strip(),
        "pull_stream_url": str(normalized_url or "").strip(),
        "pull_stream_type": int(pull_stream_type),
        "nickname": str(params.get("nickname") or "").strip(),
        "remark": str(params.get("remark") or "").strip(),
        "site_label": str(params.get("site_label") or "").strip(),
        "floor_label": str(params.get("floor_label") or "").strip(),
        "url_valid": bool(url_valid),
    }


def _stream_edit_try_update_stream(form: dict):
    """处理流编辑`try``update`流。"""
    if not (str(form.get("handle") or "").strip() == "edit" and form.get("code") and form.get("url_valid") and form.get("nickname")):
        return False, MSG_INVALID_PARAMS_CN

    code = str(form.get("code") or "").strip()
    obj = Stream.objects.get(code=code)
    pull_stream_url = str(form.get("pull_stream_url") or "").strip()
    pull_stream_type = int(form.get("pull_stream_type") or 1)
    if obj.pull_stream_url != pull_stream_url or obj.pull_stream_type != pull_stream_type:
        # 如果 拉流地址或类型更换了，需要停止转发代理
        stop_forward_for_stream(obj)

    obj.pull_stream_url = pull_stream_url
    obj.pull_stream_type = pull_stream_type
    obj.nickname = str(form.get("nickname") or "").strip()
    obj.remark = str(form.get("remark") or "").strip()
    obj.site_label = str(form.get("site_label") or "").strip()
    obj.floor_label = str(form.get("floor_label") or "").strip()
    obj.last_update_time = datetime.now()
    obj.save()

    return True, "编辑成功"


def _stream_edit_get_context(request):
    """处理流编辑`get``context`。"""
    params = f_parseGetParams(request)
    code = str(params.get("code") or "").strip()
    if not code:
        return None

    data = g_djangoSql.select(SQL_SELECT_ALL_STREAMS_DESC)
    obj = None
    for d in data:
        if code == d.get("code"):
            obj = d
            break
    if not obj:
        return None

    public_host = get_public_host_for_urls(request)
    obj["rtspUrl"] = g_zlm.get_rtspUrl(obj["app"], obj["name"], public_host)
    obj["hlsUrl"] = g_zlm.get_hlsUrl(obj["app"], obj["name"], public_host)
    obj["wsMp4Url"] = g_zlm.get_wsMp4Url(obj["app"], obj["name"], public_host)
    obj["httpMp4Url"] = g_zlm.get_httpMp4Url(obj["app"], obj["name"], public_host)

    return {
        "handle": "edit",
        "obj": obj,
        "data": data,
    }


def edit(request):
    """处理编辑。"""
    if "POST" == request.method:
        form = _stream_edit_parse_form(f_parsePostParams(request))
        ok, msg = _stream_edit_try_update_stream(form)
        redirect_url = URL_STREAM_INDEX if ok else "/stream/edit?code=" + str(form.get("code") or "")
        return render(request, "app/message.html", {"msg": msg, "is_success": ok, "redirect_url": redirect_url})

    context = _stream_edit_get_context(request)
    if context is None:
        return redirect(URL_STREAM_INDEX)
    return render(request, "app/stream/web_stream_add.html", context)

def player(request):
    """渲染播放器页面。"""
    context = {
        "talkback": _empty_talkback_player_context("请先选择一个在线视频流。"),
        "talkback_json": safe_json_dumps(_empty_talkback_player_context("请先选择一个在线视频流。"), max_len=4096, max_items=50),
    }
    params = f_parseGetParams(request)
    app = str(params.get("app") or "").strip()
    name = str(params.get("name") or "").strip()
    code = str(params.get("code") or "").strip()

    if code and (not app or not name):
        stream_row = Stream.objects.filter(code=code).only("app", "name").first()
        if stream_row:
            app = str(getattr(stream_row, "app", "") or "").strip()
            name = str(getattr(stream_row, "name", "") or "").strip()

    if app and name:
        public_host = get_public_host_for_urls(request)
        stream = GetStream(app=app, name=name, public_host=public_host)
        talkback = _build_talkback_player_context(app=app, name=name, public_host=public_host)
        if talkback.get("stream_code"):
            stream["code"] = talkback.get("stream_code")
        context["stream"] = stream
        context["is_exist_stream"] = 1
        context["webrtc_stun_urls"] = list(getattr(g_config, "webrtcStunUrls", []) or [])
        context["webrtc_turn_url"] = str(getattr(g_config, "webrtcTurnUrl", "") or "").strip()
        context["webrtc_turn_username"] = str(getattr(g_config, "webrtcTurnUsername", "") or "").strip()
        context["webrtc_turn_password_masked"] = "***" if str(getattr(g_config, "webrtcTurnPassword", "") or "").strip() else ""
        context["talkback"] = talkback
        context["talkback_json"] = safe_json_dumps(talkback, max_len=4096, max_items=50)
    else:
        context["is_exist_stream"] = 0

    return render(request, 'app/stream/player.html', context)

def player_multi(request):
    """渲染多画面播放器页面。"""
    return render(request, 'app/stream/player_multi.html', {})


def api_webrtc_self_check(request):
    """处理 `webrtcSelfCheck` 接口请求。"""
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parseGetParams(request)
    app = str(params.get("app") or "").strip()
    name = str(params.get("name") or "").strip()
    public_host = get_public_host_for_urls(request)

    from app.utils.WebRtcSelfCheck import build_webrtc_selfcheck_report

    try:
        report = build_webrtc_selfcheck_report(g_config, g_zlm, app=app, name=name, public_host=public_host)
        return f_responseJson({"code": 1000, "msg": "success", "data": report})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
api_webrtcSelfCheck = api_webrtc_self_check  # pragma: no cover - compatibility alias


def api_talkback_config_get(request):
    """处理 `talkback_config_get` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    stream_code = str(params.get("stream_code") or "").strip()
    if not stream_code:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_CODE_EMPTY_CN})

    stream = Stream.objects.filter(code=stream_code).first()
    if not stream:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_NOT_FOUND_CN})

    cfg = StreamTalkbackConfig.objects.filter(stream_code=stream_code).first() or _build_default_talkback_config(stream_code)
    return f_responseJson({"code": 1000, "msg": "success", "data": _serialize_talkback_config(cfg)})


def _maybe_update_onvif_password(cfg, params) -> None:
    """按需更新`onvif``password`。"""
    posted_password = params.get("onvif_password")
    if posted_password is None:
        return
    posted_password = str(posted_password or "").strip()
    if posted_password:
        cfg.onvif_password = posted_password


def _apply_talkback_config_params(cfg, params) -> None:
    """处理应用对讲配置参数。"""
    cfg.enabled = _talkback_bool(params.get("enabled"), default=bool(cfg.enabled))
    cfg.transport_mode = str(params.get("transport_mode") or cfg.transport_mode or "webrtc_to_rtsp").strip() or "webrtc_to_rtsp"
    cfg.onvif_service_url = str(params.get("onvif_service_url") or cfg.onvif_service_url or "").strip()
    cfg.onvif_username = str(params.get("onvif_username") or cfg.onvif_username or "").strip()
    _maybe_update_onvif_password(cfg, params)
    cfg.profile_token = str(params.get("profile_token") or cfg.profile_token or "").strip()
    cfg.backchannel_uri = str(params.get("backchannel_uri") or cfg.backchannel_uri or "").strip()
    cfg.relay_app = str(params.get("relay_app") or cfg.relay_app or "talkback").strip() or "talkback"
    cfg.relay_stream_prefix = str(params.get("relay_stream_prefix") or cfg.relay_stream_prefix or "").strip()
    cfg.sample_rate = _talkback_int(params.get("sample_rate") or cfg.sample_rate, default=16000, min_value=8000, max_value=48000)
    cfg.codec_hint = str(params.get("codec_hint") or cfg.codec_hint or "pcma").strip() or "pcma"
    cfg.remark = str(params.get("remark") or cfg.remark or "").strip()


def api_talkback_config_save(request):
    """处理 `talkback_config_save` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    stream_code = str(params.get("stream_code") or "").strip()
    if not stream_code:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_CODE_EMPTY_CN})

    stream = Stream.objects.filter(code=stream_code).first()
    if not stream:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_NOT_FOUND_CN})

    cfg, _created = StreamTalkbackConfig.objects.get_or_create(stream_code=stream_code)
    _apply_talkback_config_params(cfg, params)
    cfg.save()

    return f_responseJson({"code": 1000, "msg": "保存成功", "data": _serialize_talkback_config(cfg)})


def _talkback_start_params(params):
    """处理对讲起始参数。"""
    stream_code = str(params.get("stream_code") or "").strip()
    session_id = sanitize_stream_field(str(params.get("session_id") or "").strip(), "name")
    if not stream_code:
        return "", "", MSG_STREAM_CODE_EMPTY_CN
    if not session_id:
        return "", "", MSG_SESSION_ID_EMPTY_CN
    return stream_code, session_id, ""


def _enabled_talkback_cfg(stream_code: str):
    """处理启用对讲配置。"""
    cfg = StreamTalkbackConfig.objects.filter(stream_code=stream_code).first()
    if not cfg or not bool(getattr(cfg, "enabled", False)):
        return None
    return cfg


def _talkback_urls(cfg, *, session_id: str):
    """返回对讲URL 列表。"""
    destination_url = _resolve_talkback_backchannel_uri(cfg)
    relay_app = str(getattr(cfg, "relay_app", "talkback") or "talkback").strip() or "talkback"
    relay_stream_name = _build_talkback_stream_name(cfg, session_id)
    source_url = g_zlm.get_rtspUrl(relay_app, relay_stream_name)
    return destination_url, relay_app, relay_stream_name, source_url


def api_talkback_start(request):
    """处理 `talkback_start` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    stream_code, session_id, err = _talkback_start_params(params)
    if err:
        return f_responseJson({"code": 0, "msg": err})

    stream = Stream.objects.filter(code=stream_code).first()
    if not stream:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_NOT_FOUND_CN})

    cfg = _enabled_talkback_cfg(stream_code)
    if not cfg:
        return f_responseJson({"code": 0, "msg": "talkback 配置不存在或未启用"})

    destination_url, relay_app, relay_stream_name, source_url = _talkback_urls(cfg, session_id=session_id)
    if not destination_url:
        return f_responseJson({"code": 0, "msg": "未配置可用的 talkback 回讲地址"})

    result = _get_talkback_relay_manager().start_session(
        session_id=session_id,
        source_url=source_url,
        destination_url=destination_url,
        sample_rate=int(getattr(cfg, "sample_rate", 16000) or 16000),
        codec_hint=str(getattr(cfg, "codec_hint", "pcma") or "pcma").strip() or "pcma",
    )
    if not bool(result.get("ok")):
        return f_responseJson({"code": 0, "msg": str(result.get("msg") or "开启回讲失败"), "data": result})

    payload = dict(result)
    payload.update(
        {
            "stream_code": stream_code,
            "relay_app": relay_app,
            "relay_stream_name": relay_stream_name,
            "source_url": source_url,
        }
    )
    return f_responseJson({"code": 1000, "msg": "success", "data": payload})


def api_talkback_stop(request):
    """处理 `talkback_stop` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    session_id = sanitize_stream_field(str(params.get("session_id") or "").strip(), "name")
    if not session_id:
        return f_responseJson({"code": 0, "msg": MSG_SESSION_ID_EMPTY_CN})

    result = _get_talkback_relay_manager().stop_session(session_id)
    if not bool(result.get("ok")):
        return f_responseJson({"code": 0, "msg": str(result.get("msg") or "停止回讲失败"), "data": result})
    return f_responseJson({"code": 1000, "msg": "success", "data": result})


def api_talkback_status(request):
    """处理 `talkback_status` 接口请求。"""
    if request.method != "GET":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parseGetParams(request)
    session_id = sanitize_stream_field(str(params.get("session_id") or "").strip(), "name")
    if not session_id:
        return f_responseJson({"code": 0, "msg": MSG_SESSION_ID_EMPTY_CN})

    result = _get_talkback_relay_manager().get_status(session_id)
    if not bool(result.get("ok")):
        return f_responseJson({"code": 0, "msg": str(result.get("msg") or "查询回讲状态失败"), "data": result})
    return f_responseJson({"code": 1000, "msg": "success", "data": result})



def api_get_online(request):
    # 获取在线流
    """处理 `getOnline` 接口请求。"""
    code = 0
    msg = "未知错误"
    media_server_state = False
    data = []

    try:
        media_server_state, data = __getAllOnlineStream(is_filter_analyzer=True)

        code = 1000
        msg = "success"
    except Exception as e:
        log = "流媒体服务异常：" + str(e)
        msg = log

    top_msg = ""
    if not media_server_state:
        top_msg = "流媒体服务未运行"

    res = {
        "code": code,
        "msg": msg,
        "top_msg": top_msg,
        "data": data
    }
    return f_responseJson(res)
api_getOnline = api_get_online  # pragma: no cover - compatibility alias


def build_online_stream_app_shell_payload():
    """构建在线流`app``shell`载荷。"""
    media_ok, rows = __getAllOnlineStream(is_filter_analyzer=True)
    top_msg = "" if media_ok else "流媒体服务未运行"
    return top_msg, rows

def _stream_key(app: str, name: str) -> str:
    """返回流键。"""
    return STREAM_KEY_FMT.format(app=app, name=name)


def _index_db_streams():
    """处理索引数据库流列表。
    
    Build indexes for quick lookups during online stream listing.
        Returns:
          - db_stream_dict: {"app_name": db_row_dict}
          - db_stream_app_set: set of known Stream.app values (used to filter non-live groups)
    """
    db_stream_dict = {}
    db_stream_app_set = set()
    for db_stream in readAllStreamData():
        app = str(db_stream.get("app") or "")
        name = str(db_stream.get("name") or "")
        if not app or not name:
            continue
        db_stream_dict[_stream_key(app, name)] = db_stream
        db_stream_app_set.add(app)
    return db_stream_dict, db_stream_app_set


def _build_control_by_push_stream(online_data):
    """构建控制`by``push`流。
    
    When listing analyzer push streams, enrich with related Control metadata.
    """
    try:
        analyzer_app = g_zlm.default_push_stream_app
        analyzer_names = []
        for s in online_data or []:
            try:
                if s.get("app") == analyzer_app and s.get("name"):
                    analyzer_names.append(str(s.get("name")))
            except Exception:
                continue

        if not analyzer_names:
            return {}

        control_by_push = {}
        qs = (
            Control.objects.filter(
                push_stream=True,
                push_stream_app=analyzer_app,
                push_stream_name__in=analyzer_names,
            )
            .only("code", "stream_app", "stream_name", "algorithm_code", "remark", "push_stream_app", "push_stream_name")
        )
        for c in qs:
            key = _stream_key(str(c.push_stream_app or ""), str(c.push_stream_name or ""))
            if key:
                control_by_push[key] = c
        return control_by_push
    except Exception:
        return {}


def _auto_create_stream_from_passive_push(app: str, name: str) -> None:
    """从`passive``push`获取自动`create`流。
    
    v4.627: when we see a passive push stream in ZLM ("live/<name>") but no DB row exists,
        auto-create a Stream record so the UI can manage it.
    """
    try:
        if Stream.objects.filter(app=app, name=name).exists():
            return

        safe_code = sanitize_stream_field(name, "code")
        if not safe_code or Stream.objects.filter(code=safe_code).exists():
            safe_code = gen_random_code_s(prefix="cam")

        pull_url = g_zlm.get_rtspUrl(app, name)
        Stream.objects.create(
            user_id=0,
            sort=0,
            code=safe_code,
            app=app,
            name=name,
            pull_stream_url=pull_url,
            pull_stream_type=1,
            nickname=STREAM_PATH_FMT.format(app=app, name=name),
            remark="auto-created from passive push stream",
            forward_state=1,
            create_time=datetime.now(),
            last_update_time=datetime.now(),
            state=0,
        )
    except Exception as e:
        logger.warning("auto-create stream row failed: app=%s name=%s err=%s", app, name, e)


def _decorate_live_online_stream(online_stream, *, db_stream_dict):
    """处理装饰`live`在线流。"""
    app = str(online_stream.get("app") or "")
    name = str(online_stream.get("name") or "")
    db_stream = db_stream_dict.get(_stream_key(app, name))
    if db_stream:
        online_stream["source_type"] = 1  # 来自数据库
        online_stream["source"] = db_stream
        online_stream["source_nickname"] = db_stream.get("nickname")
        return online_stream

    _auto_create_stream_from_passive_push(app, name)
    online_stream["source_type"] = 0  # 来自推流
    online_stream["source_nickname"] = STREAM_PATH_FMT.format(app=app, name=name)
    return online_stream


def _decorate_analyzer_push_stream(online_stream, *, db_stream_dict, control_by_push):
    """处理装饰分析器`push`流。"""
    app = str(online_stream.get("app") or "")
    name = str(online_stream.get("name") or "")
    app_name = _stream_key(app, name)

    control = control_by_push.get(app_name)
    db_stream = db_stream_dict.get(app_name)
    if control:
        # Analyzer push stream: display as "<ctrl> | <src> | <algo>"
        try:
            src_app = str(getattr(control, "stream_app", "") or "")
            src_name = str(getattr(control, "stream_name", "") or "")
            algo_code = str(getattr(control, "algorithm_code", "") or "")
            ctrl_code = str(getattr(control, "code", "") or name)
        except Exception:
            src_app, src_name, algo_code, ctrl_code = "", "", "", str(name)

        online_stream["source_type"] = 2  # 算法推流
        online_stream["control_code"] = ctrl_code
        online_stream["control_stream_app"] = src_app
        online_stream["control_stream_name"] = src_name
        online_stream["control_algorithm_code"] = algo_code
        online_stream["display_name"] = "{app}/{name} | {src_app}/{src_name} | {algo}".format(
            app=app,
            name=name,
            src_app=src_app,
            src_name=src_name,
            algo=algo_code,
        )
        online_stream["source_nickname"] = online_stream["display_name"]
    elif db_stream:
        online_stream["source_type"] = 1  # 来自数据库
        online_stream["source"] = db_stream
        online_stream["source_nickname"] = db_stream.get("nickname")
    else:
        online_stream["source_type"] = 0  # 来自推流
        online_stream["source_nickname"] = STREAM_PATH_FMT.format(app=app, name=name)

    if not online_stream.get("display_name"):
        online_stream["display_name"] = STREAM_PATH_FMT.format(app=app, name=name)
    return online_stream


def _decorate_known_group_stream(online_stream, *, db_stream_dict, db_stream_app_set):
    """处理装饰`known`分组流。"""
    app = str(online_stream.get("app") or "")
    name = str(online_stream.get("name") or "")
    app_name = _stream_key(app, name)

    db_stream = db_stream_dict.get(app_name)
    if db_stream:
        online_stream["source_type"] = 1  # 来自数据库
        online_stream["source"] = db_stream
        online_stream["source_nickname"] = db_stream.get("nickname") or STREAM_PATH_FMT.format(app=app, name=name)
        if not online_stream.get("display_name"):
            online_stream["display_name"] = online_stream.get("source_nickname") or STREAM_PATH_FMT.format(app=app, name=name)
        return online_stream

    if app in db_stream_app_set:
        # best-effort: show as user push stream under known group app
        online_stream["source_type"] = 0  # 来自推流
        online_stream["source_nickname"] = STREAM_PATH_FMT.format(app=app, name=name)
        if not online_stream.get("display_name"):
            online_stream["display_name"] = online_stream["source_nickname"]
        return online_stream

    return None


def _maybe_decorate_online_stream(
    online_stream,
    *,
    db_stream_dict,
    db_stream_app_set,
    is_filter_analyzer: bool,
    control_by_push: dict,
):
    """按需处理装饰在线流。"""
    app = str(online_stream.get("app") or "")
    name = str(online_stream.get("name") or "")
    if not app or not name:
        return None

    if app == "live":
        return _decorate_live_online_stream(online_stream, db_stream_dict=db_stream_dict)

    if is_filter_analyzer and app == g_zlm.default_push_stream_app:
        return _decorate_analyzer_push_stream(
            online_stream,
            db_stream_dict=db_stream_dict,
            control_by_push=control_by_push,
        )

    return _decorate_known_group_stream(
        online_stream,
        db_stream_dict=db_stream_dict,
        db_stream_app_set=db_stream_app_set,
    )


def __get_all_online_stream(is_filter_analyzer=False):
    """获取全部在线流。"""
    online_data = g_zlm.getMediaList()
    media_server_state = g_zlm.mediaServerState
    if not media_server_state:
        return media_server_state, []

    db_stream_dict, db_stream_app_set = _index_db_streams()

    # v4.708: when listing analyzer push streams, enrich with the related control so
    # the UI can distinguish multiple algorithm streams for the same video.
    control_by_push = _build_control_by_push_stream(online_data) if is_filter_analyzer else {}

    data = []
    for online_stream in online_data or []:
        decorated = _maybe_decorate_online_stream(
            online_stream,
            db_stream_dict=db_stream_dict,
            db_stream_app_set=db_stream_app_set,
            is_filter_analyzer=bool(is_filter_analyzer),
            control_by_push=control_by_push,
        )
        if decorated:
            data.append(decorated)

    return media_server_state, data
__getAllOnlineStream = __get_all_online_stream  # pragma: no cover - compatibility alias

def api_get_all_start_forward(request):
    """处理 `getAllStartForward` 接口请求。"""
    code = 0
    if request.method == 'GET':
        __ret, __msg = AllStreamStartForward()
        msg = __msg
        if __ret:
            code = 1000
    else:
        msg = MSG_METHOD_NOT_SUPPORTED_CN

    res = {
        "code": code,
        "msg": msg
    }
    return f_responseJson(res)
api_getAllStartForward = api_get_all_start_forward  # pragma: no cover - compatibility alias


def _online_stream_key_set(online_data) -> set:
    """处理在线流键`set`。"""
    keys = set()
    for d in online_data or []:
        try:
            key = STREAM_KEY_FMT.format(app=d["app"], name=d["name"])
        except Exception:
            continue
        keys.add(key)
    return keys


def _update_forward_state_by_stream_id(stream_id_raw, *, forward_state: int) -> None:
    """更新转发状态`by`流ID。"""
    try:
        stream_id = int(stream_id_raw)
    except (ValueError, TypeError) as e:
        logger.warning("更新流状态失败: %s id=%s", e, stream_id_raw)
        return
    g_djangoSql.execute("UPDATE av_stream SET forward_state=%s WHERE id=%s", [int(forward_state), stream_id])


def api_get_all_update_forward_state(request):
    """处理 `getAllUpdateForwardState` 接口请求。"""
    try:
        media_server_state = bool(getattr(g_zlm, "mediaServerState", False))
        if not media_server_state:
            g_djangoSql.execute("UPDATE av_stream SET forward_state=0")
            return f_responseJson({"code": 1000, "msg": "刷新状态成功"})

        online_keys = _online_stream_key_set(g_zlm.getMediaList())
        stream_data = g_djangoSql.select(SQL_SELECT_ALL_STREAMS_DESC)
        for stream_d in stream_data:
            try:
                app_name = STREAM_KEY_FMT.format(app=stream_d["app"], name=stream_d["name"])
            except Exception:
                continue
            _update_forward_state_by_stream_id(
                stream_d.get("id"),
                forward_state=1 if app_name in online_keys else 0,
            )
        return f_responseJson({"code": 1000, "msg": "刷新状态成功"})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": "刷新状态失败：" + str(e)})
api_getAllUpdateForwardState = api_get_all_update_forward_state  # pragma: no cover - compatibility alias


def _open_del_delete_one(stream_code):
    """处理开放`del``delete``one`。"""
    stream = Stream.objects.filter(code=stream_code).first()
    if not stream:
        return 0, MSG_STREAM_NOT_EXIST_CN

    stop_forward_for_stream(stream)
    deleted = stream.delete()
    if deleted:
        return 1000, "删除成功"
    return 0, "删除失败！"


def _open_del_try_stop_forward(stream) -> None:
    """处理开放`del``try``stop`转发。"""
    try:
        stop_forward_for_stream(stream)
    except Exception:
        logger.debug("stop forward before stream delete failed stream_id=%s", getattr(stream, "id", None), exc_info=True)


def _open_del_try_delete_stream(stream) -> bool:
    """处理开放`del``try``delete`流。"""
    try:
        deleted = stream.delete()
    except Exception:
        return False
    return bool(deleted)


def _open_del_delete_all():
    """处理开放`del``delete`全部。"""
    streams = list(Stream.objects.all())
    if not streams:
        return 1000, "已清空（0条）"

    success_count = 0
    error_count = 0
    for stream in streams:
        _open_del_try_stop_forward(stream)
        if _open_del_try_delete_stream(stream):
            success_count += 1
        else:
            error_count += 1

    code = 1000 if success_count > 0 else 0
    msg = "成功%d条，失败%d条" % (success_count, error_count)
    return code, msg


def api_open_del(request):
    """处理 `openDel` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    handle = params.get("handle", "one")  # one：删除一个视频流，all：删除全部视频流
    stream_code = params.get("code")

    try:
        if handle == "one":
            code, msg = _open_del_delete_one(stream_code)
        elif handle == "all":
            code, msg = _open_del_delete_all()
        else:
            code, msg = 0, "request parameters are incorrect"
    except Exception as e:
        code, msg = 0, str(e)

    return f_responseJson({"code": code, "msg": msg})
api_openDel = api_open_del  # pragma: no cover - compatibility alias


def _safe_int(value, default: int = 0) -> int:
    """处理安全整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _get_user_id_from_request(request) -> int:
    """获取用户ID`from`请求。"""
    try:
        user = getUser(request) or {}
    except Exception:
        return 0
    return _safe_int((user or {}).get("id") or 0, default=0)


def _normalize_open_stream_pull_url(pull_stream_type: int, pull_stream_url: str, gb28181_device_id: str, gb28181_channel_id: str):
    """执行归一化开放流`pull`URL。"""
    url = str(pull_stream_url or "").strip()
    if int(pull_stream_type or 0) == 21:  # GB28181
        if gb28181_device_id and gb28181_channel_id:
            return f"gb28181://{gb28181_device_id}@{gb28181_channel_id}", True
        return url, False
    return url, is_supported_pull_stream_url(url)


def _create_stream_record(
    *,
    user_id: int,
    code: str,
    app: str,
    name: str,
    pull_stream_url: str,
    pull_stream_type: int,
    nickname: str,
    remark: str,
    site_label: str,
    floor_label: str,
):
    """创建流`record`。"""
    now = datetime.now()

    obj = Stream()
    obj.user_id = int(user_id or 0)
    obj.sort = 0
    obj.code = code
    obj.app = app
    obj.name = name
    obj.pull_stream_url = pull_stream_url
    obj.pull_stream_type = int(pull_stream_type or 0)
    obj.nickname = nickname
    obj.remark = remark
    obj.site_label = site_label
    obj.floor_label = floor_label
    obj.forward_state = 0  # 默认未开启转发
    obj.create_time = now
    obj.last_update_time = now
    obj.state = 0
    obj.save()
    return obj


def _touch_stream_last_update_time(stream) -> None:
    """刷新流`last``update`时间。"""
    try:
        stream.last_update_time = datetime.now()
    except Exception:
        logger.debug("touch stream last_update_time failed stream_id=%s", getattr(stream, "id", None), exc_info=True)


def _param_str(params, key: str) -> str:
    """处理参数字符串。"""
    value = params.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _param_int(params, key: str, default: int) -> int:
    """处理参数整数值。"""
    value = params.get(key)
    if value in (None, ""):
        return int(default)
    return _safe_int(value, default=default)


def _is_open_add_params_valid(safe_code: str, nickname: str, url_valid: bool) -> bool:
    """判断开放新增参数`valid`。"""
    if not safe_code:
        return False
    if not nickname:
        return False
    return bool(url_valid)


def _is_open_stream_url_ok(pull_stream_url: str, url_valid: bool) -> bool:
    """判断`is`开放流URL是否通过。"""
    if not str(pull_stream_url or "").strip():
        return False
    return bool(url_valid)


def _stream_app_or_default(safe_app: str, stream) -> str:
    """处理流`app``or`默认。"""
    if safe_app:
        return safe_app
    current = str(getattr(stream, "app", "") or "").strip()
    if current:
        return current
    return "live"


def _stream_name_or_code(stream, safe_code: str) -> str:
    """处理流名称`or`编码。"""
    name = str(getattr(stream, "name", "") or "").strip()
    return name if name else safe_code


def api_open_add(request):
    """处理 `openAdd` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})
    params = f_parsePostParams(request)

    raw_code = _param_str(params, "code")
    raw_app = _param_str(params, "app")
    pull_stream_url = _param_str(params, "pull_stream_url")
    pull_stream_type = _param_int(params, "pull_stream_type", 1)
    nickname = _param_str(params, "nickname")
    remark = _param_str(params, "remark")
    site_label = _param_str(params, "site_label")
    floor_label = _param_str(params, "floor_label")

    gb28181_device_id = _param_str(params, "gb28181_device_id")
    gb28181_channel_id = _param_str(params, "gb28181_channel_id")

    safe_code = sanitize_stream_field(raw_code, "code")
    safe_app = sanitize_stream_field(raw_app, "app") or "live"
    safe_name = safe_code

    pull_stream_url, url_valid = _normalize_open_stream_pull_url(
        pull_stream_type,
        pull_stream_url,
        gb28181_device_id,
        gb28181_channel_id,
    )
    if not _is_open_add_params_valid(safe_code, nickname, url_valid):
        return f_responseJson({"code": 0, "msg": MSG_INVALID_PARAMS_CN})

    if Stream.objects.filter(code=safe_code).exists():
        return f_responseJson({"code": 0, "msg": "摄像头编号已存在，请更换"})

    if Stream.objects.filter(app=safe_app, name=safe_name).exists():
        return f_responseJson({"code": 0, "msg": "该视频流名称已存在，请更换编号"})

    user_id = _get_user_id_from_request(request)
    try:
        _create_stream_record(
            user_id=user_id,
            code=safe_code,
            app=safe_app,
            name=safe_name,
            pull_stream_url=pull_stream_url,
            pull_stream_type=pull_stream_type,
            nickname=nickname,
            remark=remark,
            site_label=site_label,
            floor_label=floor_label,
        )
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    return f_responseJson({"code": 1000, "msg": "添加成功"})
api_openAdd = api_open_add  # pragma: no cover - compatibility alias

def api_open_get(request):
    """
    OpenAPI / 集群接口：查询单个视频流详情（用于弹窗编辑等场景）。

    GET/POST /stream/openGet?code=...
    """
    code = 0
    params = {}
    try:
        if request.method == "POST":
            params = f_parsePostParams(request)
        else:
            params = f_parseGetParams(request)
    except Exception:
        params = {}

    stream_code = str(params.get("code") or params.get("streamCode") or params.get("stream_code") or "").strip()
    if not stream_code:
        return f_responseJson({"code": code, "msg": "code is required"})

    stream = Stream.objects.filter(code=stream_code).first()
    if not stream:
        return f_responseJson({"code": code, "msg": MSG_STREAM_NOT_EXIST_CN})

    # GB28181: gb28181://device@channel
    gb28181_device_id = ""
    gb28181_channel_id = ""
    try:
        pull_url = str(getattr(stream, "pull_stream_url", "") or "").strip()
        if pull_url.lower().startswith("gb28181://"):
            raw = pull_url[len("gb28181://"):]
            if "@" in raw:
                gb28181_device_id, gb28181_channel_id = raw.split("@", 1)
    except Exception:
        gb28181_device_id = ""
        gb28181_channel_id = ""

    data = {
        "code": getattr(stream, "code", ""),
        "app": getattr(stream, "app", ""),
        "name": getattr(stream, "name", ""),
        "nickname": getattr(stream, "nickname", ""),
        "remark": getattr(stream, "remark", ""),
        "site_label": getattr(stream, "site_label", ""),
        "floor_label": getattr(stream, "floor_label", ""),
        "pull_stream_url": getattr(stream, "pull_stream_url", ""),
        "pull_stream_type": int(getattr(stream, "pull_stream_type", 0) or 0),
        "forward_state": int(getattr(stream, "forward_state", 0) or 0),
        "state": int(getattr(stream, "state", 0) or 0),
        "gb28181_device_id": gb28181_device_id,
        "gb28181_channel_id": gb28181_channel_id,
    }
    return f_responseJson({"code": 1000, "msg": "success", "data": data})
api_openGet = api_open_get  # pragma: no cover - compatibility alias


def api_open_edit(request):
    """
    OpenAPI / 集群接口：编辑视频流（用于弹窗编辑等场景）。

    POST /stream/openEdit
    body: {code, app?, pull_stream_url?, pull_stream_type?, nickname?, remark?, gb28181_device_id?, gb28181_channel_id?}
    """
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)

    raw_code = _param_str(params, "code")
    raw_app = _param_str(params, "app")
    pull_stream_url = _param_str(params, "pull_stream_url")
    pull_stream_type = _param_int(params, "pull_stream_type", 1)
    nickname = _param_str(params, "nickname")
    remark = _param_str(params, "remark")
    site_label = _param_str(params, "site_label")
    floor_label = _param_str(params, "floor_label")

    gb28181_device_id = _param_str(params, "gb28181_device_id")
    gb28181_channel_id = _param_str(params, "gb28181_channel_id")

    safe_code = sanitize_stream_field(raw_code, "code")
    safe_app = sanitize_stream_field(raw_app, "app") or ""

    if not safe_code:
        return f_responseJson({"code": 0, "msg": "code is required"})

    stream = Stream.objects.filter(code=safe_code).first()
    if not stream:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_NOT_EXIST_CN})

    if not nickname:
        return f_responseJson({"code": 0, "msg": "摄像头名称不能为空"})

    safe_app = _stream_app_or_default(safe_app, stream)
    safe_name = _stream_name_or_code(stream, safe_code)

    pull_stream_url, url_valid = _normalize_open_stream_pull_url(
        pull_stream_type,
        pull_stream_url,
        gb28181_device_id,
        gb28181_channel_id,
    )
    if not _is_open_stream_url_ok(pull_stream_url, url_valid):
        return f_responseJson({"code": 0, "msg": "视频流地址格式错误"})

    # Ensure (app, name) remains unique (consistent with openAdd rule).
    if Stream.objects.filter(app=safe_app, name=safe_name).exclude(id=getattr(stream, "id", 0)).exists():
        return f_responseJson({"code": 0, "msg": "该视频流名称已存在，请更换分组或编号"})

    try:
        stream.app = safe_app
        stream.name = safe_name
        stream.pull_stream_url = pull_stream_url
        stream.pull_stream_type = pull_stream_type
        stream.nickname = nickname
        stream.remark = remark
        stream.site_label = site_label
        stream.floor_label = floor_label
        _touch_stream_last_update_time(stream)
        stream.save()
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    return f_responseJson({"code": 1000, "msg": "success"})
api_openEdit = api_open_edit  # pragma: no cover - compatibility alias


def api_open_set_state(request):
    """处理 `openSetState` 接口请求，切换视频流启停状态。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    safe_code = sanitize_stream_field(_param_str(params, "code"), "code")
    if not safe_code:
        return f_responseJson({"code": 0, "msg": "code is required"})

    stream = Stream.objects.filter(code=safe_code).first()
    if not stream:
        return f_responseJson({"code": 0, "msg": MSG_STREAM_NOT_EXIST_CN})

    next_state = 1 if _param_int(params, "state", 0) == 1 else 0
    try:
        stream.state = next_state
        _touch_stream_last_update_time(stream)
        stream.save(update_fields=["state", "last_update_time"])
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})

    return f_responseJson({"code": 1000, "msg": "启用成功" if next_state == 1 else "停用成功"})
api_openSetState = api_open_set_state  # pragma: no cover - compatibility alias


def api_open_add_stream_proxy(request):
    """处理 `openAddStreamProxy` 接口请求。"""
    code = 0
    msg = "未知错误"
    if request.method == 'POST':
        params = f_parsePostParams(request)
        stream_code = params.get("code")
        try:
            stream = Stream.objects.get(code=stream_code)
            if stream.forward_state == 1:
                code = 1000
                msg = "开启转发已经成功"
            else:
                ok, forward_msg = start_forward_for_stream(stream)
                if ok:
                    code = 1000
                msg = forward_msg

        except Exception as e:
            msg = "openAddStreamProxy() error:" + str(e)
    else:
        msg = MSG_METHOD_NOT_SUPPORTED_CN

    res = {
        "code": code,
        "msg": msg
    }
    return f_responseJson(res)
api_openAddStreamProxy = api_open_add_stream_proxy  # pragma: no cover - compatibility alias


def _get_first_str_param(params, *keys) -> str:
    """获取首个字符串参数。"""
    for key in keys:
        value = params.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _ptz_error(msg: str):
    """处理云台错误。"""
    return f_responseJson({"code": 0, "msg": msg})


def _ptz_speed(params) -> int:
    """处理云台`speed`。"""
    speed = _safe_int(params.get("speed") or 32, default=32)
    if speed < 0:
        return 0
    if speed > 255:
        return 255
    return int(speed)


def _ptz_parse_preset_index(params):
    """返回云台`parse`预设索引。"""
    preset_raw = params.get("preset_index")
    if preset_raw is None:
        preset_raw = params.get("presetIndex")
    if preset_raw in (None, ""):
        return None, None
    try:
        return int(preset_raw), None
    except Exception:
        return None, _ptz_error("preset_index 格式错误")


def _ptz_resolve_device_channel(stream_code: str, device_id: str, channel_id: str):
    """处理云台`resolve`设备`channel`。"""
    safe_code = str(stream_code or "").strip()
    if not safe_code:
        return device_id, channel_id, None
    if device_id and channel_id:
        return device_id, channel_id, None

    stream = Stream.objects.filter(code=safe_code).first()
    if not stream:
        return "", "", _ptz_error(MSG_STREAM_NOT_EXIST_CN)
    if int(getattr(stream, "pull_stream_type", 0) or 0) != 21:
        return "", "", _ptz_error("该视频流不是 GB28181 类型")

    pull_stream_url = str(getattr(stream, "pull_stream_url", "") or "").strip()
    resolved_device_id, resolved_channel_id = parse_gb28181_url(pull_stream_url)
    return str(resolved_device_id or "").strip(), str(resolved_channel_id or "").strip(), None


def api_open_gb28181_ptz(request):
    """处理 `openGb28181Ptz` 接口请求。"""
    if request.method != "POST":
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    stream_code = _get_first_str_param(params, "code", "streamCode", "stream_code")
    device_id = _get_first_str_param(params, "device_id", "deviceId")
    channel_id = _get_first_str_param(params, "channel_id", "channelId")
    action = _get_first_str_param(params, "action").lower()
    speed = _ptz_speed(params)

    preset_index, preset_resp = _ptz_parse_preset_index(params)
    if preset_resp:
        return preset_resp

    if action not in GB28181_PTZ_ACTIONS:
        return _ptz_error("不支持的 PTZ action")

    device_id, channel_id, resolve_resp = _ptz_resolve_device_channel(stream_code, device_id, channel_id)
    if resolve_resp:
        return resolve_resp

    if not device_id or not channel_id:
        return _ptz_error("device_id/channel_id 不能为空")

    if not g_gb28181_provider:
        return _ptz_error("GB28181 provider 未配置")

    try:
        payload = g_gb28181_provider.ptz_control(
            device_id,
            channel_id,
            action,
            speed=speed,
            preset_index=preset_index,
        )
    except Exception as e:
        return _ptz_error(str(e))

    return f_responseJson({"code": 1000, "msg": "success", "data": payload})
api_openGb28181Ptz = api_open_gb28181_ptz  # pragma: no cover - compatibility alias


def api_open_del_stream_proxy(request):
    """处理 `openDelStreamProxy` 接口请求。"""
    code = 0
    msg = "未知错误"
    if request.method == 'POST':
        params = f_parsePostParams(request)
        stream_code = params.get("code")
        try:
            stream = Stream.objects.get(code=stream_code)
            ok, forward_msg = stop_forward_for_stream(stream)
            if ok:
                code = 1000
            msg = forward_msg

        except Exception as e:
            msg = "openDelStreamProxy() error:" + str(e)
    else:
        msg = MSG_METHOD_NOT_SUPPORTED_CN
    res = {
        "code": code,
        "msg": msg
    }
    return f_responseJson(res)
api_openDelStreamProxy = api_open_del_stream_proxy  # pragma: no cover - compatibility alias

def api_open_add_stream_pusher_proxy(request):
    # （v3.502新增）开启转推代理
    """处理 `openAddStreamPusherProxy` 接口请求。"""
    ret = False
    msg = "未知错误"
    key = ""  # 转推key

    if request.method != "POST":
        msg = "request method not supported"
        res = {"code": 0, "msg": msg, "key": key}
        logger.debug("StreamView.openAddStreamPusherProxy() res=%s", safe_json_dumps(res, max_len=1024))
        return f_responseJson(res)

    params = f_parsePostParams(request)
    logger.debug("StreamView.openAddStreamPusherProxy() params=%s", safe_json_dumps(params, max_len=1024))
    stream_app = str(params.get("stream_app") or "").strip()
    stream_name = str(params.get("stream_name") or "").strip()
    dst_stream_app = str(params.get("dst_stream_app") or "").strip()
    dst_stream_name = str(params.get("dst_stream_name") or "").strip()
    dst_host = str(params.get("dst_host") or "").strip()
    try:
        dst_rtsp_port = int(params.get("dst_rtsp_port", 554) or 554)
    except Exception:
        dst_rtsp_port = 554

    try:
        __key, __msg = g_zlm.addStreamPusherProxy(
            app=stream_app,
            name=stream_name,
            schema="rtsp",
            dst_url="rtsp://%s:%d/%s/%s" % (dst_host, dst_rtsp_port, dst_stream_app, dst_stream_name),
        )
        logger.debug("StreamView.openAddStreamPusherProxy() key=%s msg=%s", __key, __msg)
        if __key:
            ret = True
            msg = "success"
            key = __key
        else:
            msg = str(__msg or "failed")
    except Exception as e:
        msg = str(e)

    res = {"code": 1000 if ret else 0, "msg": msg, "key": key}
    logger.debug("StreamView.openAddStreamPusherProxy() res=%s", safe_json_dumps(res, max_len=1024))
    return f_responseJson(res)
api_openAddStreamPusherProxy = api_open_add_stream_pusher_proxy  # pragma: no cover - compatibility alias


def _parse_codes(params):
    """解析编码列表。"""
    codes = params.get("codes")
    if isinstance(codes, list):
        raw_codes = codes
    else:
        raw_codes = str(codes or "").split(",")
    return [c.strip() for c in raw_codes if c and str(c).strip()]


def _batch_add_stream_proxy_one(stream_code: str):
    """处理批量新增流代理`one`。"""
    try:
        stream = Stream.objects.filter(code=stream_code).first()
        if not stream:
            return False, {"code": stream_code, "result_code": 0, "msg": "摄像头不存在"}
        if int(stream.forward_state or 0) == 1:
            return True, {"code": stream_code, "result_code": 1000, "msg": "已在转发中"}

        ok, forward_msg = start_forward_for_stream(stream)
        if ok:
            return True, {"code": stream_code, "result_code": 1000, "msg": forward_msg or "开启转发成功"}
        return False, {"code": stream_code, "result_code": 0, "msg": forward_msg or "开启转发失败"}
    except Exception as e:
        return False, {"code": stream_code, "result_code": 0, "msg": str(e)}


def api_open_batch_add_stream_proxy(request):
    """处理 `openBatchAddStreamProxy` 接口请求。"""
    code = 0
    results = []

    if request.method != "POST":
        return f_responseJson({"code": code, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    codes = _parse_codes(params)
    if not codes:
        return f_responseJson({"code": code, "msg": "请至少选择一条摄像头"})

    success_count = 0
    fail_count = 0
    for stream_code in codes:
        ok, result = _batch_add_stream_proxy_one(stream_code)
        results.append(result)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    if success_count > 0:
        code = 1000
        msg = "批量开启完成：成功%d条，失败%d条" % (success_count, fail_count)
    else:
        msg = "批量开启失败：失败%d条" % fail_count

    return f_responseJson({"code": code, "msg": msg, "results": results})
api_openBatchAddStreamProxy = api_open_batch_add_stream_proxy  # pragma: no cover - compatibility alias


def api_open_batch_del_stream_proxy(request):
    """处理 `openBatchDelStreamProxy` 接口请求。"""
    code = 0
    msg = "未知错误"
    results = []

    if request.method != "POST":
        return f_responseJson({"code": code, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    params = f_parsePostParams(request)
    codes = _parse_codes(params)
    if not codes:
        return f_responseJson({"code": code, "msg": "请至少选择一条摄像头"})

    success_count = 0
    fail_count = 0
    for stream_code in codes:
        try:
            stream = Stream.objects.filter(code=stream_code).first()
            if not stream:
                raise LookupError("摄像头不存在")
            ok, forward_msg = stop_forward_for_stream(stream)
            if ok:
                success_count += 1
                results.append({"code": stream_code, "result_code": 1000, "msg": forward_msg or "停止转发成功"})
            else:
                fail_count += 1
                results.append({"code": stream_code, "result_code": 0, "msg": forward_msg or "停止转发失败"})
        except Exception as e:
            fail_count += 1
            results.append({"code": stream_code, "result_code": 0, "msg": str(e)})

    if success_count > 0:
        code = 1000
        msg = "批量停止完成：成功%d条，失败%d条" % (success_count, fail_count)
    else:
        msg = "批量停止失败：失败%d条" % fail_count

    return f_responseJson({"code": code, "msg": msg, "results": results})
api_openBatchDelStreamProxy = api_open_batch_del_stream_proxy  # pragma: no cover - compatibility alias

def _safe_get_user_id(request) -> int:
    """返回安全`get`用户ID。"""
    try:
        return int(getUser(request).get("id") or 0)
    except Exception:
        return 0


def _parse_stream_import_rows_csv(uploaded_file):
    """解析流导入记录CSV。"""
    import csv
    from io import StringIO

    try:
        content = uploaded_file.read().decode("utf-8-sig", errors="replace")
    except Exception as e:
        return None, "读取CSV失败：%s" % str(e)

    rows = []
    reader = csv.reader(StringIO(content))
    header_skipped = False
    for row in reader:
        if not header_skipped:
            header_skipped = True
            continue
        if not row or not row[0]:
            continue
        rows.append(
            {
                "nickname": str(row[0]).strip(),
                "rtsp_url": str(row[1]).strip() if len(row) > 1 else "",
                "remark": str(row[2]).strip() if len(row) > 2 else "",
                "code": str(row[3]).strip() if len(row) > 3 else "",  # 支持自定义编号
            }
        )
    return rows, ""


def _parse_stream_import_rows(uploaded_file):
    """解析流导入记录。"""
    filename = str(getattr(uploaded_file, "name", "") or "").lower()
    if filename.endswith(".csv"):
        return _parse_stream_import_rows_csv(uploaded_file)
    return None, "仅支持 CSV 文件"


def _stream_import_clean_str(value) -> str:
    """处理流导入清理字符串。"""
    return str(value or "").strip()


def _stream_import_existing_urls(candidate_urls: list) -> set:
    """返回流导入现有URL 列表。"""
    if not candidate_urls:
        return set()
    try:
        return set(Stream.objects.filter(pull_stream_url__in=candidate_urls).values_list("pull_stream_url", flat=True))
    except Exception:
        return set()


def _stream_import_existing_codes(candidate_codes: list) -> set:
    """处理流导入现有编码列表。"""
    if not candidate_codes:
        return set()
    try:
        return set(Stream.objects.filter(code__in=candidate_codes).values_list("code", flat=True))
    except Exception:
        return set()


def _stream_import_preload_existing(rows: list):
    """处理流导入`preload`现有。"""
    candidate_urls = []
    candidate_codes = []
    for row in rows or []:
        rtsp_url = _stream_import_clean_str((row or {}).get("rtsp_url"))
        if rtsp_url:
            candidate_urls.append(rtsp_url)
        code = _stream_import_clean_str((row or {}).get("code"))
        if code:
            candidate_codes.append(code)

    return _stream_import_existing_urls(candidate_urls), _stream_import_existing_codes(candidate_codes)


def _stream_import_generate_unique_code(*, seen_codes: set):
    """处理流导入`generate`去重后编码。"""
    stream_code = gen_random_code_s(prefix="cam")
    for _ in range(3):
        if not Stream.objects.filter(code=stream_code).exists() and stream_code not in seen_codes:
            break
        stream_code = gen_random_code_s(prefix="cam")
    return stream_code


def _stream_import_pick_stream_code(custom_code: str, *, seen_codes: set, existing_codes: set):
    """处理流导入选择流编码。"""
    if custom_code:
        if custom_code in existing_codes or custom_code in seen_codes:
            return "", f"摄像头编号'{custom_code}'已存在"
        return custom_code, ""

    return _stream_import_generate_unique_code(seen_codes=seen_codes), ""


def _stream_import_prepare_row(
    idx: int,
    row_data: dict,
    *,
    existing_urls: set,
    existing_codes: set,
    seen_urls: set,
    seen_codes: set,
):
    """返回流导入`prepare`记录。"""
    row_data = row_data or {}

    nickname = _stream_import_clean_str(row_data.get("nickname"))
    if not nickname:
        return None, f"第{idx}行：昵称不能为空"

    rtsp_url = _stream_import_clean_str(row_data.get("rtsp_url"))
    if not is_supported_pull_stream_url(rtsp_url):
        return None, f"第{idx}行：视频流地址格式错误"

    if rtsp_url in existing_urls or rtsp_url in seen_urls:
        return None, f"第{idx}行：视频流地址已存在"

    remark = _stream_import_clean_str(row_data.get("remark"))
    custom_code = _stream_import_clean_str(row_data.get("code"))

    stream_code, err = _stream_import_pick_stream_code(
        custom_code,
        seen_codes=seen_codes,
        existing_codes=existing_codes,
    )
    if err:
        return None, f"第{idx}行：{err}"

    return {
        "nickname": nickname,
        "rtsp_url": rtsp_url,
        "remark": remark,
        "stream_code": stream_code,
    }, ""


def _stream_import_create_stream(*, user_id: int, stream_code: str, nickname: str, rtsp_url: str, remark: str):
    """处理流导入`create`流。"""
    Stream.objects.create(
        user_id=user_id,
        sort=0,
        code=stream_code,
        app="live",
        name=stream_code,
        pull_stream_url=rtsp_url,
        pull_stream_type=0,
        nickname=nickname,
        remark=remark,
        forward_state=0,
        create_time=datetime.now(),
        last_update_time=datetime.now(),
        state=0,
    )


def _import_stream_row(
    idx: int,
    row_data: dict,
    *,
    user_id: int,
    existing_urls: set,
    existing_codes: set,
    seen_urls: set,
    seen_codes: set,
):
    """执行导入流记录。"""
    prepared, err = _stream_import_prepare_row(
        idx,
        row_data,
        existing_urls=existing_urls,
        existing_codes=existing_codes,
        seen_urls=seen_urls,
        seen_codes=seen_codes,
    )
    if err:
        return False, err, "", ""

    try:
        _stream_import_create_stream(
            user_id=user_id,
            stream_code=prepared["stream_code"],
            nickname=prepared["nickname"],
            rtsp_url=prepared["rtsp_url"],
            remark=prepared["remark"],
        )
    except Exception as e:
        return False, f"第{idx}行：保存失败 - {str(e)}", "", ""

    return True, "", prepared["rtsp_url"], prepared["stream_code"]


def _import_stream_rows(rows, *, user_id: int):
    """执行导入流记录。
    
    Returns: (success_count, error_count, error_list)
    """
    success_count = 0
    error_count = 0
    error_list = []

    existing_urls, existing_codes = _stream_import_preload_existing(rows)
    seen_urls = set()
    seen_codes = set()

    for idx, row_data in enumerate(rows, start=2):
        ok, err_msg, rtsp_url, stream_code = _import_stream_row(
            idx,
            row_data,
            user_id=user_id,
            existing_urls=existing_urls,
            existing_codes=existing_codes,
            seen_urls=seen_urls,
            seen_codes=seen_codes,
        )
        if ok:
            success_count += 1
            if rtsp_url:
                seen_urls.add(rtsp_url)
            if stream_code:
                seen_codes.add(stream_code)
        else:
            error_count += 1
            error_list.append(err_msg)

    return success_count, error_count, error_list


def api_batch_import(request):
    """
    批量导入摄像头
    支持 CSV (.csv) 文件
    列格式：昵称, 视频流地址, 备注, 摄像头编号(可选)
    """
    code = 0
    msg = "未知错误"
    success_count = 0
    error_count = 0
    error_list = []

    if request.method != "POST":
        return f_responseJson({"code": code, "msg": MSG_METHOD_NOT_SUPPORTED_CN})

    try:
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return f_responseJson({"code": code, "msg": "请选择要上传的文件"})
        if int(getattr(uploaded_file, "size", 0) or 0) > 5 * 1024 * 1024:
            return f_responseJson({"code": code, "msg": "CSV 文件不能超过 5 MB"})

        rows, parse_err = _parse_stream_import_rows(uploaded_file)
        if parse_err:
            return f_responseJson({"code": code, "msg": parse_err})
        if not rows:
            return f_responseJson({"code": code, "msg": "文件中没有有效数据"})

        user_id = _safe_get_user_id(request)
        success_count, error_count, error_list = _import_stream_rows(rows, user_id=user_id)

        if success_count > 0:
            code = 1000
            msg = f"导入完成：成功{success_count}条，失败{error_count}条"
        else:
            msg = "导入失败"
    except Exception as e:
        msg = f"导入失败：{str(e)}"

    result = {"code": code, "msg": msg, "success_count": success_count, "error_count": error_count}
    if error_list:
        result["error_list"] = error_list[:10]  # 最多返回前10条错误
    return f_responseJson(result)
api_batchImport = api_batch_import  # pragma: no cover - compatibility alias


def api_get_auto_start_config(request):
    """处理 `getAutoStartConfig` 接口请求。"""
    from app.models import SystemConfig
    try:
        config = SystemConfig.objects.filter(key='stream_auto_start').first()
        auto_start = config.value == '1' if config else False
    except Exception:
        auto_start = False
    return f_responseJson({"code": 1000, "msg": "success", "auto_start": auto_start})
api_getAutoStartConfig = api_get_auto_start_config  # pragma: no cover - compatibility alias


def api_set_auto_start_config(request):
    """处理 `setAutoStartConfig` 接口请求。"""
    code = 0
    msg = "未知错误"
    if request.method == 'POST':
        params = f_parsePostParams(request)
        auto_start = params.get("auto_start", "0")
        from app.models import SystemConfig

        try:
            config, created = SystemConfig.objects.get_or_create(
                key='stream_auto_start',
                defaults={'value': auto_start, 'remark': '摄像头自启动转发'}
            )
            if not created:
                config.value = auto_start
                config.save()
            code = 1000
            msg = "设置成功"
        except Exception as e:
            msg = f"设置失败：{str(e)}"
    return f_responseJson({"code": code, "msg": msg})
api_setAutoStartConfig = api_set_auto_start_config  # pragma: no cover - compatibility alias


def execute_auto_start():
    """执行自动起始。"""
    from app.models import SystemConfig

    try:
        config = SystemConfig.objects.filter(key='stream_auto_start').first()
        if config and config.value == '1':
            AllStreamStartForward()
            return True
    except Exception:
        logger.exception("execute auto-start forward failed")
    return False
executeAutoStart = execute_auto_start  # pragma: no cover - compatibility alias


def _playurl_normalize_codec(value):
    """处理播放 URL归一化编解码器。"""
    s = str(value or "").strip().lower()
    if not s:
        return ""
    if "265" in s or "hevc" in s:
        return "h265"
    if "264" in s:
        return "h264"
    return s


def _playurl_ffmpeg_cmd_key(target_height: int) -> str:
    """返回播放 URL`ffmpeg``cmd`键。"""
    if target_height >= 1080:
        return "ffmpeg.cmd_1080p"
    if target_height >= 720:
        return "ffmpeg.cmd_720p"
    if target_height >= 540:
        return "ffmpeg.cmd_540p"
    if target_height >= 360:
        return "ffmpeg.cmd_360p"
    return "ffmpeg.cmd_270p"


def _playurl_infer_demux_type(url: str) -> str:
    """返回播放 URL推理`demux`类型。"""
    u = str(url or "").lower()
    return "fmp4" if ".mp4" in u else "flv"


def _playurl_find_media_list_row(app: str, name: str) -> dict:
    """返回播放 URL`find`媒体列表记录。"""
    try:
        rows = g_zlm.getMediaList() or []
    except Exception:
        rows = []

    app = str(app or "").strip()
    name = str(name or "").strip()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_app = str(row.get("app") or "").strip()
        row_name = str(row.get("name") or "").strip()
        if row_app == app and row_name == name:
            return row
    return {}


def _playurl_parse_video_height(value) -> int:
    """处理播放 URL`parse``video``height`。"""
    try:
        parsed = int(value)
        return parsed if parsed > 0 else 0
    except Exception:
        logger.debug("parse video height as integer failed: %s", value, exc_info=True)

    text = str(value or "").strip()
    dimensions = text.lower().split("x", 1)
    if len(dimensions) != 2:
        return 0
    try:
        return int(dimensions[1].strip() or 0)
    except Exception:
        return 0


def _playurl_recover_stream_from_media_list(stream: dict, *, app: str, name: str) -> dict:
    """从媒体列表获取播放 URL`recover`流。"""
    stream = dict(stream or {})
    if stream.get("is_online"):
        return stream

    media_row = _playurl_find_media_list_row(app, name)
    if not media_row:
        return stream

    stream["is_online"] = 1
    if not str(stream.get("video_codec_name") or "").strip():
        stream["video_codec_name"] = (
            str(media_row.get("video_codec_name") or "").strip()
            or str(media_row.get("video_codec") or "").strip()
            or str(media_row.get("video") or "").strip()
        )
    if not int(stream.get("video_height") or 0):
        stream["video_height"] = _playurl_parse_video_height(
            media_row.get("video_height") or media_row.get("video")
        )
    return stream


def _playurl_make_data(
    *,
    url: str,
    codec: str,
    origin_codec: str,
    mode: str,
    demux_type: str,
    is_transcode: int,
    target_height: int,
    ffmpeg_cmd_key: str,
    app: str,
    name: str,
    public_host: str,
):
    """返回播放 URL生成数据。"""
    webrtc_url = g_zlm.get_webrtcDemoUrl(app, name, public_host, type="play")
    return {
        "url": url,
        "codec": codec or "",
        "origin_codec": origin_codec or "",
        "mode": mode,
        "demuxType": demux_type,
        "is_transcode": int(is_transcode or 0),
        "target_height": int(target_height or 0),
        "ffmpeg_cmd_key": ffmpeg_cmd_key or "",
        "app": app,
        "name": name,
        "embed_url": webrtc_url,
        "embed_type": "iframe" if webrtc_url else "",
        "webrtc_url": webrtc_url,
        "webrtc_api_url": g_zlm.get_webrtcApiUrl(app, name, public_host, type="play"),
    }


def _playurl_target_height(layout: int, quality: str) -> int:
    """处理播放 URL`target``height`。"""
    auto_target_map = {1: 1080, 2: 720, 4: 720, 9: 540, 16: 360}
    q = str(quality or "").strip().lower()
    if q in ("origin", "src", "source"):
        return 0
    if q.isdigit():
        try:
            return max(0, int(q))
        except (TypeError, ValueError):
            return 0
    return int(auto_target_map.get(layout, 0) or 0)


def _playurl_transcode_stream_name(app: str, name: str, *, origin_height: int, target_height: int, need_downscale: bool) -> str:
    """返回播放 URL转码流名称。"""
    height_tag = 0
    if need_downscale and target_height:
        height_tag = target_height
    elif origin_height:
        height_tag = origin_height
    if height_tag:
        return f"{app}_{name}_h264_{height_tag}p"
    return f"{app}_{name}_h264_orig"


def _playurl_touch_transcode_manager(stream_id: str) -> None:
    """处理播放 URL刷新转码`manager`。"""
    try:
        tm = get_transcode_manager()
        if tm:
            tm.touch_stream(stream_id)
    except Exception:
        logger.debug("touch transcode manager failed stream_id=%s", stream_id, exc_info=True)


def _playurl_transcode_pending_response(
    *,
    msg: str,
    retry_after_ms: int,
    public_host: str,
    trans_app: str,
    trans_name: str,
    out_codec: str,
    origin_codec: str,
    target_height: int,
    ffmpeg_cmd_key: str,
):
    """返回播放 URL转码`pending`响应。"""
    play_url = g_zlm.get_wsFlvUrl(trans_app, trans_name, public_host)
    data = _playurl_make_data(
        url=play_url,
        codec=out_codec or "",
        origin_codec=origin_codec or "",
        mode="compat",
        demux_type=_playurl_infer_demux_type(play_url),
        is_transcode=1,
        target_height=target_height,
        ffmpeg_cmd_key=ffmpeg_cmd_key,
        app=trans_app,
        name=trans_name,
        public_host=public_host,
    )
    return f_responseJson({"code": 1001, "msg": msg, "retry_after_ms": int(retry_after_ms or 0), "data": data})


def _playurl_is_transcode_online(trans_app: str, trans_name: str) -> bool:
    """处理播放 URL`is`转码在线。"""
    try:
        trans_online = g_zlm.getMediaInfo(trans_app, trans_name, schema="rtmp") or {}
    except Exception:
        trans_online = {}
    return bool(trans_online.get("ret"))


def _playurl_get_transcode_manager_best_effort():
    """尽力处理播放 URL`get`转码`manager`。"""
    try:
        return get_transcode_manager()
    except Exception:
        return None


def _playurl_retry_after_ms(tm, token: str, default: int) -> int:
    """处理播放 URL`retry``after``ms`。"""
    retry_after_ms = 0
    try:
        if tm and hasattr(tm, "cooldown_remaining_ms"):
            retry_after_ms = int(tm.cooldown_remaining_ms(token) or 0)
    except Exception:
        retry_after_ms = 0
    if retry_after_ms <= 0:
        return int(default)
    return retry_after_ms


def _playurl_ensure_transcode_ready(
    *,
    src_app: str,
    src_name: str,
    public_host: str,
    trans_app: str,
    trans_name: str,
    origin_codec: str,
    out_codec: str,
    target_height_payload: int,
    ffmpeg_cmd_key: str,
):
    """处理播放 URL`ensure`转码`ready`。"""
    stream_id = f"{trans_app}/{trans_name}"
    if _playurl_is_transcode_online(trans_app, trans_name):
        _playurl_touch_transcode_manager(stream_id)
        return True, None

    src_url = g_zlm.get_rtspUrl(src_app, src_name)
    dst_url = g_zlm.get_rtmpUrl(trans_app, trans_name)
    tm = _playurl_get_transcode_manager_best_effort()

    if tm and not tm.can_start(dst_url):
        resp = _playurl_transcode_pending_response(
            msg="transcoding_not_ready",
            retry_after_ms=_playurl_retry_after_ms(tm, dst_url, 800),
            public_host=public_host,
            trans_app=trans_app,
            trans_name=trans_name,
            out_codec=out_codec,
            origin_codec=origin_codec,
            target_height=target_height_payload,
            ffmpeg_cmd_key=ffmpeg_cmd_key,
        )
        return False, resp

    key = g_zlm.addFFmpegSource(
        src_url=src_url,
        dst_url=dst_url,
        ffmpeg_cmd_key=ffmpeg_cmd_key,
        timeout_ms=8000,
        enable_hls=0,
        enable_mp4=0,
    )
    if tm and key:
        tm.register_stream(stream_id, key)

    # addFFmpegSource may fail (returns empty key). In this case we must not pretend it's ready.
    if not key:
        resp = _playurl_transcode_pending_response(
            msg="transcoding_start_failed",
            retry_after_ms=_playurl_retry_after_ms(tm, dst_url, 800),
            public_host=public_host,
            trans_app=trans_app,
            trans_name=trans_name,
            out_codec=out_codec,
            origin_codec=origin_codec,
            target_height=target_height_payload,
            ffmpeg_cmd_key=ffmpeg_cmd_key,
        )
        return False, resp

    if not _playurl_is_transcode_online(trans_app, trans_name):
        resp = _playurl_transcode_pending_response(
            msg="transcoding_not_ready",
            retry_after_ms=500,
            public_host=public_host,
            trans_app=trans_app,
            trans_name=trans_name,
            out_codec=out_codec,
            origin_codec=origin_codec,
            target_height=target_height_payload,
            ffmpeg_cmd_key=ffmpeg_cmd_key,
        )
        return False, resp

    return True, None


def _playurl_parse_int(value, default: int) -> int:
    """处理播放 URL`parse`整数值。"""
    try:
        return int(value)
    except Exception:
        return int(default)


def _playurl_normalize_prefer(value: str) -> str:
    """处理播放 URL归一化`prefer`。"""
    prefer = str(value or "compat").strip().lower()
    if prefer in ("compat", "raw", "hls", "hls_fmp4"):
        return prefer
    return "compat"


def _playurl_success(data: dict):
    """处理播放 URL成功状态。"""
    return f_responseJson({"code": 1000, "msg": "success", "data": data})


def _playurl_build_hls_response(*, prefer: str, app: str, name: str, origin_codec: str, public_host: str):
    """返回播放 URL构建`hls`响应。"""
    play_url = g_zlm.get_hlsFmp4Url(app, name, public_host) if prefer == "hls_fmp4" else g_zlm.get_hlsUrl(app, name, public_host)
    data = _playurl_make_data(
        url=play_url,
        codec=origin_codec or "",
        origin_codec=origin_codec or "",
        mode="hls",
        demux_type="hls",
        is_transcode=0,
        target_height=0,
        ffmpeg_cmd_key="",
        app=app,
        name=name,
        public_host=public_host,
    )
    return _playurl_success(data)


def _playurl_build_raw_response(*, app: str, name: str, origin_codec: str, public_host: str):
    """返回播放 URL构建`raw`响应。"""
    play_url = g_zlm.get_wsMp4Url(app, name, public_host) if origin_codec == "h265" else g_zlm.get_wsFlvUrl(app, name, public_host)
    data = _playurl_make_data(
        url=play_url,
        codec=origin_codec or "",
        origin_codec=origin_codec or "",
        mode="raw",
        demux_type=_playurl_infer_demux_type(play_url),
        is_transcode=0,
        target_height=0,
        ffmpeg_cmd_key="",
        app=app,
        name=name,
        public_host=public_host,
    )
    return _playurl_success(data)


def _playurl_build_compat_response(
    *,
    app: str,
    name: str,
    layout: int,
    quality: str,
    origin_codec: str,
    origin_height: int,
    public_host: str,
):
    """返回播放 URL构建`compat`响应。"""
    target_height = _playurl_target_height(layout, quality)

    need_codec_convert = origin_codec == "h265"
    need_downscale = bool(target_height and origin_height and origin_height > target_height)
    need_transcode = need_codec_convert or need_downscale

    if not need_transcode:
        play_url = g_zlm.get_wsFlvUrl(app, name, public_host)
        data = _playurl_make_data(
            url=play_url,
            codec=origin_codec or "",
            origin_codec=origin_codec or "",
            mode="compat",
            demux_type=_playurl_infer_demux_type(play_url),
            is_transcode=0,
            target_height=0,
            ffmpeg_cmd_key="",
            app=app,
            name=name,
            public_host=public_host,
        )
        return _playurl_success(data)

    # output is always H264 for browser compatibility
    out_codec = "h264"
    trans_app = "trans"
    trans_name = _playurl_transcode_stream_name(
        app,
        name,
        origin_height=origin_height,
        target_height=target_height,
        need_downscale=need_downscale,
    )
    target_height_payload = target_height if need_downscale else 0
    ffmpeg_cmd_key = _playurl_ffmpeg_cmd_key(target_height) if need_downscale and target_height else ""

    ready, pending_resp = _playurl_ensure_transcode_ready(
        src_app=app,
        src_name=name,
        public_host=public_host,
        trans_app=trans_app,
        trans_name=trans_name,
        origin_codec=origin_codec,
        out_codec=out_codec,
        target_height_payload=target_height_payload,
        ffmpeg_cmd_key=ffmpeg_cmd_key,
    )
    if not ready and pending_resp is not None:
        return pending_resp

    play_url = g_zlm.get_wsFlvUrl(trans_app, trans_name, public_host)
    data = _playurl_make_data(
        url=play_url,
        codec=out_codec or "",
        origin_codec=origin_codec or "",
        mode="compat",
        demux_type=_playurl_infer_demux_type(play_url),
        is_transcode=1,
        target_height=target_height_payload,
        ffmpeg_cmd_key=ffmpeg_cmd_key,
        app=trans_app,
        name=trans_name,
        public_host=public_host,
    )
    return _playurl_success(data)


def api_get_play_url(request):
    """
    根据布局与播放模式选择最优播放地址（需要时触发转码）

    Query:
      - app/name: 流标识
      - layout: 1/2/4/9/16（默认 1）
      - prefer: compat(默认)/raw
      - quality: auto(默认)/origin/1080/720/540/360/270

    返回：
      - code=1000: 直接播放
      - code=1001: 转码未就绪（前端按 retry_after_ms 重试）
    """
    params = f_parseGetParams(request)
    app = params.get("app", "").strip()
    name = params.get("name", "").strip()
    layout = _playurl_parse_int(params.get("layout", 1) or 1, 1)
    prefer = _playurl_normalize_prefer(params.get("prefer", "compat"))
    quality = str(params.get("quality", "auto") or "auto").strip().lower()

    if not app or not name:
        return f_responseJson({"code": 0, "msg": "参数错误"})

    public_host = get_public_host_for_urls(request)
    stream = GetStream(app=app, name=name, public_host=public_host)
    stream = _playurl_recover_stream_from_media_list(stream, app=app, name=name)
    if not stream.get("is_online"):
        return f_responseJson({"code": 0, "msg": "当前视频流不在线"})

    origin_codec = _playurl_normalize_codec(stream.get("video_codec_name", ""))
    try:
        origin_height = int(stream.get("video_height") or 0)
    except Exception:
        origin_height = 0

    # ========== HLS mode (HTTP m3u8) ==========
    if prefer in ("hls", "hls_fmp4"):
        return _playurl_build_hls_response(prefer=prefer, app=app, name=name, origin_codec=origin_codec, public_host=public_host)

    # ========== raw mode (no transcode) ==========
    if prefer == "raw":
        return _playurl_build_raw_response(app=app, name=name, origin_codec=origin_codec, public_host=public_host)

    return _playurl_build_compat_response(
        app=app,
        name=name,
        layout=layout,
        quality=quality,
        origin_codec=origin_codec,
        origin_height=origin_height,
        public_host=public_host,
    )
api_getPlayUrl = api_get_play_url  # pragma: no cover - compatibility alias

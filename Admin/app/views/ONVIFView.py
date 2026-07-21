import json
import os
from datetime import datetime

from django.shortcuts import render

from app.models import Stream
from app.utils.ONVIF import discover_onvif_devices, ONVIFClient, capture_device_snapshot, get_device_rtsp_urls

from app.views.ViewsBase import f_parsePostParams, f_responseJson, getUser, g_config, start_forward_for_stream


MSG_METHOD_NOT_SUPPORTED = "请求方法不支持"
MSG_IP_REQUIRED = "IP地址不能为空"


def _snapshot_image_url(rel_path: str) -> str:
    """返回 ONVIF 快照图片可访问 URL。"""
    path = str(rel_path or "").strip().lstrip("/")
    if not path:
        return ""
    base = str(getattr(g_config, "uploadDir_www", "/static/upload/") or "/static/upload/")
    return base.rstrip("/") + "/" + path


def onvif_discover(request):
    """ONVIF 设备搜索页面"""
    context = {}
    return render(request, 'app/onvif/discover.html', context)

def _build_onvif_stream_code(ip_address: str, profile_index: int) -> str:
    """构建`onvif`流编码。"""
    from app.utils.Security import validate_control_code

    ip_safe = str(ip_address or "").strip().replace(".", "_")
    idx = int(profile_index or 0)
    code = f"onvif_{ip_safe}_p{idx}"
    return validate_control_code(code)

def _inject_rtsp_credentials(rtsp_url: str, username: str, password: str) -> str:
    """处理`inject``rtsp``credentials`。
    
    Inject username/password into RTSP url (userinfo).
        - Quote special characters for safety.
        - Override existing userinfo if present.
    """
    import urllib.parse

    url = str(rtsp_url or "").strip()
    if not url:
        return ""
    user = str(username or "").strip()
    pwd = str(password or "").strip()
    if not user and not pwd:
        return url
    if not user and pwd:
        # Password without username is ambiguous and often breaks URL parsing.
        return url

    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme or "rtsp"
    if scheme.lower() != "rtsp":
        return url

    # Determine host/port from netloc (remove existing userinfo if present)
    netloc = parts.netloc or ""
    if "@" in netloc:
        netloc = netloc.split("@", 1)[1]

    user_enc = urllib.parse.quote(user, safe="")
    pwd_enc = urllib.parse.quote(pwd, safe="")
    userinfo = f"{user_enc}:{pwd_enc}" if pwd_enc else f"{user_enc}:"

    new_netloc = f"{userinfo}@{netloc}" if netloc else parts.netloc
    rebuilt = urllib.parse.urlunsplit((scheme, new_netloc, parts.path, parts.query, parts.fragment))
    return rebuilt

def _mask_rtsp_password(rtsp_url: str) -> str:
    """脱敏`rtsp``password`。"""
    import urllib.parse

    value = str(rtsp_url or "").strip()
    if not value:
        return ""
    parts = urllib.parse.urlsplit(value)
    scheme = (parts.scheme or "").lower()
    if scheme != "rtsp":
        return value

    netloc = parts.netloc or ""
    if "@" not in netloc:
        return value

    userinfo, hostport = netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return value

    user, _ = userinfo.split(":", 1)
    masked_netloc = f"{user}:***@{hostport}"
    return urllib.parse.urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))


def _sanitize_snapshot_filename_stem(value: str) -> str:
    """清洗快照`filename``stem`。"""
    import re

    raw = str(value or "").strip().replace(".", "_")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    if not stem:
        return "device"
    return stem[:120]


def _normalize_onvif_port(port_value) -> int:
    """执行归一化`onvif`端口。"""
    try:
        port = int(port_value or 80)
    except Exception:
        return 80
    if 1 <= port <= 65535:
        return port
    return 80


def _normalize_onvif_profiles(profiles):
    """执行归一化`onvif`profiles。"""
    if isinstance(profiles, list):
        return profiles
    if not isinstance(profiles, str):
        return []

    raw = profiles.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_onvif_import_request(params: dict) -> dict:
    """解析`onvif`导入请求。"""
    return {
        "ip_address": str(params.get("ip_address", "") or "").strip(),
        "port": _normalize_onvif_port(params.get("port", 80)),
        "username": str(params.get("username", "") or "").strip(),
        "password": str(params.get("password", "") or "").strip(),
        "skip_existing": str(params.get("skip_existing", "1") or "1").strip() != "0",
        "auto_start": str(params.get("auto_start_forward", "0") or "0").strip() == "1",
        "profiles": _normalize_onvif_profiles(params.get("profiles", [])),
    }


def _validate_onvif_import_request(import_request: dict) -> str:
    """校验`onvif`导入请求。"""
    if not import_request.get("ip_address"):
        return MSG_IP_REQUIRED
    if import_request.get("password") and not import_request.get("username"):
        return "仅填写密码无效，请同时填写用户名"
    profiles = import_request.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return "profiles 不能为空"
    return ""


def _build_onvif_rtsp_profiles(rtsp_items):
    """构建`onvif``rtsp`profiles。"""
    return [{"profile_name": name, "rtsp_url": url} for name, url in rtsp_items]


def _get_onvif_request_user_id(request) -> int:
    """获取`onvif`请求用户ID。"""
    try:
        return int(getUser(request).get("id") or 0)
    except Exception:
        return 0


def _get_onvif_profile_index(item) -> int:
    """获取`onvif`profile索引。"""
    try:
        return int((item or {}).get("profile_index", 0) or 0)
    except Exception:
        return 0


def _get_onvif_profile_name(item) -> str:
    """获取`onvif`profile名称。"""
    return str((item or {}).get("profile_name", "") or "").strip()


def _build_onvif_skip_result(stream_code: str, skip_existing: bool) -> dict:
    """构建`onvif``skip`结果。"""
    msg = "已存在，跳过" if skip_existing else "已存在（本版本不覆盖更新）"
    return {"stream_code": stream_code, "action": "skipped", "msg": msg}


def _resolve_onvif_profile_rtsp(profile_index: int, profile_name: str, rtsp_by_index) -> tuple[str, str]:
    """解析并返回`onvif`profile`rtsp`。"""
    if profile_index < 0 or profile_index >= len(rtsp_by_index):
        return "", profile_name

    item = rtsp_by_index[profile_index]
    rtsp_url = str(item.get("rtsp_url") or "").strip()
    resolved_name = profile_name or str(item.get("profile_name") or "").strip()
    return rtsp_url, resolved_name


def _build_onvif_stream_metadata(ip_address: str, port: int, profile_index: int, profile_name: str) -> tuple[str, str]:
    """构建`onvif`流元数据。"""
    nickname = f"{ip_address}-{profile_name}" if profile_name else ip_address
    remark = f"ONVIF import: {ip_address}:{port} profileIndex={profile_index} profile={profile_name}".strip()
    return nickname[:200], remark[:200]


def _create_onvif_stream(*, user_id: int, stream_code: str, rtsp_url: str, nickname: str, remark: str) -> Stream:
    """创建`onvif`流。"""
    stream = Stream()
    stream.user_id = user_id
    stream.sort = 0
    stream.code = stream_code
    stream.app = "live"
    stream.name = stream_code
    stream.pull_stream_url = rtsp_url[:300]
    stream.pull_stream_type = 1
    stream.nickname = nickname
    stream.remark = remark
    stream.forward_state = 0
    stream.create_time = datetime.now()
    stream.last_update_time = datetime.now()
    stream.state = 0
    stream.save()
    return stream


def _start_onvif_forward(stream: Stream, auto_start: bool) -> tuple[int, str]:
    """启动`onvif`转发。"""
    if not auto_start:
        return 0, ""
    ok, msg = start_forward_for_stream(stream)
    return (1 if ok else 0), str(msg or "")


def _import_onvif_profile(
    item,
    *,
    ip_address: str,
    port: int,
    username: str,
    password: str,
    skip_existing: bool,
    auto_start: bool,
    rtsp_by_index,
    user_id: int,
) -> tuple[str, dict]:
    """执行导入`onvif`profile。"""
    profile_index = _get_onvif_profile_index(item)
    profile_name = _get_onvif_profile_name(item)
    stream_code = _build_onvif_stream_code(ip_address, profile_index)

    if Stream.objects.filter(code=stream_code).exists():
        return "skipped", _build_onvif_skip_result(stream_code, skip_existing)

    rtsp_url, profile_name = _resolve_onvif_profile_rtsp(profile_index, profile_name, rtsp_by_index)
    if not rtsp_url:
        return "failed", {"stream_code": stream_code, "action": "failed", "msg": "无法获取该 profile 的 RTSP 地址"}

    rtsp_with_creds = _inject_rtsp_credentials(rtsp_url, username, password)
    nickname, remark = _build_onvif_stream_metadata(ip_address, port, profile_index, profile_name)
    stream = _create_onvif_stream(
        user_id=user_id,
        stream_code=stream_code,
        rtsp_url=rtsp_with_creds,
        nickname=nickname,
        remark=remark,
    )
    forward_state, forward_msg = _start_onvif_forward(stream, auto_start)
    return "created", {
        "stream_code": stream_code,
        "action": "created",
        "msg": forward_msg or "导入成功",
        "forward_state": forward_state,
        "rtsp_url_masked": _mask_rtsp_password(rtsp_with_creds),
    }


def _run_onvif_import_profiles(
    profiles,
    *,
    ip_address: str,
    port: int,
    username: str,
    password: str,
    skip_existing: bool,
    auto_start: bool,
    rtsp_by_index,
    user_id: int,
) -> dict:
    """执行`onvif`导入profiles。"""
    results = []
    created = 0
    skipped = 0
    failed = 0

    for item in profiles:
        action, result = _import_onvif_profile(
            item,
            ip_address=ip_address,
            port=port,
            username=username,
            password=password,
            skip_existing=skip_existing,
            auto_start=auto_start,
            rtsp_by_index=rtsp_by_index,
            user_id=user_id,
        )
        results.append(result)
        if action == "created":
            created += 1
        elif action == "skipped":
            skipped += 1
        else:
            failed += 1

    return {"results": results, "created": created, "skipped": skipped, "failed": failed}


def _build_onvif_import_message(created: int, skipped: int, failed: int) -> tuple[int, str]:
    """构建`onvif`导入`message`。"""
    if created > 0 or skipped > 0:
        return 1000, f"导入完成：新增{created}条，跳过{skipped}条，失败{failed}条"
    return 0, f"导入失败：失败{failed}条"


def api_onvif_discover(request):
    """API: ONVIF 设备搜索"""
    code = 0
    msg = "未知错误"
    data = []

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            timeout = int(params.get('timeout', 5))
            if timeout < 1:
                timeout = 5
            if timeout > 30:
                timeout = 30

            # 搜索设备
            devices = discover_onvif_devices(timeout)

            for device in devices:
                device_data = {
                    'name': device.name,
                    'ip_address': device.ip_address,
                    'port': device.port,
                    'manufacturer': device.manufacturer,
                    'model': device.model,
                    'hardware': device.hardware,
                    'location': device.location,
                    'xaddrs': device.xaddrs,
                    'scopes': device.scopes
                }
                data.append(device_data)

            code = 1000
            msg = f"搜索完成，发现 {len(devices)} 个设备"

        except Exception as e:
            msg = f"搜索失败：{str(e)}"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": code,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)

def api_onvif_import_streams(request):
    """
    API: 从 ONVIF profiles 批量导入为摄像头（Stream）
    - code 规则：onvif_<ip下划线>_p<profileIndex>
    - RTSP 持久化保存账号密码（URL 编码）
    - 可选：导入后自动开启转发
    """
    code = 0
    msg = "未知错误"
    results = []

    if request.method != "POST":
        return f_responseJson({"code": code, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        import_request = _parse_onvif_import_request(f_parsePostParams(request))
        error_msg = _validate_onvif_import_request(import_request)
        if error_msg:
            return f_responseJson({"code": code, "msg": error_msg})

        rtsp_by_index = _build_onvif_rtsp_profiles(
            get_device_rtsp_urls(
                import_request["ip_address"],
                import_request["port"],
                import_request["username"],
                import_request["password"],
            )
        )
        user_id = _get_onvif_request_user_id(request)
        summary = _run_onvif_import_profiles(
            import_request["profiles"],
            ip_address=import_request["ip_address"],
            port=import_request["port"],
            username=import_request["username"],
            password=import_request["password"],
            skip_existing=import_request["skip_existing"],
            auto_start=import_request["auto_start"],
            rtsp_by_index=rtsp_by_index,
            user_id=user_id,
        )
        results = summary["results"]
        code, msg = _build_onvif_import_message(summary["created"], summary["skipped"], summary["failed"])

    except Exception as e:
        msg = str(e)

    return f_responseJson({"code": code, "msg": msg, "results": results})


def _parse_onvif_device_info_params(request) -> dict:
    """Parse ONVIF device-info POST params."""
    params = f_parsePostParams(request)
    return {
        "ip_address": str(params.get('ip_address', '') or '').strip(),
        "port": int(params.get('port', 80)),
        "username": str(params.get('username', '') or '').strip(),
        "password": str(params.get('password', '') or '').strip(),
    }


def _onvif_rtsp_uri_by_profile_name(ip_address: str, port: int, username: str, password: str) -> dict:
    """Return RTSP URLs keyed by profile name, best-effort."""
    try:
        rtsp_items = get_device_rtsp_urls(ip_address, port, username, password)
    except Exception:
        return {}
    return {
        str(profile_name or "").strip(): str(rtsp_url or "").strip()
        for profile_name, rtsp_url in rtsp_items
        if str(profile_name or "").strip() and str(rtsp_url or "").strip()
    }


def _onvif_profile_payloads(profiles, rtsp_uri_by_profile_name: dict) -> list:
    """Serialize ONVIF profiles for the device-info response."""
    profile_list = []
    for profile in profiles:
        profile_name = str(getattr(profile, "name", "") or "").strip()
        profile_list.append(
            {
                'token': profile.token,
                'name': profile.name,
                'width': profile.width,
                'height': profile.height,
                'encoding': profile.encoding,
                'framerate': profile.framerate,
                'bitrate': profile.bitrate,
                'stream_uri': rtsp_uri_by_profile_name.get(profile_name, ""),
            }
        )
    return profile_list


def api_onvif_get_device_info(request):
    """API: 获取 ONVIF 设备信息"""
    code = 0
    msg = "未知错误"
    data = {}

    if request.method == 'POST':
        try:
            params = _parse_onvif_device_info_params(request)
            ip_address = params["ip_address"]
            port = params["port"]
            username = params["username"]
            password = params["password"]

            if not ip_address:
                msg = MSG_IP_REQUIRED
                return f_responseJson({"code": code, "msg": msg})

            # 创建客户端
            client = ONVIFClient(ip_address, port, username, password)

            # 获取设备信息
            device_info = client.get_device_information()
            if device_info:
                data['device_info'] = device_info
            else:
                data['device_info'] = None

            # 获取配置文件
            profiles = client.get_profiles()
            rtsp_uri_by_profile_name = _onvif_rtsp_uri_by_profile_name(ip_address, port, username, password)
            data['profiles'] = _onvif_profile_payloads(profiles, rtsp_uri_by_profile_name)

            code = 1000
            msg = "获取成功"

        except Exception as e:
            msg = f"获取失败：{str(e)}"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": code,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)


def api_onvif_get_rtsp_urls(request):
    """API: 获取 RTSP 地址"""
    code = 0
    msg = "未知错误"
    data = []

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            ip_address = params.get('ip_address', '').strip()
            port = int(params.get('port', 80))
            username = params.get('username', '').strip()
            password = params.get('password', '').strip()

            if not ip_address:
                msg = MSG_IP_REQUIRED
                return f_responseJson({"code": code, "msg": msg})

            # 获取 RTSP 地址
            rtsp_urls = get_device_rtsp_urls(ip_address, port, username, password)

            for profile_name, rtsp_url in rtsp_urls:
                data.append({
                    'profile_name': profile_name,
                    'rtsp_url': rtsp_url
                })

            code = 1000
            msg = "获取成功"

        except Exception as e:
            msg = f"获取失败：{str(e)}"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": code,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)


def api_onvif_capture_snapshot(request):
    """API: ONVIF 截图"""
    code = 0
    msg = "未知错误"
    data = {}

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            ip_address = params.get('ip_address', '').strip()
            port = int(params.get('port', 80))
            username = params.get('username', '').strip()
            password = params.get('password', '').strip()
            profile_index = int(params.get('profile_index', 0))

            if not ip_address:
                msg = MSG_IP_REQUIRED
                return f_responseJson({"code": code, "msg": msg})

            # 统一使用 Config.storageRootPath（可被 config.json 或环境变量覆盖）
            storage_root = getattr(g_config, "storageRootPath", "") or "upload"
            snapshot_root = getattr(g_config, "snapshotStoragePath", "") or os.path.join(storage_root, "snapshots")
            snapshot_dir = os.path.join(snapshot_root, 'onvif')
            os.makedirs(snapshot_dir, exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            filename = f"{_sanitize_snapshot_filename_stem(ip_address)}_{timestamp}.jpg"
            save_path = os.path.join(snapshot_dir, filename)

            # 截图
            if capture_device_snapshot(ip_address, save_path, port, username, password, profile_index):
                relative_path = os.path.join('snapshots', 'onvif', filename).replace('\\', '/')
                data['image_path'] = relative_path
                data['image_url'] = _snapshot_image_url(relative_path)

                code = 1000
                msg = "截图成功"
            else:
                msg = "截图失败"

        except Exception as e:
            msg = f"截图失败：{str(e)}"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    res = {
        "code": code,
        "msg": msg,
        "data": data
    }
    return f_responseJson(res)

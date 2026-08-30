from app.views.ViewsBase import f_parseGetParams, f_parsePostParams, f_responseJson, g_config
from app.models import AlarmSound
from django.shortcuts import render
from django.db import transaction
import logging
import os
import uuid
from app.utils.Utils import buildPageLabels
from app.utils.Security import resolve_under_base, validate_upload_rel_path

AUDIO_MIME_BY_EXT = {
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.m4a': 'audio/mp4',
    '.aac': 'audio/aac',
}

MSG_METHOD_NOT_SUPPORTED = "请求方法不支持"
MAX_SOUND_FILE_BYTES = 20 * 1024 * 1024
logger = logging.getLogger(__name__)


def _sound_upload_dir() -> str:
    """Return the mutable runtime directory used for alarm sound uploads."""
    upload_dir = str(getattr(g_config, "uploadDir", "") or "").strip()
    if not upload_dir:
        raise RuntimeError("alarm sound upload directory is not configured")
    return os.path.join(upload_dir, "sounds")


def _sound_url(sound_filename: str) -> str:
    prefix = str(getattr(g_config, "uploadDir_www", "/static/upload/") or "/static/upload/").strip()
    if not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}sounds/{sound_filename}"


def _resolve_sound_abs_path(file_path: str) -> str:
    """Resolve only managed sound URLs and reject absolute/traversal paths."""
    raw = str(file_path or "").strip()
    prefix = str(getattr(g_config, "uploadDir_www", "/static/upload/") or "/static/upload/").strip()
    if not prefix.endswith("/"):
        prefix += "/"
    if not raw.startswith(prefix):
        raise ValueError("alarm sound path is outside the managed upload prefix")
    rel_path = validate_upload_rel_path(raw[len(prefix):], required_prefix="sounds/")
    return resolve_under_base(str(getattr(g_config, "uploadDir", "") or ""), rel_path)


def _write_sound_file(sound_file, destination_path: str) -> None:
    """Write an upload atomically while enforcing the server-side size limit."""
    tmp_path = destination_path + ".part"
    written = 0
    try:
        with open(tmp_path, "xb") as destination:
            for chunk in sound_file.chunks():
                written += len(chunk)
                if written > MAX_SOUND_FILE_BYTES:
                    raise ValueError("音频文件过大，最大支持 20MB")
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(tmp_path, destination_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            logger.warning("failed to clean temporary alarm sound upload", exc_info=True)


def _infer_audio_mime_type(file_path):
    """返回推理音频`mime`类型。"""
    ext = os.path.splitext(str(file_path or ''))[1].lower()
    return AUDIO_MIME_BY_EXT.get(ext, 'audio/mpeg')


def _remove_sound_file_best_effort(file_path: str) -> None:
    """尽力处理`remove``sound`文件。"""
    if not file_path:
        return
    try:
        abs_path = _resolve_sound_abs_path(file_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        logger.warning("refused or failed to remove managed alarm sound file", exc_info=True)


def index(request):
    """报警声音管理列表"""
    context = {}

    params = f_parseGetParams(request)

    try:
        page = int(params.get('p', 1))
        if page < 1:
            page = 1
    except Exception:
        page = 1

    try:
        page_size = int(params.get('ps', 10))
        if page_size < 1:
            page_size = 10
    except Exception:
        page_size = 10

    queryset = AlarmSound.objects.filter(state__gte=0).order_by('-id')

    from django.core.paginator import Paginator
    paginator = Paginator(queryset, page_size)

    try:
        current_page = paginator.page(page)
    except Exception:
        current_page = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    data = list(current_page.object_list)
    for sound in data:
        sound.preview_audio_id = f"alarmSoundAudio{sound.id}"
        sound.preview_mime_type = _infer_audio_mime_type(sound.file_path)

    page_labels = buildPageLabels(page=page, page_num=paginator.num_pages)

    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": page_labels
    }

    context["data"] = data
    context["pageData"] = page_data
    return render(request, 'app/alarm_sound/index.html', context)


def api_upload(request):
    """上传报警声音"""
    code = 0
    msg = "未知错误"

    if request.method == 'POST':
        try:
            sound_file = request.FILES.get('sound_file')
            name = request.POST.get('name', '').strip()
            remark = request.POST.get('remark', '').strip()
            is_default = request.POST.get('is_default', '0') == '1'

            if not sound_file:
                msg = "请选择要上传的音频文件"
                return f_responseJson({"code": code, "msg": msg})

            if not name:
                name = os.path.splitext(sound_file.name)[0]

            if len(name) > 100:
                msg = "名称不能超过 100 个字符"
                return f_responseJson({"code": code, "msg": msg})
            if len(remark) > 200:
                msg = "备注不能超过 200 个字符"
                return f_responseJson({"code": code, "msg": msg})

            # 验证文件格式
            file_ext = os.path.splitext(sound_file.name)[1].lower()
            if file_ext not in ['.mp3', '.wav', '.ogg', '.m4a', '.aac']:
                msg = "不支持的音频格式，请上传 MP3/WAV/OGG/M4A/AAC 格式"
                return f_responseJson({"code": code, "msg": msg})
            if int(getattr(sound_file, "size", 0) or 0) > MAX_SOUND_FILE_BYTES:
                msg = "音频文件过大，最大支持 20MB"
                return f_responseJson({"code": code, "msg": msg})

            # 保存文件
            sound_filename = f"alarm_{uuid.uuid4().hex}{file_ext}"
            upload_dir = _sound_upload_dir()
            os.makedirs(upload_dir, mode=0o750, exist_ok=True)
            sound_path = os.path.join(upload_dir, sound_filename)
            _write_sound_file(sound_file, sound_path)

            file_url = _sound_url(sound_filename)

            try:
                with transaction.atomic():
                    # Serialize default selection against existing sound rows.
                    if is_default:
                        list(AlarmSound.objects.select_for_update().values_list("id", flat=True))
                        AlarmSound.objects.filter(is_default=True).update(is_default=False)

                    AlarmSound.objects.create(
                        name=name,
                        file_path=file_url,
                        duration=0,
                        is_default=is_default,
                        remark=remark,
                        state=1,
                    )
            except Exception:
                _remove_sound_file_best_effort(file_url)
                raise

            code = 1000
            msg = "上传成功"

        except ValueError:
            msg = "上传失败：文件不符合要求"
        except Exception:
            logger.exception("alarm sound upload failed")
            msg = "上传失败，请稍后重试"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    return f_responseJson({"code": code, "msg": msg})


def api_delete(request):
    """删除报警声音"""
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": MSG_METHOD_NOT_SUPPORTED})

    try:
        params = f_parsePostParams(request)
        sound_id = params.get('id')
        if not sound_id:
            return f_responseJson({"code": 0, "msg": "参数错误"})

        sound = AlarmSound.objects.filter(id=sound_id).first()
        if not sound:
            return f_responseJson({"code": 0, "msg": "该报警声音不存在"})

        _remove_sound_file_best_effort(sound.file_path)
        sound.delete()
        return f_responseJson({"code": 1000, "msg": "删除成功"})
    except Exception:
        logger.exception("alarm sound delete failed")
        return f_responseJson({"code": 0, "msg": "删除失败，请稍后重试"})


def api_set_default(request):
    """设置默认报警声音"""
    code = 0
    msg = "未知错误"

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            sound_id = params.get('id')

            if sound_id:
                sound = AlarmSound.objects.filter(id=sound_id).first()
                if sound:
                    # 取消其他默认设置
                    AlarmSound.objects.filter(is_default=True).update(is_default=False)
                    # 设置当前为默认
                    sound.is_default = True
                    sound.save()
                    code = 1000
                    msg = "设置成功"
                else:
                    msg = "该报警声音不存在"
            else:
                msg = "参数错误"

        except Exception:
            logger.exception("set default alarm sound failed")
            msg = "设置失败，请稍后重试"

    else:
        msg = MSG_METHOD_NOT_SUPPORTED

    return f_responseJson({"code": code, "msg": msg})
api_setDefault = api_set_default  # pragma: no cover - compatibility alias


def api_list(_request):
    """获取报警声音列表（供下拉选择使用）"""
    code = 1000
    msg = "success"
    data = []

    try:
        sounds = AlarmSound.objects.filter(state=1).order_by('-is_default', '-id')
        for sound in sounds:
            data.append({
                'id': sound.id,
                'name': sound.name,
                'file_path': sound.file_path,
                'is_default': sound.is_default
            })
    except Exception:
        logger.exception("list alarm sounds failed")
        code = 0
        msg = "获取报警声音列表失败"

    return f_responseJson({"code": code, "msg": msg, "data": data})

from app.views.ViewsBase import f_parseGetParams, f_parsePostParams, f_responseJson
from app.models import AlarmSound
from django.shortcuts import render
import os
import time
from app.utils.Utils import buildPageLabels

AUDIO_MIME_BY_EXT = {
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.m4a': 'audio/mp4',
    '.aac': 'audio/aac',
}

# 报警声音上传目录
UPLOAD_SOUND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'static', 'upload', 'sounds')
os.makedirs(UPLOAD_SOUND_DIR, exist_ok=True)

MSG_METHOD_NOT_SUPPORTED = "请求方法不支持"


def _infer_audio_mime_type(file_path):
    """返回推理音频`mime`类型。"""
    ext = os.path.splitext(str(file_path or ''))[1].lower()
    return AUDIO_MIME_BY_EXT.get(ext, 'audio/mpeg')


def _remove_sound_file_best_effort(file_path: str) -> None:
    """尽力处理`remove``sound`文件。"""
    if not file_path:
        return
    try:
        abs_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            str(file_path).lstrip('/'),
        )
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        return


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

            # 验证文件格式
            file_ext = os.path.splitext(sound_file.name)[1].lower()
            if file_ext not in ['.mp3', '.wav', '.ogg', '.m4a', '.aac']:
                msg = "不支持的音频格式，请上传 MP3/WAV/OGG/M4A/AAC 格式"
                return f_responseJson({"code": code, "msg": msg})

            # 保存文件
            sound_filename = f"alarm_{int(time.time())}{file_ext}"
            sound_path = os.path.join(UPLOAD_SOUND_DIR, sound_filename)
            with open(sound_path, 'wb+') as destination:
                for chunk in sound_file.chunks():
                    destination.write(chunk)

            file_url = f"/static/upload/sounds/{sound_filename}"

            # 如果设为默认，取消其他默认设置
            if is_default:
                AlarmSound.objects.filter(is_default=True).update(is_default=False)

            # 创建记录
            obj = AlarmSound()
            obj.name = name
            obj.file_path = file_url
            obj.duration = 0  # 可以通过音频库获取时长
            obj.is_default = is_default
            obj.remark = remark
            obj.state = 1
            obj.save()

            code = 1000
            msg = "上传成功"

        except Exception as e:
            msg = f"上传失败: {str(e)}"

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
    except Exception as e:
        return f_responseJson({"code": 0, "msg": f"删除失败: {str(e)}"})


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

        except Exception as e:
            msg = f"设置失败: {str(e)}"

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
    except Exception as e:
        code = 0
        msg = str(e)

    return f_responseJson({"code": code, "msg": msg, "data": data})

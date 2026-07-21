from app.views.ViewsBase import f_parseGetParams
from app.models import ControlLog
from django.shortcuts import render
from django.core.paginator import Paginator
from django.http import HttpResponse
from app.utils.Utils import buildPageLabels
from datetime import datetime
import json
import csv
import logging
from io import StringIO
import platform


DATETIME_PARSE_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
logger = logging.getLogger(__name__)


def _control_log_int(value, default: int, *, min_value=None, max_value=None) -> int:
    """处理控制`log`整数值。"""
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    if min_value is not None and parsed < min_value:
        return int(min_value)
    if max_value is not None and parsed > max_value:
        return int(max_value)
    return int(parsed)


def _control_log_parse_datetime(value: str):
    """处理控制`log``parse``datetime`。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in DATETIME_PARSE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
        except Exception:
            return None
    return None


def _control_log_filters(params: dict) -> dict:
    """处理控制`log``filters`。"""
    return {
        "control_code": str(params.get("control_code", "")).strip(),
        "action": str(params.get("action", "")).strip(),
        "result_code": str(params.get("result_code", "")).strip(),
        "start_time": str(params.get("start_time", "")).strip(),
        "end_time": str(params.get("end_time", "")).strip(),
    }


def _control_log_filtered_queryset(filters: dict):
    """返回控制`log``filtered`查询集。"""
    queryset = ControlLog.objects.all().order_by("-id")
    control_code = str(filters.get("control_code") or "").strip()
    action = str(filters.get("action") or "").strip()
    result_code = str(filters.get("result_code") or "").strip()
    start_time = str(filters.get("start_time") or "").strip()
    end_time = str(filters.get("end_time") or "").strip()

    if control_code:
        queryset = queryset.filter(control_code__icontains=control_code)
    if action:
        queryset = queryset.filter(action=action)
    if result_code:
        try:
            queryset = queryset.filter(result_code=int(result_code))
        except Exception:
            logger.debug("ignore invalid control log result_code filter: %s", result_code, exc_info=True)

    start_dt = _control_log_parse_datetime(start_time) if start_time else None
    if start_dt:
        queryset = queryset.filter(create_time__gte=start_dt)

    end_dt = _control_log_parse_datetime(end_time) if end_time else None
    if end_dt:
        queryset = queryset.filter(create_time__lte=end_dt)

    return queryset


def _control_log_paginate(paginator: Paginator, page: int):
    """处理控制`log`分页。"""
    try:
        return paginator.page(page), int(page)
    except Exception:
        last_page = max(1, int(getattr(paginator, "num_pages", 1) or 1))
        return paginator.page(last_page), last_page


def index(request):
    """渲染默认页面。"""
    params = f_parseGetParams(request)
    page = _control_log_int(params.get("p", 1), 1, min_value=1)
    page_size = _control_log_int(params.get("ps", 20), 20, min_value=1, max_value=100)
    filters = _control_log_filters(params)
    queryset = _control_log_filtered_queryset(filters)
    paginator = Paginator(queryset, page_size)
    current_page, page = _control_log_paginate(paginator, page)

    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": paginator.num_pages,
        "count": paginator.count,
        "pageLabels": buildPageLabels(page=page, page_num=paginator.num_pages)
    }

    return render(
        request,
        "app/control/logs.html",
        {
            "data": current_page.object_list,
            "pageData": page_data,
            "filters": filters,
            "actions": [
                {"code": "", "name": "全部"},
                {"code": "start", "name": "启动"},
                {"code": "stop", "name": "停止"},
                {"code": "batch_start", "name": "批量启动"},
                {"code": "batch_stop", "name": "批量停止"},
                {"code": "copy", "name": "复制"},
                {"code": "delete", "name": "删除"},
            ],
        },
    )


def _control_log_export_csv(logs, *, timestamp: str) -> HttpResponse:
    """处理控制`log``export`CSV。"""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "布控编号", "动作", "结果码", "结果信息", "操作人", "详情", "创建时间"])

    for log in logs:
        writer.writerow(
            [
                log.id,
                log.control_code,
                log.action,
                log.result_code,
                log.result_msg,
                log.operator,
                log.detail,
                log.create_time.strftime("%Y-%m-%d %H:%M:%S") if log.create_time else "",
            ]
        )

    # 添加 BOM 以支持中文
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    filename = f"control_logs_{timestamp}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _control_log_export_system_info() -> dict:
    # v4.717: 导出日志附带系统内核与处理器信息（便于离线排障/工单）
    """返回控制`log``export`系统信息。"""
    from app.utils.OSSystem import OSSystem

    try:
        osys = OSSystem()
        return {
            "node": osys.get_machine_node(),
            "os_release": osys.get_machine_os_release(),
            "kernel_release": platform.release(),
            "kernel_version": platform.version(),
            "cpu": osys.get_machine_cpu(),
        }
    except Exception:
        return {
            "kernel_release": platform.release(),
            "kernel_version": platform.version(),
            "cpu": "",
        }


def _control_log_export_json(logs, *, timestamp: str, filters: dict) -> HttpResponse:
    """返回控制`log``export`JSON。"""
    export_data = {
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filter": {
            "control_code": str(filters.get("control_code") or "").strip(),
            "action": str(filters.get("action") or "").strip(),
            "result_code": str(filters.get("result_code") or "").strip(),
            "start_time": str(filters.get("start_time") or "").strip(),
            "end_time": str(filters.get("end_time") or "").strip(),
        },
        "total_count": logs.count() if hasattr(logs, "count") else len(logs),
        "logs": [
            {
                "id": log.id,
                "control_code": log.control_code,
                "action": log.action,
                "result_code": log.result_code,
                "result_msg": log.result_msg,
                "operator": log.operator,
                "detail": log.detail,
                "create_time": log.create_time.strftime("%Y-%m-%d %H:%M:%S") if log.create_time else "",
            }
            for log in logs
        ],
        "system": _control_log_export_system_info(),
    }

    response = HttpResponse(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    filename = f"control_logs_{timestamp}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def api_export_logs(request):
    """API: 导出布控日志"""
    params = f_parseGetParams(request)

    export_format = str(params.get("format", "json")).strip().lower()

    filters = _control_log_filters(params)
    queryset = _control_log_filtered_queryset(filters)

    # 限制最大导出数量
    MAX_EXPORT_COUNT = 10000
    logs = queryset[:MAX_EXPORT_COUNT]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if export_format == "csv":
        return _control_log_export_csv(logs, timestamp=timestamp)

    return _control_log_export_json(logs, timestamp=timestamp, filters=filters)

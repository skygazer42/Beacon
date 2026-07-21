from typing import Dict, Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from app.models import AlgorithmModel, AlgorithmModelVersion
from app.utils.Security import validate_control_code


ALGORITHM_VERSION_SNAPSHOT_FIELDS = (
    "algorithm_type",
    "algorithm_subtype",
    "basic_source",
    "api_url",
    "model_path",
    "dll_path",
    "builtin_behavior",
    "support_direct_api",
    "behavior_api_version",
    "object_count",
    "object_str",
    "max_control_count",
    "license_package",
    "model_precision",
    "model_concurrency",
    "input_width",
    "input_height",
    "nms_thresh",
    "conf_thresh",
)


def build_algorithm_snapshot(algorithm: AlgorithmModel) -> Dict[str, object]:
    """构建算法快照。"""
    snapshot = {}
    for field in ALGORITHM_VERSION_SNAPSHOT_FIELDS:
        snapshot[field] = getattr(algorithm, field, None)
    return snapshot


def snapshots_equal(a: Dict[str, object], b: Dict[str, object]) -> bool:
    """判断`snapshots`是否相等。"""
    for field in ALGORITHM_VERSION_SNAPSHOT_FIELDS:
        if a.get(field) != b.get(field):
            return False
    return True


def _next_version_no(algorithm: AlgorithmModel) -> int:
    """处理下一个版本`no`。"""
    max_no = (
        AlgorithmModelVersion.objects.filter(algorithm=algorithm).aggregate(max_no=Max("version_no")).get("max_no")
        or 0
    )
    try:
        max_no = int(max_no or 0)
    except Exception:
        max_no = 0
    return max_no + 1


def create_algorithm_version(
    algorithm: AlgorithmModel,
    *,
    snapshot: Optional[Dict[str, object]] = None,
    note: str = "",
    make_current: bool = True,
) -> AlgorithmModelVersion:
    """创建算法版本。"""
    data = dict(snapshot or build_algorithm_snapshot(algorithm))
    version_no = _next_version_no(algorithm)
    now = timezone.now()

    if make_current:
        AlgorithmModelVersion.objects.filter(algorithm=algorithm, is_current=True).update(is_current=False)

    version = AlgorithmModelVersion.objects.create(
        algorithm=algorithm,
        version_no=version_no,
        version_name=f"v{version_no}",
        note=str(note or "").strip(),
        is_current=bool(make_current),
        activated_at=now if make_current else None,
        **data,
    )
    return version


def ensure_algorithm_version_registry(algorithm: AlgorithmModel, *, note: str = "bootstrap") -> AlgorithmModelVersion:
    """处理`ensure`算法版本`registry`。"""
    current = AlgorithmModelVersion.objects.filter(algorithm=algorithm, is_current=True).order_by("-version_no", "-id").first()
    if current:
        return current

    latest = AlgorithmModelVersion.objects.filter(algorithm=algorithm).order_by("-version_no", "-id").first()
    if latest:
        AlgorithmModelVersion.objects.filter(algorithm=algorithm).update(is_current=False)
        latest.is_current = True
        if not latest.activated_at:
            latest.activated_at = timezone.now()
        latest.save(update_fields=["is_current", "activated_at"])
        return latest

    return create_algorithm_version(algorithm, note=note, make_current=True)


def normalize_gray_control_codes(value: str) -> str:
    """执行归一化`gray`控制编码列表。"""
    seen = set()
    items = []
    raw = str(value or "")
    for chunk in raw.replace("\n", ",").replace("\r", ",").split(","):
        token = str(chunk or "").strip()
        if not token:
            continue
        token = validate_control_code(token)
        if token in seen:
            continue
        seen.add(token)
        items.append(token)
    return ",".join(items)


def gray_control_code_matches(gray_control_codes: str, control_code: str) -> bool:
    """判断`gray`控制编码是否匹配。"""
    current = str(control_code or "").strip()
    if not current:
        return False
    normalized = normalize_gray_control_codes(gray_control_codes)
    if not normalized:
        return False
    return current in normalized.split(",")


@transaction.atomic
def activate_algorithm_version(version: AlgorithmModelVersion) -> AlgorithmModelVersion:
    """处理`activate`算法版本。"""
    algorithm = version.algorithm
    update_fields = []
    for field in ALGORITHM_VERSION_SNAPSHOT_FIELDS:
        setattr(algorithm, field, getattr(version, field))
        update_fields.append(field)
    algorithm.save(update_fields=update_fields)

    AlgorithmModelVersion.objects.filter(algorithm=algorithm).update(is_current=False)
    version.is_current = True
    version.is_gray = False
    version.gray_control_codes = ""
    version.activated_at = timezone.now()
    version.save(update_fields=["is_current", "is_gray", "gray_control_codes", "activated_at"])
    return version


def rollback_algorithm_version(algorithm: AlgorithmModel) -> Optional[AlgorithmModelVersion]:
    """处理`rollback`算法版本。"""
    ensure_algorithm_version_registry(algorithm, note="rollback-bootstrap")
    current = AlgorithmModelVersion.objects.filter(algorithm=algorithm, is_current=True).order_by("-version_no", "-id").first()
    candidates = AlgorithmModelVersion.objects.filter(algorithm=algorithm, activated_at__isnull=False)
    if current:
        candidates = candidates.exclude(id=current.id)
    candidate = candidates.order_by("-activated_at", "-version_no", "-id").first()
    if not candidate:
        return None
    return activate_algorithm_version(candidate)


@transaction.atomic
def set_algorithm_gray_version(
    algorithm: AlgorithmModel,
    *,
    version: Optional[AlgorithmModelVersion],
    gray_control_codes: str,
) -> Optional[AlgorithmModelVersion]:
    """设置算法`gray`版本。"""
    normalized = normalize_gray_control_codes(gray_control_codes)
    if not version or not normalized:
        AlgorithmModelVersion.objects.filter(algorithm=algorithm).update(is_gray=False, gray_control_codes="")
        return None
    if version.algorithm_id != algorithm.id:
        raise ValueError("version does not belong to algorithm")
    if version.is_current:
        raise ValueError("current version cannot be gray version")

    AlgorithmModelVersion.objects.filter(algorithm=algorithm).update(is_gray=False, gray_control_codes="")

    version.is_gray = True
    version.gray_control_codes = normalized
    version.save(update_fields=["is_gray", "gray_control_codes"])
    return version


def version_to_snapshot(version: AlgorithmModelVersion) -> Dict[str, object]:
    """处理版本`to`快照。"""
    snapshot = {}
    for field in ALGORITHM_VERSION_SNAPSHOT_FIELDS:
        snapshot[field] = getattr(version, field, None)
    return snapshot


def resolve_algorithm_runtime_config(algorithm: AlgorithmModel, *, control_code: str = "") -> Dict[str, object]:
    """解析并返回算法运行时配置。"""
    ensure_algorithm_version_registry(algorithm, note="runtime-bootstrap")

    gray_version = AlgorithmModelVersion.objects.filter(algorithm=algorithm, is_gray=True).order_by("-version_no", "-id").first()
    if gray_version and gray_control_code_matches(getattr(gray_version, "gray_control_codes", ""), control_code):
        data = version_to_snapshot(gray_version)
        data["version_id"] = gray_version.id
        data["version_name"] = gray_version.version_name
        data["runtime_source"] = "gray"
        return data

    current = AlgorithmModelVersion.objects.filter(algorithm=algorithm, is_current=True).order_by("-version_no", "-id").first()
    if current:
        data = version_to_snapshot(current)
        data["version_id"] = current.id
        data["version_name"] = current.version_name
        data["runtime_source"] = "current"
        return data

    data = build_algorithm_snapshot(algorithm)
    data["version_id"] = 0
    data["version_name"] = ""
    data["runtime_source"] = "live"
    return data

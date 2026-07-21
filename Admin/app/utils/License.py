import logging
import os
import subprocess
import hashlib
import uuid
import shlex
from app.utils.OSSystem import OSSystem
from app.utils.LicenseManager import extract_license_runtime_policy_from_json



logger = logging.getLogger(__name__)
def _normalize_stream_code(stream_code, control_code=""):
    """执行归一化流编码。"""
    value = str(stream_code or "").strip()
    if value:
        return value
    return str(control_code or "").strip()


def _count_active_streams(qs):
    """统计活动流列表。"""
    keys = set()
    try:
        rows = qs.values_list("node_id", "stream_code", "control_code")
    except Exception:
        return 0

    for node_id, stream_code, control_code in rows:
        node = str(node_id or "").strip()
        stream = _normalize_stream_code(stream_code, control_code)
        if not node or not stream:
            continue
        keys.add((node, stream))
    return len(keys)


class License:
    """
    简单的授权管理：
    - machine：校验机器码是否匹配 licenseKey
    - dongle：调用外部检测命令或探测加密锁文件
    """

    def __init__(self, config):
        """处理`init`。"""
        self.config = config
        self.os = OSSystem()
        self._machine_code = None
        self._machine_code_v1 = None
        self._machine_code_v2 = None

    def _get_mac(self):
        """获取`mac`。"""
        try:
            mac = uuid.getnode()
            # If uuid.getnode() cannot find a MAC, it may return a random value
            # with the multicast bit set. Treat it as unreliable for licensing.
            first_octet = (mac >> 40) & 0xFF
            if (first_octet & 0x01) == 0x01:
                return ""
            if mac == 0:
                return ""
            return "%012x" % mac
        except Exception:
            return ""

    def _call_os(self, *names):
        """处理`call``os`。"""
        for name in names:
            method = getattr(self.os, name, None)
            if callable(method):
                return method()
        return ""

    def get_machine_code_v1(self):
        """
        历史机器码（v1）：兼容旧授权码生成逻辑。
        注意：v1 会尽量避免使用“随机 MAC”，否则会导致机器码随重启变化。
        """
        if self._machine_code_v1:
            return self._machine_code_v1
        parts = [
            self._call_os("getMachineNode", "get_machine_node"),
            self._call_os("getMachineCpu", "get_machine_cpu"),
            self._get_mac(),
        ]
        raw = "|".join([str(p or "") for p in parts])
        self._machine_code_v1 = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
        return self._machine_code_v1

    def get_machine_code_v2(self):
        """
        更稳定的机器码（v2）：优先使用 OS 级稳定 ID（Windows MachineGuid / Linux machine-id / macOS IOPlatformUUID）。
        """
        if self._machine_code_v2:
            return self._machine_code_v2

        stable = ""
        try:
            stable = str(self._call_os("getMachineStableId", "get_machine_stable_id") or "").strip()
        except Exception:
            stable = ""

        if stable:
            parts = [
                self._call_os("getSystemName", "get_system_name"),
                stable,
                self._call_os("getMachineCpu", "get_machine_cpu"),
            ]
            raw = "|".join([str(p or "") for p in parts])
            self._machine_code_v2 = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
            return self._machine_code_v2

        # Fallback: if stable id is not available, fall back to v1.
        self._machine_code_v2 = self.get_machine_code_v1()
        return self._machine_code_v2

    def get_machine_code(self):
        # Backward compatible: return v2 by default (more stable), but v1 is still available.
        """获取`machine`编码。"""
        if self._machine_code:
            return self._machine_code
        self._machine_code = self.get_machine_code_v2()
        return self._machine_code

    def _normalize_dongle_cmd_args(self, cmd) -> list:
        """执行归一化`dongle``cmd``args`。"""
        cmd_args = []
        if isinstance(cmd, (list, tuple)):
            for token in cmd:
                part = str(token or "").strip()
                if part:
                    cmd_args.append(part)
            return cmd_args

        cmd_text = str(cmd or "").strip()
        if not cmd_text:
            return cmd_args
        try:
            return shlex.split(cmd_text, posix=(os.name != "nt"))
        except Exception:
            return cmd_args

    def _run_dongle_cmd_best_effort(self, cmd_args) -> bool:
        """尽力执行`dongle``cmd`。"""
        try:
            ret = subprocess.run(cmd_args, shell=False, timeout=5)
            return ret.returncode == 0
        except Exception:
            return False

    def _check_dongle(self):
        """
        dongle 检测：优先执行配置的检测命令；失败时回退检查 sentinel 文件
        """
        cmd = getattr(self.config, "licenseDongleCmd", "")
        sentinel = getattr(self.config, "licenseDongleFile", "license.dongle")
        cmd_args = self._normalize_dongle_cmd_args(cmd)
        if cmd_args and self._run_dongle_cmd_best_effort(cmd_args):
            return True
        return bool(sentinel and os.path.isfile(sentinel))

    def _check_machine_license(self):
        """检查`machine`授权。"""
        key = str(getattr(self.config, "licenseKey", "") or "").strip()
        if not key:
            return False

        codes = []
        try:
            codes.append(self.get_machine_code_v2())
        except Exception:
            logger.debug("suppressed exception in app/utils/License.py:171", exc_info=True)
        try:
            codes.append(self.get_machine_code_v1())
        except Exception:
            logger.debug("suppressed exception in app/utils/License.py:175", exc_info=True)
        # Unique, keep order
        uniq = []
        for c in codes:
            if c and c not in uniq:
                uniq.append(c)

        # Accept raw machine code or its SHA-256 hash.
        for machine_code in uniq:
            if key == machine_code:
                return True
            if key == hashlib.sha256(machine_code.encode("utf-8")).hexdigest():
                return True
        return False

    def _check_pool_license(self):
        """
        pool/manager 授权：
        - 以 Admin 内 LicenseState 为准（license 导入后持久化）
        - 路数/节点的强制门禁在 Analyzer，这里主要用于展示与健康检查
        """
        from django.utils import timezone
        from app.models import LicenseState, LicenseLease

        try:
            state = LicenseState.objects.order_by("-update_time", "-id").first()
            if not state or not bool(getattr(state, "valid", False)):
                return False, {"reason": "license_invalid"}

            now = timezone.now()
            if getattr(state, "not_after", None) and now > state.not_after:
                return False, {"reason": "license_expired", "not_after": state.not_after}

            active_qs = LicenseLease.objects.filter(released_at__isnull=True, expires_at__gt=now)
            usage = {
                "active_controls": active_qs.count(),
                "active_streams": _count_active_streams(active_qs),
                "active_nodes": active_qs.values("node_id").distinct().count(),
            }
            info = {
                "license_id": getattr(state, "license_id", "") or "",
                "customer": getattr(state, "customer", "") or "",
                "cluster_id": getattr(state, "cluster_id", "") or "",
                "not_before": getattr(state, "not_before", None),
                "not_after": getattr(state, "not_after", None),
                "limits": {
                    "max_active_controls": int(getattr(state, "max_active_controls", 0) or 0),
                    "max_nodes": int(getattr(state, "max_nodes", 0) or 0),
                },
                "packages_json": getattr(state, "packages_json", "") or "[]",
                "usage": usage,
            }
            runtime_policy = extract_license_runtime_policy_from_json(getattr(state, "license_json", "") or "")
            info["edition"] = str(runtime_policy.get("edition", "") or "")
            info["thread_priority_policy"] = runtime_policy.get("thread_priority_policy") if isinstance(runtime_policy, dict) else {}
            return True, info
        except Exception as e:
            return False, {"reason": str(e)}

    def check(self):
        """检查相关数据。"""
        ltype = (getattr(self.config, "licenseType", "community") or "community").lower()
        extra = {}
        if ltype == "community":
            ok = True
            extra = {"edition": "community"}
        elif ltype in ("pool", "manager"):
            ok, extra = self._check_pool_license()
        elif ltype == "dongle":
            ok = self._check_dongle()
        else:
            ok = self._check_machine_license()
        return {
            "ok": bool(ok),
            "type": ltype,
            "machine_code": self.get_machine_code(),
            "machine_code_v1": self.get_machine_code_v1(),
            "machine_code_v2": self.get_machine_code_v2(),
            "extra": extra,
        }

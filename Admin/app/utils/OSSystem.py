import psutil
import shutil
from datetime import datetime
import platform
import subprocess
import re


class OSSystem():
    def __init__(self):
        """处理`init`。"""
        self.__system_name = platform.system() # 操作系统
        self.__machine_node = str(platform.node()) # 机器名称

    def _spend_date_format(self,spend_date):# type <class 'datetime.timedelta'>
        """处理`spend`日期`format`。"""
        spend_day = spend_date.days  # 已运行的天数 int
        spend_seconds = spend_date.seconds  # 已运行的秒数 int
        spend_hour = int(spend_seconds / 60 / 60)  # 已运行小时 int
        spend_seconds -= spend_hour * 60 * 60  # 已运行的秒数 int
        spend_minute = int(spend_seconds / 60)  # 已运行的分钟 int
        spend_seconds -= spend_minute * 60  # 已运行的秒数 int
        spend_date_str = "%d天%d小时%d分钟%d秒" % (spend_day, spend_hour, spend_minute, spend_seconds)

        return spend_date_str

    def _byte_format(self,byte_count, suffix="B"):
        """处理`byte``format`。
        
        Scale bytes to its proper format
                e.g:
                    1253656 => '1.20MB'
                    1253656678 => '1.17GB'
        """
        factor = 1024
        for unit in ["", "K", "M", "G", "T", "P"]:
            if byte_count < factor:
                return f"{byte_count:.2f}{unit}{suffix}"
            byte_count /= factor

    def get_os_info(self):

        # 获取系统 cpu 比例 start
        """获取`os`信息。"""
        os_cpu_used = psutil.cpu_percent()
        os_cpu_total_core = psutil.cpu_count(logical=True) # 逻辑核心数量
        os_cpu_used_rate = round(os_cpu_used / 100, 3)  # <class 'float'> 0.125
        # 获取系统 cpu 比例 end

        # 获取系统内存比例 start
        os_virtual_mem = psutil.virtual_memory()
        os_virtual_mem_total = os_virtual_mem.total
        os_virtual_mem_used_rate = os_virtual_mem.used / os_virtual_mem.total
        os_virtual_mem_used_rate = round(os_virtual_mem_used_rate, 3)  # <class 'float'> 0.635
        # 获取系统内存比例 end

        # 获取系统磁盘比例 start
        os_disk_total = 0
        os_disk_used = 0
        os_disk_partitions = psutil.disk_partitions()
        for partition in os_disk_partitions:
            try:
                partition_usage = psutil.disk_usage(partition.mountpoint)
                os_disk_total += partition_usage.total
                os_disk_used += partition_usage.used
            except PermissionError:
                continue
        os_disk_used_rate = os_disk_used / os_disk_total
        os_disk_used_rate = round(os_disk_used_rate, 3)  # 当前系统磁盘占用比例
        # 获取系统磁盘比例 end

        # 获取系统开机时间 start
        os_boot_time = psutil.boot_time()  # <class 'float'> 1651904713.9067075
        os_boot_date = datetime.fromtimestamp(os_boot_time)  # <class 'datetime.datetime'>
        os_run_date = datetime.now() - os_boot_date  # <class 'datetime.timedelta'>
        os_run_date_str = self._spend_date_format(os_run_date)
        # 获取系统开机时间 end

        try:
            os_net_io = psutil.net_io_counters() or None
            os_net_bytes_sent = int(getattr(os_net_io, "bytes_sent", 0) or 0)
            os_net_bytes_recv = int(getattr(os_net_io, "bytes_recv", 0) or 0)
        except Exception:
            os_net_bytes_sent = 0
            os_net_bytes_recv = 0

        os_info = {
            "machine_node": str(platform.node()),
            "system_name": self.get_system_name(),
            "os_cpu_used_rate": os_cpu_used_rate, # cpu总占比
            "os_virtual_mem_used_rate": os_virtual_mem_used_rate, # 内存总占比
            "os_disk_used_rate": os_disk_used_rate,
            "os_net_bytes_sent": os_net_bytes_sent,
            "os_net_bytes_recv": os_net_bytes_recv,

            "os_cpu_used_rate_str": str(round(os_cpu_used_rate*100,1))+"% ("+str(os_cpu_total_core)+"核)",
            "os_virtual_mem_used_rate_str": str(round(os_virtual_mem_used_rate*100,1))+"% ("+str(self._byte_format(os_virtual_mem_total))+")",
            "os_disk_used_rate_str": str(round(os_disk_used_rate*100,1))+"% ("+str(self._byte_format(os_disk_total))+")",

            "os_run_date_str": os_run_date_str
        }

        return os_info

    def get_system_name(self):
        """获取系统名称。"""
        return self.__system_name

    def get_machine_node(self):
        """获取`machine``node`。"""
        try:
            node = str(self.__machine_node or "").strip()
            if not node:
                node = platform.node()
            return node or "unknown-node"
        except Exception:
            return "unknown-node"

    def _strip_release_value(self, raw_value: str) -> str:
        """返回`strip``release`值。"""
        value = str(raw_value or "").strip()
        while len(value) >= 2 and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))):
            value = value[1:-1].strip()
        return value.replace('\\"', '"').replace("\\'", "'").strip()

    def _parse_os_release_fields(self, text: str) -> dict:
        """解析`os``release`字段。"""
        fields = {}
        for raw_line in str(text or "").splitlines():
            line = str(raw_line or "").strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = str(key or "").strip()
            if not key:
                continue
            fields[key] = self._strip_release_value(value)
        return fields

    def _read_linux_lsb_release_description(self) -> str:
        """读取Linux`lsb``release``description`。"""
        try:
            with open("/etc/lsb-release", "r", encoding="utf-8") as f:
                fields = self._parse_os_release_fields(f.read())
        except Exception:
            return ""

        for key in ("DISTRIB_DESCRIPTION", "DISTRIB_ID"):
            value = str(fields.get(key) or "").strip()
            if value:
                return value
        return ""

    def _looks_generic_linux_release(self, value: str) -> bool:
        """处理外观`generic`Linux`release`。"""
        normalized = str(value or "").strip().lower()
        return normalized in {"", "linux", "custom linux", "gnu/linux"}

    def get_machine_os_release(self):
        """获取`machine``os``release`。"""
        system = self.get_system_name()
        if system == "Windows":
            return "Windows"
        if system == "Darwin":
            # macOS: keep it stable enough and avoid shell errors in minimal environments.
            try:
                return platform.platform() or "Darwin"
            except Exception:
                return "Darwin"

        # Linux: /etc/os-release
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                fields = self._parse_os_release_fields(f.read())
            release = ""
            for key in ("PRETTY_NAME", "NAME", "ID"):
                value = str(fields.get(key) or "").strip()
                if value:
                    release = value
                    break

            if release and not self._looks_generic_linux_release(release):
                return release

            lsb_release = self._read_linux_lsb_release_description()
            if lsb_release:
                return lsb_release

            return release or "Linux"
        except Exception:
            lsb_release = self._read_linux_lsb_release_description()
            return lsb_release or "Linux"

    def _parse_named_command_output(self, raw, header: str) -> str:
        """解析`named``command``output`。"""
        text = str(raw.decode("utf-8", errors="ignore") or "").replace("\r", "\n")
        lines = [line.strip() for line in text.split("\n") if str(line or "").strip()]
        for line in lines:
            if line.lower() == str(header or "").strip().lower():
                continue
            return line
        return ""

    def _read_linux_cpuinfo_model_name(self) -> str:
        """读取Linux`cpuinfo`模型名称。"""
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                text = str(f.read() or "")
        except Exception:
            return ""

        for line in text.splitlines():
            if not line.lower().startswith("model name"):
                continue
            parts = line.split(":", 1)
            if len(parts) == 2 and str(parts[1]).strip():
                return str(parts[1]).strip()
        return ""

    def _read_lscpu_model_name(self) -> str:
        """读取`lscpu`模型名称。"""
        try:
            if not shutil.which("lscpu"):
                return ""
            out = subprocess.check_output(["lscpu"], timeout=2)
        except Exception:
            return ""

        text = out.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            if not line.lower().startswith("model name"):
                continue
            parts = line.split(":", 1)
            if len(parts) == 2 and str(parts[1]).strip():
                return str(parts[1]).strip()
        return ""

    def _get_windows_cpu_name(self) -> str:
        """获取`windows``cpu`名称。"""
        try:
            raw = subprocess.check_output(["wmic", "cpu", "get", "Name"], timeout=3)
            machine_cpu = self._parse_named_command_output(raw, "Name")
            return machine_cpu or "run error"
        except Exception:
            return "run error"

    def _get_macos_cpu_name(self) -> str:
        """获取macOS`cpu`名称。"""
        try:
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=2)
            machine_cpu = out.decode("utf-8", errors="ignore").strip()
        except Exception:
            try:
                machine_cpu = str(platform.processor() or "").strip()
            except Exception:
                machine_cpu = ""
        return machine_cpu or "unknown-cpu"

    def _get_linux_cpu_name(self) -> str:
        """获取Linux`cpu`名称。"""
        machine_cpu = self._read_linux_cpuinfo_model_name()
        if not machine_cpu:
            machine_cpu = self._read_lscpu_model_name()
        return machine_cpu.strip() or "unknown-cpu"

    def get_machine_cpu(self):
        """获取`machine``cpu`。"""
        system = self.get_system_name()
        if system == "Windows":
            return self._get_windows_cpu_name()
        if system == "Darwin":
            return self._get_macos_cpu_name()
        return self._get_linux_cpu_name()

    def get_machine_stable_id(self):
        """
        获取更稳定的机器标识（用于 machine_code_v2），避免 MAC 随机导致授权码变化。
        - Windows: MachineGuid
        - Linux: /etc/machine-id
        - macOS: IOPlatformUUID
        """
        system = self.get_system_name()
        if system == "Windows":
            stable = self._get_windows_machine_guid() or self._get_windows_wmic_uuid()
            return str(stable or "").strip()

        if system == "Darwin":
            return str(self._get_macos_ioplatform_uuid() or "").strip()

        # Linux / other
        return str(self._get_linux_machine_id() or "").strip()

    def _get_windows_machine_guid(self) -> str:
        """获取`windows``machine``guid`。"""
        if self.get_system_name() != "Windows":
            return ""
        try:
            import winreg
        except ImportError:
            return ""

        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\Microsoft\\Cryptography")
            value, _typ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value or "").strip()
        except Exception:
            return ""

    def _get_windows_wmic_uuid(self) -> str:
        # Fallback: wmic csproduct UUID
        """获取`windows``wmic``uuid`。"""
        try:
            out = subprocess.check_output(["wmic", "csproduct", "get", "UUID"], timeout=3)
        except Exception:
            return ""

        text = out.decode("utf-8", errors="ignore")
        text = text.replace("\r", "\n")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        for line in lines:
            if line.lower() == "uuid":
                continue
            if re.match(r"^[0-9a-fA-F\\-]{8,}$", line):
                return line
        return ""

    def _get_macos_ioplatform_uuid(self) -> str:
        # ioreg -rd1 -c IOPlatformExpertDevice
        """获取macOS`ioplatform``uuid`。"""
        try:
            out = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], timeout=3)
        except Exception:
            return ""

        text = out.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            if "IOPlatformUUID" not in line:
                continue
            # Parse platform UUID from ioreg output line.
            m = re.search(r"\"IOPlatformUUID\"\\s*=\\s*\"([^\"]+)\"", line)
            if m:
                return str(m.group(1)).strip()
        return ""

    def _get_linux_machine_id(self) -> str:
        """获取Linux`machine`ID。"""
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    stable = str(f.read() or "").strip()
                if stable:
                    return stable
            except Exception:
                continue
        return ""

    def _format_percent(self, ratio):
        """处理`format``percent`。"""
        try:
            value = float(ratio) * 100.0
        except Exception:
            return "-"
        if value < 0:
            value = 0.0
        return f"{value:.1f}%"

    def _format_uptime_short(self, total_seconds):
        """处理`format``uptime``short`。"""
        try:
            total = int(total_seconds or 0)
        except Exception:
            total = 0
        if total < 0:
            total = 0

        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _seconds = divmod(rem, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0 or days > 0:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)

    def get_diagnostics_summary(self):
        """获取`diagnostics``summary`。"""
        info = self.get_os_info()

        try:
            boot_time = float(psutil.boot_time())
            uptime_seconds = max(0, int((datetime.now() - datetime.fromtimestamp(boot_time)).total_seconds()))
        except Exception:
            uptime_seconds = 0

        os_release = str(self.get_machine_os_release() or "").strip()
        if "\n" in os_release:
            os_release = next((line.strip() for line in os_release.splitlines() if line.strip()), os_release)

        summary = {
            "host": str(self.get_machine_node() or "-").strip() or "-",
            "system_name": str(self.get_system_name() or "-").strip() or "-",
            "os_release": os_release or "-",
            "cpu": str(self.get_machine_cpu() or "-").strip() or "-",
            "cpu_usage": self._format_percent(info.get("os_cpu_used_rate")),
            "memory_usage": self._format_percent(info.get("os_virtual_mem_used_rate")),
            "disk_usage": self._format_percent(info.get("os_disk_used_rate")),
            "uptime": self._format_uptime_short(uptime_seconds),
            "summary_ok": True,
        }
        return summary


# Backward-compatible camelCase aliases used by older callers and tests.
OSSystem.getSystemName = OSSystem.get_system_name
OSSystem.getMachineNode = OSSystem.get_machine_node
OSSystem.getMachineCpu = OSSystem.get_machine_cpu
OSSystem.getMachineStableId = OSSystem.get_machine_stable_id
OSSystem.getDiagnosticsSummary = OSSystem.get_diagnostics_summary

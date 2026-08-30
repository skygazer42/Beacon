import logging
import requests
from urllib.parse import quote

from app.utils.OutboundUrl import canonicalize_outbound_http_url, validate_outbound_http_url
from app.utils.Security import validate_upload_rel_path



logger = logging.getLogger(__name__)
class CloudEdgeClientError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = int(status_code or 0)


class CloudEdgeClient:
    def __init__(self, *, base_url: str, open_api_token: str, timeout_seconds: int | float = 5):
        """处理`init`。"""
        raw_base_url = str(base_url or "").strip()
        raw_token = str(open_api_token or "").strip()
        if not raw_base_url:
            raise ValueError("base_url is required")
        if not raw_token:
            raise ValueError("open_api_token is required")

        # Constructor validation is deliberately DNS-free so object creation
        # has no network side effect. _url() performs the full DNS/IP policy
        # check immediately before each real request.
        self.base_url = canonicalize_outbound_http_url(raw_base_url).rstrip("/")
        self.open_api_token = raw_token
        self.timeout_seconds = float(timeout_seconds or 5)
        if self.timeout_seconds <= 0:
            self.timeout_seconds = 5.0

    def _headers(self):
        """处理请求头。"""
        return {"X-Beacon-Token": self.open_api_token}

    def _url(self, path: str):
        """返回请求 URL。"""
        base_url = validate_outbound_http_url(
            self.base_url,
            allowed_hosts_env="BEACON_CLOUD_EDGE_ALLOWED_HOSTS",
            allowed_cidrs_env="BEACON_CLOUD_EDGE_ALLOWED_CIDRS",
        ).rstrip("/")
        relative = str(path or "").lstrip("/")
        if not relative or "://" in relative or any(ch in relative for ch in ("\\", "\x00", "\r", "\n")):
            raise CloudEdgeClientError("edge request path is invalid")
        return base_url + "/" + relative

    def _parse_response(self, response):
        """解析响应。"""
        try:
            body = response.json()
        except Exception:
            body = None

        if response.status_code != 200:
            raise CloudEdgeClientError(
                f"edge request failed (HTTP {int(response.status_code or 0)})",
                status_code=response.status_code,
            )

        if not isinstance(body, dict):
            raise CloudEdgeClientError("edge response is not a JSON object")

        try:
            code = int(body.get("code") or 0)
        except (TypeError, ValueError) as e:
            raise CloudEdgeClientError("edge response code is invalid") from e
        if code != 1000:
            raise CloudEdgeClientError("edge request failed")

        return body

    def get_json(self, path: str, *, params=None):
        """获取JSON。"""
        try:
            response = requests.get(
                self._url(path),
                headers=self._headers(),
                params=params,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise CloudEdgeClientError("edge service is unavailable") from exc
        return self._parse_response(response)

    def post_json(self, path: str, payload: dict):
        """发送 JSON 请求。"""
        try:
            response = requests.post(
                self._url(path),
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise CloudEdgeClientError("edge service is unavailable") from exc
        return self._parse_response(response)

    def list_streams(self):
        """处理列表流列表。"""
        body = self.get_json("/open/getAllStreamData")
        return body.get("data") or []

    def get_stream(self, code: str):
        """获取流。"""
        body = self.get_json("/stream/openGet", params={"code": str(code or "").strip()})
        return body.get("data") or {}

    def edit_stream(self, payload: dict):
        """处理编辑流。"""
        body = self.post_json("/stream/openEdit", payload or {})
        return body.get("data") or {}

    def list_algorithm_flows(self):
        """处理列表算法`flows`。"""
        body = self.get_json("/open/getAllAlgroithmFlowData")
        return body.get("data") or []

    def list_core_processes(self):
        """处理列表核心`processes`。"""
        return self.get_json("/open/getAllCoreProcessData")

    def get_ops_health(self):
        """获取运维健康检查。"""
        try:
            body = self.get_json("/open/ops/health")
        except CloudEdgeClientError:
            body = self.get_json("/healthz")
        data = body.get("data") or {}
        return data if isinstance(data, dict) else {}

    def list_recording_files(self, stream_code: str, *, page: int = 1, page_size: int = 50):
        """处理列表录制`files`。"""
        payload = {
            "streamCode": str(stream_code or "").strip(),
            "page": int(page or 1),
            "pageSize": int(page_size or 50),
        }
        return self.post_json("/open/recording/file/list", payload)

    def get_recording_play_url(self, rel_path: str):
        """获取录制播放URL。"""
        body = self.post_json("/open/recording/file/playUrl", {"relPath": str(rel_path or "").strip()})
        return body.get("data") or {}

    def stream_file(self, rel_path: str):
        """流式获取边缘文件内容。"""
        try:
            normalized_rel_path = validate_upload_rel_path(rel_path)
        except ValueError as exc:
            raise CloudEdgeClientError("edge file path is invalid") from exc
        safe_rel_path = quote(normalized_rel_path, safe="/")
        try:
            response = requests.get(
                self._url(f"/open/fileService/{safe_rel_path}"),
                headers=self._headers(),
                timeout=self.timeout_seconds,
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise CloudEdgeClientError("edge service is unavailable") from exc

        if response.status_code == 200:
            return response

        try:
            response.close()
        except Exception:
            logger.debug("suppressed exception in app/utils/CloudEdgeClient.py:163", exc_info=True)
        raise CloudEdgeClientError(
            f"edge request failed (HTTP {int(response.status_code or 0)})",
            status_code=response.status_code,
        )

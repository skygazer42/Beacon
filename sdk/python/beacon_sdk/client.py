import time


class BeaconApiError(RuntimeError):
    def __init__(self, message, *, code=None, payload=None):
        super().__init__(str(message or "Beacon API request failed"))
        self.code = code
        self.payload = payload


class BeaconClient:
    def __init__(self, base_url="http://localhost:9991", *, timeout=10.0, session=None, open_api_token="", cloud_edge_token=""):
        self.base_url = str(base_url or "http://localhost:9991").rstrip("/")
        self.timeout = float(timeout or 10.0)
        self.session = session if session is not None else self._create_default_session()
        self.open_api_token = str(open_api_token or "").strip()
        self.cloud_edge_token = str(cloud_edge_token or "").strip()

    def _create_default_session(self):
        import requests

        return requests.Session()

    def _parse_response(self, response):
        try:
            payload = response.json()
        except Exception as exc:
            raise BeaconApiError("invalid JSON response", payload=None) from exc

        code = payload.get("code")
        if code != 1000:
            raise BeaconApiError(payload.get("msg") or "request failed", code=code, payload=payload)
        return payload

    def _get(self, path):
        response = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
        return self._parse_response(response)

    def _get_with_params(self, path, *, params=None, headers=None):
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers or {},
            timeout=self.timeout,
        )
        return self._parse_response(response)

    def _get_raw(self, path, *, params=None, headers=None):
        return self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers or {},
            timeout=self.timeout,
        )

    def _post_form(self, path, data):
        response = self.session.post(f"{self.base_url}{path}", data=data, timeout=self.timeout)
        return self._parse_response(response)

    def _post_json(self, path, payload):
        response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        return self._parse_response(response)

    def _post_open_json(self, path, payload):
        headers = {}
        if self.open_api_token:
            headers["X-Beacon-Token"] = self.open_api_token
        response = self.session.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        return self._parse_response(response)

    def _post_cloud_json(self, path, payload):
        headers = {}
        if self.cloud_edge_token:
            headers["Authorization"] = f"Bearer {self.cloud_edge_token}"
        response = self.session.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        return self._parse_response(response)

    def _post_open_files(self, path, files):
        headers = {}
        if self.open_api_token:
            headers["X-Beacon-Token"] = self.open_api_token
        response = self.session.post(
            f"{self.base_url}{path}",
            files=files,
            headers=headers,
            timeout=self.timeout,
        )
        return self._parse_response(response)

    def _post_open_data(self, path, payload):
        return self._post_open_json(path, payload).get("data")

    def _post_cloud_data(self, path, payload):
        return self._post_cloud_json(path, payload).get("data")

    def _open_headers(self):
        headers = {}
        if self.open_api_token:
            headers["X-Beacon-Token"] = self.open_api_token
        return headers

    def _get_open_data(self, path, *, params=None):
        payload = self._get_with_params(path, params=params, headers=self._open_headers())
        return payload.get("data")

    def _get_open_payload(self, path, *, params=None):
        return self._get_with_params(path, params=params, headers=self._open_headers())

    def login(self, username, password, *, verify_code=None):
        payload = {
            "username": str(username or ""),
            "password": str(password or ""),
        }
        if verify_code is not None and str(verify_code or "").strip():
            payload["verify_code"] = str(verify_code or "").strip()
        return self._post_form("/login", payload)

    def get_controls(self):
        payload = self._get("/developer/getStreamInfo")
        return payload.get("data") or []

    def get_stream_info(self):
        return self.get_controls()

    def get_algorithms(self):
        payload = self._get("/developer/getAlgorithmInfo")
        return payload.get("data") or []

    def get_algorithm_info(self):
        return self.get_algorithms()

    def report_detection(
        self,
        *,
        control_code,
        detections,
        frame_index=0,
        timestamp=None,
        trigger_alarm=False,
        image_base64="",
    ):
        if timestamp is None:
            timestamp = int(time.time())
        payload = {
            "control_code": str(control_code or ""),
            "frame_index": int(frame_index or 0),
            "timestamp": timestamp,
            "detections": list(detections or []),
            "trigger_alarm": bool(trigger_alarm),
        }
        if image_base64:
            payload["image_base64"] = str(image_base64 or "")
        return self._post_json("/developer/algorithmCallback", payload)

    def upload_alarm(self, **payload):
        return self._post_open_json("/open/alarm/upload", dict(payload or {}))

    def check_version(self, **params):
        payload = self._get_with_params("/open/checkVersion", params=dict(params or {}), headers={})
        return payload.get("data")

    def get_license_info(self):
        return self._get_open_data("/open/license/info")

    def get_license_usage(self):
        return self._get_open_data("/open/license/usage")

    def get_control_data(self, *, code=None):
        params = {"code": str(code)} if code is not None and str(code).strip() else None
        data = self._get_open_data("/open/getControlData", params=params)
        return data or []

    def get_stream_data(self, *, code=None):
        params = {"code": str(code)} if code is not None and str(code).strip() else None
        data = self._get_open_data("/open/getStreamData", params=params)
        return data or []

    def get_platform_basic_info(self):
        return self._get_open_data("/open/platform/basicInfo")

    def get_platform_storage_info(self):
        return self._get_open_data("/open/platform/storageInfo")

    def acquire_license_lease(
        self,
        *,
        node_id,
        control_code,
        algorithm_code,
        stream_code=None,
        ttl_seconds=None,
    ):
        payload = {
            "node_id": str(node_id or ""),
            "control_code": str(control_code or ""),
            "algorithm_code": str(algorithm_code or ""),
        }
        if stream_code is not None and str(stream_code).strip():
            payload["stream_code"] = str(stream_code).strip()
        if ttl_seconds is not None:
            payload["ttl_seconds"] = int(ttl_seconds)
        data = self._post_open_json("/open/license/lease/acquire", payload)
        return data.get("data")

    def renew_license_lease(self, lease_id, *, ttl_seconds=None):
        payload = {"lease_id": str(lease_id or "")}
        if ttl_seconds is not None:
            payload["ttl_seconds"] = int(ttl_seconds)
        data = self._post_open_json("/open/license/lease/renew", payload)
        return data.get("data")

    def release_license_lease(self, lease_id):
        payload = {"lease_id": str(lease_id or "")}
        return self._post_open_json("/open/license/lease/release", payload)

    def add_recording_plan(self, **payload):
        return self._post_open_data("/open/recordingPlan/add", dict(payload or {}))

    def list_recording_plans(self, **payload):
        return self._post_open_data("/open/recordingPlan/list", dict(payload or {})) or []

    def edit_recording_plan(self, **payload):
        return self._post_open_data("/open/recordingPlan/edit", dict(payload or {}))

    def delete_recording_plan(self, code):
        return self._post_open_data("/open/recordingPlan/delete", {"code": str(code or "")})

    def add_task_plan(self, **payload):
        return self._post_open_data("/open/taskPlan/add", dict(payload or {}))

    def list_task_plans(self, **payload):
        return self._post_open_data("/open/taskPlan/list", dict(payload or {})) or []

    def edit_task_plan(self, **payload):
        return self._post_open_data("/open/taskPlan/edit", dict(payload or {}))

    def delete_task_plan(self, code):
        return self._post_open_data("/open/taskPlan/delete", {"code": str(code or "")})

    def list_recording_files(self, **payload):
        return self._post_open_data("/open/recording/file/list", dict(payload or {})) or []

    def get_recording_file_play_url(self, **payload):
        return self._post_open_data("/open/recording/file/playUrl", dict(payload or {}))

    def start_recording(self, **payload):
        return self._post_open_data("/open/recording/startRecording", dict(payload or {}))

    def stop_recording(self, **payload):
        return self._post_open_data("/open/recording/stopRecording", dict(payload or {}))

    def capture_snapshot(self, **payload):
        return self._post_open_data("/open/recording/captureSnapshot", dict(payload or {}))

    def list_faces(self):
        return self._post_open_data("/open/face/list", {})

    def add_face(self, **payload):
        return self._post_open_data("/open/face/add", dict(payload or {}))

    def delete_face(self, face_id):
        return self._post_open_data("/open/face/delete", {"id": str(face_id or "")})

    def search_face(self, **payload):
        return self._post_open_data("/open/face/search", dict(payload or {}))

    def enable_face_search(self):
        return self._post_open_data("/open/face/enable", {})

    def disable_face_search(self):
        return self._post_open_data("/open/face/disable", {})

    def cloud_presign_image(self, **payload):
        return self._post_cloud_data("/open/cloud/v1/presign/image", dict(payload or {}))

    def cloud_ingest_alarm_created(self, **payload):
        return self._post_cloud_json("/open/cloud/v1/events/alarm-created", dict(payload or {}))

    def ops_cleanup(self, **payload):
        return self._post_open_data("/open/ops/cleanup", dict(payload or {}))

    def ops_outbox_replay(self, **payload):
        return self._post_open_data("/open/ops/outbox/replay", dict(payload or {}))

    def ops_set_logging_level(self, **payload):
        return self._post_open_data("/open/ops/logging/level", dict(payload or {}))

    def ops_health(self):
        return self._get_open_data("/open/ops/health")

    def ops_ready(self):
        return self._get_open_data("/open/ops/ready")

    def ops_metrics(self):
        response = self._get_raw("/open/ops/metrics", headers=self._open_headers())
        return getattr(response, "text", "")

    def ops_audit_export(self, *, format="csv"):
        response = self._get_raw("/open/ops/audit/export", params={"format": str(format or "csv")}, headers=self._open_headers())
        return getattr(response, "content", b"")

    def ops_diagnostics_export(self, **params):
        response = self._get_raw("/open/ops/diagnostics/export", params=dict(params or {}) or None, headers=self._open_headers())
        return getattr(response, "content", b"")

    def ops_upgrade_list(self, *, only_compatible=False):
        params = {"only_compatible": "1"} if only_compatible else None
        return self._get_open_data("/open/ops/upgrade/list", params=params) or []

    def ops_upgrade_validate(self, package_id):
        return self._get_open_data("/open/ops/upgrade/validate", params={"package_id": str(package_id or "")})

    def ops_upgrade_apply(self, **payload):
        return self._post_open_data("/open/ops/upgrade/apply", dict(payload or {}))

    def ops_upgrade_rollback(self):
        return self._post_open_data("/open/ops/upgrade/rollback", {})

    def ops_upgrade_upload(self, file_name, file_bytes, *, content_type="application/zip"):
        files = {
            "file": (str(file_name or "package.zip"), file_bytes, str(content_type or "application/zip")),
        }
        return self._post_open_files("/open/ops/upgrade/upload", files).get("data")

    def image_detect(self, **payload):
        return self._post_open_data("/open/algorithm/imageDetect", dict(payload or {}))

    def audio_detect(self, **payload):
        return self._post_open_data("/open/algorithm/audioDetect", dict(payload or {}))

    def discover(self):
        return self._get_open_payload("/open/discover").get("info") or {}

    def get_all_stream_data(self):
        return self._get_open_data("/open/getAllStreamData") or []

    def get_all_algorithm_flow_data(self):
        return self._get_open_data("/open/getAllAlgroithmFlowData") or []

    def get_all_core_process_data(self):
        payload = self._get_open_payload("/open/getAllCoreProcessData")
        return {"data": payload.get("data") or [], "info": payload.get("info") or {}}

    def get_all_core_process_data2(self):
        payload = self._get_open_payload("/open/getAllCoreProcessData2")
        return payload.get("info") or {}

    def restart_software(self):
        return self._post_open_json("/open/platform/restartSoftware", {})

    def restart_system(self):
        return self._post_open_json("/open/platform/restartSystem", {})

    def download_file(self, rel_path):
        from urllib.parse import quote

        safe_rel = quote(str(rel_path or "").strip(), safe="/")
        response = self._get_raw(f"/open/fileService/{safe_rel}", headers=self._open_headers())
        return getattr(response, "content", b"")

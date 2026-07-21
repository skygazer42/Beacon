export class BeaconApiError extends Error {
  constructor(message, { code = null, payload = null } = {}) {
    super(String(message || "Beacon API request failed"));
    this.name = "BeaconApiError";
    this.code = code;
    this.payload = payload;
  }
}

function trimTrailingSlashes(value) {
  let text = String(value || "");
  while (text.endsWith("/")) {
    text = text.slice(0, -1);
  }
  return text;
}

export class BeaconClient {
  constructor(
    baseUrl = "http://localhost:9991",
    { fetchImpl = globalThis.fetch, credentials = "include", openApiToken = "", cloudEdgeToken = "" } = {},
  ) {
    this.baseUrl = trimTrailingSlashes(baseUrl || "http://localhost:9991");
    this.fetchImpl = fetchImpl;
    this.credentials = credentials;
    this.openApiToken = String(openApiToken || "").trim();
    this.cloudEdgeToken = String(cloudEdgeToken || "").trim();
    this.cookieHeader = "";
    if (typeof this.fetchImpl !== "function") {
      throw new BeaconApiError("fetch implementation is required");
    }
  }

  _mergeHeaders(headers = {}) {
    const merged = { ...headers };
    if (this.cookieHeader) {
      merged.cookie = this.cookieHeader;
    }
    return merged;
  }

  _updateCookieHeader(response) {
    if (!response?.headers) return;

    let rawCookies = [];
    if (typeof response.headers.getSetCookie === "function") {
      try {
        rawCookies = response.headers.getSetCookie() || [];
      } catch {
        rawCookies = [];
      }
    }

    if ((!rawCookies || rawCookies.length === 0) && typeof response.headers.get === "function") {
      const single = response.headers.get("set-cookie");
      if (single) {
        rawCookies = [single];
      }
    }

    const normalized = [];
    for (const item of rawCookies || []) {
      const cookie = String(item || "").split(";", 1)[0].trim();
      if (cookie) {
        normalized.push(cookie);
      }
    }

    if (normalized.length > 0) {
      this.cookieHeader = normalized.join("; ");
    }
  }

  async _parseResponse(response) {
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new BeaconApiError("invalid JSON response");
    }

    const code = payload?.code;
    if (code !== 1000) {
      throw new BeaconApiError(payload?.msg || "request failed", { code, payload });
    }
    return payload;
  }

  _buildUrl(path, query = undefined) {
    if (!query || typeof query !== "object") {
      return `${this.baseUrl}${path}`;
    }
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      const text = String(value);
      if (!text.trim()) continue;
      params.set(key, text);
    }
    const queryString = params.toString();
    const querySuffix = queryString ? `?${queryString}` : "";
    return `${this.baseUrl}${path}${querySuffix}`;
  }

  _openHeaders() {
    return this.openApiToken ? { "x-beacon-token": this.openApiToken } : {};
  }

  _cloudHeaders() {
    return this.cloudEdgeToken ? { authorization: `Bearer ${this.cloudEdgeToken}` } : {};
  }

  async _request(method, path, { headers = {}, body, query } = {}) {
    const options = {
      method,
      headers: this._mergeHeaders(headers),
      credentials: this.credentials,
    };
    if (body !== undefined) {
      options.body = body;
    }
    const response = await this.fetchImpl(this._buildUrl(path, query), options);
    this._updateCookieHeader(response);
    return this._parseResponse(response);
  }

  async _requestRaw(method, path, { headers = {}, body, query } = {}) {
    const options = {
      method,
      headers: this._mergeHeaders(headers),
      credentials: this.credentials,
    };
    if (body !== undefined) {
      options.body = body;
    }
    const response = await this.fetchImpl(this._buildUrl(path, query), options);
    this._updateCookieHeader(response);
    return response;
  }

  async _getData(path, { headers = {}, query } = {}) {
    const payload = await this._request("GET", path, { headers, query });
    return payload?.data;
  }

  async _postData(path, payload = {}, { headers = {} } = {}) {
    const body = await this._request("POST", path, {
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(payload || {}),
    });
    return body?.data;
  }

  async login(username, password, { verifyCode } = {}) {
    const payload = new URLSearchParams();
    payload.set("username", String(username || ""));
    payload.set("password", String(password || ""));
    if (verifyCode !== undefined && String(verifyCode || "").trim()) {
      payload.set("verify_code", String(verifyCode || "").trim());
    }
    return this._request("POST", "/login", {
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: payload.toString(),
    });
  }

  async getControls() {
    const payload = await this._request("GET", "/developer/getStreamInfo");
    return payload?.data || [];
  }

  async getStreamInfo() {
    return this.getControls();
  }

  async getAlgorithms() {
    const payload = await this._request("GET", "/developer/getAlgorithmInfo");
    return payload?.data || [];
  }

  async getAlgorithmInfo() {
    return this.getAlgorithms();
  }

  async reportDetection({
    controlCode,
    detections,
    frameIndex = 0,
    timestamp = Math.floor(Date.now() / 1000),
    triggerAlarm = false,
    imageBase64 = "",
  }) {
    const payload = {
      control_code: String(controlCode || ""),
      frame_index: Number(frameIndex || 0),
      timestamp,
      detections: Array.isArray(detections) ? detections : [],
      trigger_alarm: Boolean(triggerAlarm),
    };
    if (imageBase64) {
      payload.image_base64 = String(imageBase64);
    }
    return this._request("POST", "/developer/algorithmCallback", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async uploadAlarm(payload = {}) {
    const headers = { "content-type": "application/json", ...this._openHeaders() };
    const keyMap = {
      controlCode: "control_code",
      imagePath: "image_path",
      videoPath: "video_path",
      imageBase64: "image_base64",
      videoBase64: "video_base64",
      imageExt: "image_ext",
      videoExt: "video_ext",
      alarmType: "alarm_type",
      alarmLevel: "alarm_level",
      algorithmCode: "algorithm_code",
      objectCode: "object_code",
      recognitionRegion: "recognition_region",
      regionIndex: "region_index",
      classThresh: "class_thresh",
      overlapThresh: "overlap_thresh",
      minInterval: "min_interval",
      streamCode: "stream_code",
      streamApp: "stream_app",
      streamName: "stream_name",
      streamUrl: "stream_url",
      extraImages: "extra_images",
    };
    const bodyPayload = {};
    for (const [key, value] of Object.entries(payload || {})) {
      const targetKey = keyMap[key] || key;
      bodyPayload[targetKey] = value;
    }
    return this._request("POST", "/open/alarm/upload", {
      headers,
      body: JSON.stringify(bodyPayload),
    });
  }

  async checkVersion(params = {}) {
    return this._getData("/open/checkVersion", { headers: this._openHeaders(), query: params });
  }

  async getLicenseInfo() {
    return this._getData("/open/license/info", { headers: this._openHeaders() });
  }

  async getLicenseUsage() {
    return this._getData("/open/license/usage", { headers: this._openHeaders() });
  }

  async getControlData({ code } = {}) {
    return (await this._getData("/open/getControlData", {
      headers: this._openHeaders(),
      query: code ? { code } : undefined,
    })) || [];
  }

  async getStreamData({ code } = {}) {
    return (await this._getData("/open/getStreamData", {
      headers: this._openHeaders(),
      query: code ? { code } : undefined,
    })) || [];
  }

  async getPlatformBasicInfo() {
    return this._getData("/open/platform/basicInfo", { headers: this._openHeaders() });
  }

  async getPlatformStorageInfo() {
    return this._getData("/open/platform/storageInfo", { headers: this._openHeaders() });
  }

  async acquireLicenseLease({
    nodeId,
    controlCode,
    algorithmCode,
    streamCode = "",
    ttlSeconds,
  } = {}) {
    const payload = {
      node_id: String(nodeId || ""),
      control_code: String(controlCode || ""),
      algorithm_code: String(algorithmCode || ""),
    };
    if (streamCode && String(streamCode).trim()) {
      payload.stream_code = String(streamCode).trim();
    }
    if (ttlSeconds !== undefined && ttlSeconds !== null) {
      payload.ttl_seconds = Number(ttlSeconds);
    }
    const body = await this._request("POST", "/open/license/lease/acquire", {
      headers: { "content-type": "application/json", ...this._openHeaders() },
      body: JSON.stringify(payload),
    });
    return body?.data;
  }

  async renewLicenseLease({ leaseId, ttlSeconds } = {}) {
    const payload = {
      lease_id: String(leaseId || ""),
    };
    if (ttlSeconds !== undefined && ttlSeconds !== null) {
      payload.ttl_seconds = Number(ttlSeconds);
    }
    const body = await this._request("POST", "/open/license/lease/renew", {
      headers: { "content-type": "application/json", ...this._openHeaders() },
      body: JSON.stringify(payload),
    });
    return body?.data;
  }

  async releaseLicenseLease({ leaseId } = {}) {
    return this._request("POST", "/open/license/lease/release", {
      headers: { "content-type": "application/json", ...this._openHeaders() },
      body: JSON.stringify({ lease_id: String(leaseId || "") }),
    });
  }

  async addRecordingPlan(payload = {}) {
    return this._postData("/open/recordingPlan/add", payload, { headers: this._openHeaders() });
  }

  async listRecordingPlans(payload = {}) {
    return (await this._postData("/open/recordingPlan/list", payload, { headers: this._openHeaders() })) || [];
  }

  async editRecordingPlan(payload = {}) {
    return this._postData("/open/recordingPlan/edit", payload, { headers: this._openHeaders() });
  }

  async deleteRecordingPlan({ code } = {}) {
    return this._postData("/open/recordingPlan/delete", { code: String(code || "") }, { headers: this._openHeaders() });
  }

  async addTaskPlan(payload = {}) {
    return this._postData("/open/taskPlan/add", payload, { headers: this._openHeaders() });
  }

  async listTaskPlans(payload = {}) {
    return (await this._postData("/open/taskPlan/list", payload, { headers: this._openHeaders() })) || [];
  }

  async editTaskPlan(payload = {}) {
    return this._postData("/open/taskPlan/edit", payload, { headers: this._openHeaders() });
  }

  async deleteTaskPlan({ code } = {}) {
    return this._postData("/open/taskPlan/delete", { code: String(code || "") }, { headers: this._openHeaders() });
  }

  async listRecordingFiles(payload = {}) {
    return (await this._postData("/open/recording/file/list", payload, { headers: this._openHeaders() })) || [];
  }

  async getRecordingFilePlayUrl(payload = {}) {
    return this._postData("/open/recording/file/playUrl", payload, { headers: this._openHeaders() });
  }

  async startRecording(payload = {}) {
    return this._postData("/open/recording/startRecording", payload, { headers: this._openHeaders() });
  }

  async stopRecording(payload = {}) {
    return this._postData("/open/recording/stopRecording", payload, { headers: this._openHeaders() });
  }

  async captureSnapshot(payload = {}) {
    return this._postData("/open/recording/captureSnapshot", payload, { headers: this._openHeaders() });
  }

  async listFaces() {
    return this._postData("/open/face/list", {}, { headers: this._openHeaders() });
  }

  async addFace(payload = {}) {
    return this._postData("/open/face/add", payload, { headers: this._openHeaders() });
  }

  async deleteFace({ id } = {}) {
    return this._postData("/open/face/delete", { id: String(id || "") }, { headers: this._openHeaders() });
  }

  async searchFace(payload = {}) {
    return this._postData("/open/face/search", payload, { headers: this._openHeaders() });
  }

  async enableFaceSearch() {
    return this._postData("/open/face/enable", {}, { headers: this._openHeaders() });
  }

  async disableFaceSearch() {
    return this._postData("/open/face/disable", {}, { headers: this._openHeaders() });
  }

  async cloudPresignImage(payload = {}) {
    return this._postData("/open/cloud/v1/presign/image", payload, { headers: this._cloudHeaders() });
  }

  async cloudIngestAlarmCreated(payload = {}) {
    return this._request("POST", "/open/cloud/v1/events/alarm-created", {
      headers: { "content-type": "application/json", ...this._cloudHeaders() },
      body: JSON.stringify(payload || {}),
    });
  }

  async opsCleanup(payload = {}) {
    return this._postData("/open/ops/cleanup", payload, { headers: this._openHeaders() });
  }

  async opsOutboxReplay(payload = {}) {
    return this._postData("/open/ops/outbox/replay", payload, { headers: this._openHeaders() });
  }

  async opsSetLoggingLevel(payload = {}) {
    return this._postData("/open/ops/logging/level", payload, { headers: this._openHeaders() });
  }

  async opsHealth() {
    return this._getData("/open/ops/health", { headers: this._openHeaders() });
  }

  async opsReady() {
    return this._getData("/open/ops/ready", { headers: this._openHeaders() });
  }

  async opsMetrics() {
    const response = await this._requestRaw("GET", "/open/ops/metrics", { headers: this._openHeaders() });
    return response.text();
  }

  async opsAuditExport({ format = "csv" } = {}) {
    const response = await this._requestRaw("GET", "/open/ops/audit/export", {
      headers: this._openHeaders(),
      query: { format },
    });
    return response.arrayBuffer();
  }

  async opsDiagnosticsExport(params = {}) {
    const response = await this._requestRaw("GET", "/open/ops/diagnostics/export", {
      headers: this._openHeaders(),
      query: params,
    });
    return response.arrayBuffer();
  }

  async opsUpgradeList({ onlyCompatible = false } = {}) {
    return (await this._getData("/open/ops/upgrade/list", {
      headers: this._openHeaders(),
      query: onlyCompatible ? { only_compatible: "1" } : undefined,
    })) || [];
  }

  async opsUpgradeValidate({ packageId } = {}) {
    return this._getData("/open/ops/upgrade/validate", {
      headers: this._openHeaders(),
      query: { package_id: String(packageId || "") },
    });
  }

  async opsUpgradeApply(payload = {}) {
    return this._postData("/open/ops/upgrade/apply", payload, { headers: this._openHeaders() });
  }

  async opsUpgradeRollback() {
    return this._postData("/open/ops/upgrade/rollback", {}, { headers: this._openHeaders() });
  }

  async opsUpgradeUpload({ fileName = "package.zip", bytes, contentType = "application/zip" } = {}) {
    const form = new FormData();
    const blob = bytes instanceof Blob ? bytes : new Blob([bytes ?? new Uint8Array()], { type: contentType });
    form.append("file", blob, String(fileName || "package.zip"));
    const payload = await this._request("POST", "/open/ops/upgrade/upload", {
      headers: this._openHeaders(),
      body: form,
    });
    return payload?.data;
  }

  async imageDetect(payload = {}) {
    return this._postData("/open/algorithm/imageDetect", payload, { headers: this._openHeaders() });
  }

  async audioDetect(payload = {}) {
    return this._postData("/open/algorithm/audioDetect", payload, { headers: this._openHeaders() });
  }

  async discover() {
    const payload = await this._request("GET", "/open/discover", { headers: this._openHeaders() });
    return payload?.info || {};
  }

  async getAllStreamData() {
    return (await this._getData("/open/getAllStreamData", { headers: this._openHeaders() })) || [];
  }

  async getAllAlgorithmFlowData() {
    return (await this._getData("/open/getAllAlgroithmFlowData", { headers: this._openHeaders() })) || [];
  }

  async getAllCoreProcessData() {
    const payload = await this._request("GET", "/open/getAllCoreProcessData", { headers: this._openHeaders() });
    return { data: payload?.data || [], info: payload?.info || {} };
  }

  async getAllCoreProcessData2() {
    const payload = await this._request("GET", "/open/getAllCoreProcessData2", { headers: this._openHeaders() });
    return payload?.info || {};
  }

  async restartSoftware() {
    return this._request("POST", "/open/platform/restartSoftware", {
      headers: { "content-type": "application/json", ...this._openHeaders() },
      body: JSON.stringify({}),
    });
  }

  async restartSystem() {
    return this._request("POST", "/open/platform/restartSystem", {
      headers: { "content-type": "application/json", ...this._openHeaders() },
      body: JSON.stringify({}),
    });
  }

  async downloadFile(relPath = "") {
    const clean = String(relPath || "").replace(/^\/+/, "");
    const encoded = clean
      .split("/")
      .map((part) => encodeURIComponent(part))
      .join("/");
    const response = await this._requestRaw("GET", `/open/fileService/${encoded}`, {
      headers: this._openHeaders(),
    });
    return response.arrayBuffer();
  }
}

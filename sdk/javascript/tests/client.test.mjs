import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";

let BeaconApiError;
let BeaconClient;
let importError = null;

try {
  ({ BeaconApiError, BeaconClient } = await import("../beacon-sdk.mjs"));
} catch (error) {
  importError = error;
}

function makeResponse(payload, { headers = {}, ok = true, status = 200, body = null, text = null } = {}) {
  let encodedBody = new Uint8Array();
  if (body instanceof Uint8Array) {
    encodedBody = body;
  } else if (body instanceof ArrayBuffer) {
    encodedBody = new Uint8Array(body);
  } else if (text !== null && text !== undefined) {
    encodedBody = new TextEncoder().encode(String(text));
  } else if (payload !== null && payload !== undefined) {
    encodedBody = new TextEncoder().encode(JSON.stringify(payload));
  }
  return {
    ok,
    status,
    async json() {
      if (payload == null) throw new Error("no json payload");
      return payload;
    },
    async text() {
      if (text === null || text === undefined) {
        return new TextDecoder().decode(encodedBody);
      }
      return String(text);
    },
    async arrayBuffer() {
      return encodedBody.buffer.slice(encodedBody.byteOffset, encodedBody.byteOffset + encodedBody.byteLength);
    },
    headers: {
      get(name) {
        return headers[String(name || "").toLowerCase()] ?? null;
      },
      getSetCookie() {
        const raw = headers["set-cookie"];
        if (raw === null || raw === undefined || raw === "") return [];
        return Array.isArray(raw) ? raw : [raw];
      },
    },
  };
}

test("sdk module is present", () => {
  assert.equal(importError, null, `sdk/javascript/beacon-sdk.mjs is missing: ${importError}`);
  assert.equal(typeof BeaconClient, "function");
  assert.equal(typeof BeaconApiError, "function");
});

test("login stores session cookie and returns payload", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse(
      { code: 1000, msg: "登录成功" },
      { headers: { "set-cookie": "v3_sessionid=session123; Path=/; HttpOnly" } },
    );
  };
  const client = new BeaconClient("http://localhost:9991", { fetchImpl });

  const password = `test-${crypto.randomBytes(8).toString("hex")}`;
  const payload = await client.login("admin", password, { verifyCode: "1234" });
  const expectedBody = new URLSearchParams({
    username: "admin",
    password,
    verify_code: "1234",
  }).toString();

  assert.equal(payload.code, 1000);
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/login",
      options: {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: expectedBody,
        credentials: "include",
      },
    },
  ]);
  assert.equal(client.cookieHeader, "v3_sessionid=session123");
});

test("getControls sends stored cookie to developer endpoint", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse({ code: 1000, msg: "success", data: [{ control_code: "c001" }] });
  };
  const client = new BeaconClient("http://localhost:9991/", { fetchImpl });
  client.cookieHeader = "v3_sessionid=session123";

  const data = await client.getControls();

  assert.deepEqual(data, [{ control_code: "c001" }]);
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/developer/getStreamInfo",
      options: {
        method: "GET",
        headers: { cookie: "v3_sessionid=session123" },
        credentials: "include",
      },
    },
  ]);
});

test("reportDetection posts expected json body", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse({ code: 1000, msg: "success" });
  };
  const client = new BeaconClient("http://localhost:9991", { fetchImpl });

  const payload = await client.reportDetection({
    controlCode: "ctrl001",
    detections: [{ class_name: "person", confidence: 0.95 }],
    frameIndex: 12,
    timestamp: 1702700000,
    triggerAlarm: true,
    imageBase64: "ZmFrZS1pbWFnZQ==",
  });

  assert.equal(payload.code, 1000);
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/developer/algorithmCallback",
      options: {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          control_code: "ctrl001",
          frame_index: 12,
          timestamp: 1702700000,
          detections: [{ class_name: "person", confidence: 0.95 }],
          trigger_alarm: true,
          image_base64: "ZmFrZS1pbWFnZQ==",
        }),
        credentials: "include",
      },
    },
  ]);
});

test("non-success response raises BeaconApiError", async () => {
  const fetchImpl = async () => makeResponse({ code: 0, msg: "密码错误" });
  const client = new BeaconClient("http://localhost:9991", { fetchImpl });

  await assert.rejects(() => client.login("admin", "wrong"), (error) => {
    assert.ok(error instanceof BeaconApiError);
    assert.match(String(error.message), /密码错误/);
    return true;
  });
});

test("uploadAlarm posts openapi token and json body", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse({ code: 1000, msg: "success", data: { id: 1 } });
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  const payload = await client.uploadAlarm({
    controlCode: "C001",
    desc: "sdk upload",
    imageBase64: "ZmFrZS1pbWFnZQ==",
    alarmType: "crossing",
  });

  assert.equal(payload.code, 1000);
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/open/alarm/upload",
      options: {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-beacon-token": "token-open-001",
        },
        body: JSON.stringify({
          control_code: "C001",
          desc: "sdk upload",
          image_base64: "ZmFrZS1pbWFnZQ==",
          alarm_type: "crossing",
        }),
        credentials: "include",
      },
    },
  ]);
});

test("checkVersion forwards query params and returns data payload", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse({ code: 1000, msg: "success", data: { currentVersion: "4.22.0", hasUpdate: false } });
  };
  const client = new BeaconClient("http://localhost:9991", { fetchImpl });

  const payload = await client.checkVersion({ infer_engine: "openvino", infer_engine_version: "2024.4" });

  assert.deepEqual(payload, { currentVersion: "4.22.0", hasUpdate: false });
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/open/checkVersion?infer_engine=openvino&infer_engine_version=2024.4",
      options: {
        method: "GET",
        headers: {},
        credentials: "include",
      },
    },
  ]);
});

test("core openapi queries return data and send token", async () => {
  const queue = [
    { code: 1000, msg: "success", data: { license_id: "LIC-1" } },
    { code: 1000, msg: "success", data: { active_controls: 2 } },
    { code: 1000, msg: "success", data: [{ code: "ctrl-1" }] },
    { code: 1000, msg: "success", data: [{ code: "stream-1" }] },
    { code: 1000, msg: "success", data: { nodeCode: "node-1" } },
    { code: 1000, msg: "success", data: { storageRootPath: "/data" } },
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse(queue.shift());
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  assert.deepEqual(await client.getLicenseInfo(), { license_id: "LIC-1" });
  assert.deepEqual(await client.getLicenseUsage(), { active_controls: 2 });
  assert.deepEqual(await client.getControlData({ code: "ctrl-1" }), [{ code: "ctrl-1" }]);
  assert.deepEqual(await client.getStreamData({ code: "stream-1" }), [{ code: "stream-1" }]);
  assert.deepEqual(await client.getPlatformBasicInfo(), { nodeCode: "node-1" });
  assert.deepEqual(await client.getPlatformStorageInfo(), { storageRootPath: "/data" });

  const expectedHeaders = { "x-beacon-token": "token-open-001" };
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/open/license/info",
      options: { method: "GET", headers: expectedHeaders, credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/license/usage",
      options: { method: "GET", headers: expectedHeaders, credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/getControlData?code=ctrl-1",
      options: { method: "GET", headers: expectedHeaders, credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/getStreamData?code=stream-1",
      options: { method: "GET", headers: expectedHeaders, credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/platform/basicInfo",
      options: { method: "GET", headers: expectedHeaders, credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/platform/storageInfo",
      options: { method: "GET", headers: expectedHeaders, credentials: "include" },
    },
  ]);
});

test("license lease methods post openapi json payloads", async () => {
  const queue = [
    { code: 1000, msg: "success", data: { lease_id: "lease-1", expires_at: "2026-03-09T10:00:00" } },
    { code: 1000, msg: "success", data: { expires_at: "2026-03-09T10:30:00" } },
    { code: 1000, msg: "success" },
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse(queue.shift());
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  assert.deepEqual(
    await client.acquireLicenseLease({
      nodeId: "node-1",
      controlCode: "ctrl-1",
      algorithmCode: "alg-1",
      streamCode: "cam-001",
      ttlSeconds: 180,
    }),
    { lease_id: "lease-1", expires_at: "2026-03-09T10:00:00" },
  );
  assert.deepEqual(
    await client.renewLicenseLease({
      leaseId: "lease-1",
      ttlSeconds: 240,
    }),
    { expires_at: "2026-03-09T10:30:00" },
  );
  assert.deepEqual(await client.releaseLicenseLease({ leaseId: "lease-1" }), { code: 1000, msg: "success" });

  const expectedHeaders = {
    "content-type": "application/json",
    "x-beacon-token": "token-open-001",
  };
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/open/license/lease/acquire",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({
          node_id: "node-1",
          control_code: "ctrl-1",
          algorithm_code: "alg-1",
          stream_code: "cam-001",
          ttl_seconds: 180,
        }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/license/lease/renew",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({
          lease_id: "lease-1",
          ttl_seconds: 240,
        }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/license/lease/release",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({
          lease_id: "lease-1",
        }),
        credentials: "include",
      },
    },
  ]);
});

test("recording and task plan methods post openapi json payloads", async () => {
  const queue = [
    { code: 1000, msg: "success", data: { code: "plan001" } },
    { code: 1000, msg: "success", data: [{ code: "plan001" }] },
    { code: 1000, msg: "success", data: { enabled: false } },
    { code: 1000, msg: "success", data: { deleted: 1 } },
    { code: 1000, msg: "success", data: { code: "task001" } },
    { code: 1000, msg: "success", data: [{ code: "task001" }] },
    { code: 1000, msg: "success", data: { enabled: false } },
    { code: 1000, msg: "success", data: { deleted: 1 } },
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse(queue.shift());
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  assert.deepEqual(
    await client.addRecordingPlan({
      code: "plan001",
      name: "Plan 1",
      streamCode: "stream001",
      startTime: "00:00",
      endTime: "23:59",
    }),
    { code: "plan001" },
  );
  assert.deepEqual(await client.listRecordingPlans(), [{ code: "plan001" }]);
  assert.deepEqual(await client.editRecordingPlan({ code: "plan001", enabled: 0 }), { enabled: false });
  assert.deepEqual(await client.deleteRecordingPlan({ code: "plan001" }), { deleted: 1 });

  assert.deepEqual(
    await client.addTaskPlan({
      code: "task001",
      name: "Task 1",
      taskType: "restart_software",
      scheduleType: "daily",
      runTime: "02:00",
    }),
    { code: "task001" },
  );
  assert.deepEqual(await client.listTaskPlans(), [{ code: "task001" }]);
  assert.deepEqual(await client.editTaskPlan({ code: "task001", enabled: 0 }), { enabled: false });
  assert.deepEqual(await client.deleteTaskPlan({ code: "task001" }), { deleted: 1 });

  const expectedHeaders = {
    "content-type": "application/json",
    "x-beacon-token": "token-open-001",
  };
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/open/recordingPlan/add",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ code: "plan001", name: "Plan 1", streamCode: "stream001", startTime: "00:00", endTime: "23:59" }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/recordingPlan/list",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({}),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/recordingPlan/edit",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ code: "plan001", enabled: 0 }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/recordingPlan/delete",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ code: "plan001" }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/taskPlan/add",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ code: "task001", name: "Task 1", taskType: "restart_software", scheduleType: "daily", runTime: "02:00" }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/taskPlan/list",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({}),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/taskPlan/edit",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ code: "task001", enabled: 0 }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/taskPlan/delete",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ code: "task001" }),
        credentials: "include",
      },
    },
  ]);
});

test("recording runtime methods use openapi json payloads", async () => {
  const queue = [
    { code: 1000, msg: "success", data: [{ filename: "demo.mp4" }], total: 1 },
    { code: 1000, msg: "success", data: { play_url: "https://demo/open/fileService/recordings/a.mp4" } },
    { code: 1000, msg: "success", data: { record_id: "rec-1", save_path: "recordings/stream001/demo.mp4" } },
    { code: 1000, msg: "success", data: { save_path: "recordings/stream001/demo.mp4", duration: 1.2 } },
    { code: 1000, msg: "success", data: { image_path: "snapshots/stream001/demo.jpg" } },
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse(queue.shift());
  };
  const client = new BeaconClient("https://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  assert.deepEqual(await client.listRecordingFiles({ streamCode: "stream001" }), [{ filename: "demo.mp4" }]);
  assert.deepEqual(
    await client.getRecordingFilePlayUrl({ relPath: "recordings/stream001/demo.mp4" }),
    { play_url: "https://demo/open/fileService/recordings/a.mp4" },
  );
  assert.deepEqual(
    await client.startRecording({ streamCode: "stream001", streamUrl: "rtsp://127.0.0.1/demo", duration: 10, format: "mp4", recordAudio: 1 }),
    { record_id: "rec-1", save_path: "recordings/stream001/demo.mp4" },
  );
  assert.deepEqual(
    await client.stopRecording({ streamCode: "stream001" }),
    { save_path: "recordings/stream001/demo.mp4", duration: 1.2 },
  );
  assert.deepEqual(
    await client.captureSnapshot({ streamCode: "stream001", streamUrl: "rtsp://127.0.0.1/demo" }),
    { image_path: "snapshots/stream001/demo.jpg" },
  );

  const expectedHeaders = {
    "content-type": "application/json",
    "x-beacon-token": "token-open-001",
  };
  assert.deepEqual(calls, [
    {
      url: "https://localhost:9991/open/recording/file/list",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ streamCode: "stream001" }),
        credentials: "include",
      },
    },
    {
      url: "https://localhost:9991/open/recording/file/playUrl",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ relPath: "recordings/stream001/demo.mp4" }),
        credentials: "include",
      },
    },
    {
      url: "https://localhost:9991/open/recording/startRecording",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ streamCode: "stream001", streamUrl: "rtsp://127.0.0.1/demo", duration: 10, format: "mp4", recordAudio: 1 }),
        credentials: "include",
      },
    },
    {
      url: "https://localhost:9991/open/recording/stopRecording",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ streamCode: "stream001" }),
        credentials: "include",
      },
    },
    {
      url: "https://localhost:9991/open/recording/captureSnapshot",
      options: {
        method: "POST",
        headers: expectedHeaders,
        body: JSON.stringify({ streamCode: "stream001", streamUrl: "rtsp://127.0.0.1/demo" }),
        credentials: "include",
      },
    },
  ]);
});

test("face methods use openapi json payloads", async () => {
  const queue = [
    { code: 1000, msg: "success", data: { count: 1, items: [{ id: "alice" }] } },
    { code: 1000, msg: "success", data: { code: 1000, msg: "success" } },
    { code: 1000, msg: "success", data: { found: false } },
    { code: 1000, msg: "success", data: { code: 1000, msg: "success" } },
    { code: 1000, msg: "success", data: { code: 1000, msg: "success" } },
    { code: 1000, msg: "success", data: { code: 1000, msg: "success" } },
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse(queue.shift());
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  assert.deepEqual(await client.listFaces(), { count: 1, items: [{ id: "alice" }] });
  assert.deepEqual(await client.addFace({ id: "alice", name: "Alice", embedding: [1, 0] }), { code: 1000, msg: "success" });
  assert.deepEqual(await client.searchFace({ embedding: [1, 0], minScore: 0.8 }), { found: false });
  assert.deepEqual(await client.enableFaceSearch(), { code: 1000, msg: "success" });
  assert.deepEqual(await client.disableFaceSearch(), { code: 1000, msg: "success" });
  assert.deepEqual(await client.deleteFace({ id: "alice" }), { code: 1000, msg: "success" });

  const expectedHeaders = {
    "content-type": "application/json",
    "x-beacon-token": "token-open-001",
  };
  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/open/face/list",
      options: { method: "POST", headers: expectedHeaders, body: JSON.stringify({}), credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/face/add",
      options: { method: "POST", headers: expectedHeaders, body: JSON.stringify({ id: "alice", name: "Alice", embedding: [1, 0] }), credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/face/search",
      options: { method: "POST", headers: expectedHeaders, body: JSON.stringify({ embedding: [1, 0], minScore: 0.8 }), credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/face/enable",
      options: { method: "POST", headers: expectedHeaders, body: JSON.stringify({}), credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/face/disable",
      options: { method: "POST", headers: expectedHeaders, body: JSON.stringify({}), credentials: "include" },
    },
    {
      url: "http://localhost:9991/open/face/delete",
      options: { method: "POST", headers: expectedHeaders, body: JSON.stringify({ id: "alice" }), credentials: "include" },
    },
  ]);
});

test("cloud and ops methods use expected auth and payloads", async () => {
  const queue = [
    { code: 1000, msg: "success", data: { bucket: "beacon-alarms" } },
    { code: 1000, msg: "success" },
    { code: 1000, msg: "success", data: { targets: { logs: { deleted_files: 1 } } } },
    { code: 1000, msg: "success", data: { updated: 1 } },
    { code: 1000, msg: "success", data: { level: "DEBUG", loggers: ["app.middleware"] } },
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return makeResponse(queue.shift());
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
    cloudEdgeToken: "edge-token-001",
  });

  assert.deepEqual(
    await client.cloudPresignImage({ event_id: "evt-1", content_type: "image/jpeg", ext: ".jpg" }),
    { bucket: "beacon-alarms" },
  );
  assert.deepEqual(
    await client.cloudIngestAlarmCreated({
      schema: "beacon.event.v1",
      event_id: "evt-1",
      event_type: "alarm.created",
      event_source: "openAdd",
    }),
    { code: 1000, msg: "success" },
  );
  assert.deepEqual(await client.opsCleanup({ targets: ["logs"], dry_run: true }), { targets: { logs: { deleted_files: 1 } } });
  assert.deepEqual(await client.opsOutboxReplay({ event_id: "evt-1" }), { updated: 1 });
  assert.deepEqual(await client.opsSetLoggingLevel({ level: "DEBUG", logger: "app.middleware" }), { level: "DEBUG", loggers: ["app.middleware"] });

  assert.deepEqual(calls, [
    {
      url: "http://localhost:9991/open/cloud/v1/presign/image",
      options: {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer edge-token-001" },
        body: JSON.stringify({ event_id: "evt-1", content_type: "image/jpeg", ext: ".jpg" }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/cloud/v1/events/alarm-created",
      options: {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer edge-token-001" },
        body: JSON.stringify({ schema: "beacon.event.v1", event_id: "evt-1", event_type: "alarm.created", event_source: "openAdd" }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/ops/cleanup",
      options: {
        method: "POST",
        headers: { "content-type": "application/json", "x-beacon-token": "token-open-001" },
        body: JSON.stringify({ targets: ["logs"], dry_run: true }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/ops/outbox/replay",
      options: {
        method: "POST",
        headers: { "content-type": "application/json", "x-beacon-token": "token-open-001" },
        body: JSON.stringify({ event_id: "evt-1" }),
        credentials: "include",
      },
    },
    {
      url: "http://localhost:9991/open/ops/logging/level",
      options: {
        method: "POST",
        headers: { "content-type": "application/json", "x-beacon-token": "token-open-001" },
        body: JSON.stringify({ level: "DEBUG", logger: "app.middleware" }),
        credentials: "include",
      },
    },
  ]);
});

test("ops export and upgrade methods use expected payloads", async () => {
  const queue = [
    makeResponse({ code: 1000, msg: "success", data: { status: "ok" } }),
    makeResponse({ code: 1000, msg: "success", data: { status: "ok" } }),
    makeResponse(null, { text: "metric 1\n" }),
    makeResponse(null, { body: new TextEncoder().encode("event_type\nlicense.lease.acquire\n") }),
    makeResponse(null, { body: new Uint8Array([0x50, 0x4b, 0x03, 0x04]) }),
    makeResponse({ code: 1000, msg: "success", data: [{ package_id: "pkg-a" }] }),
    makeResponse({ code: 1000, msg: "success", data: { ok: true, package_id: "pkg-a" } }),
    makeResponse({ code: 1000, msg: "success", data: { applied_package_id: "pkg-a" } }),
    makeResponse({ code: 1000, msg: "success", data: { applied_package_id: "pkg-prev" } }),
    makeResponse({ code: 1000, msg: "success", data: { package_id: "pkg-up" } }),
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return queue.shift();
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  assert.deepEqual(await client.opsHealth(), { status: "ok" });
  assert.deepEqual(await client.opsReady(), { status: "ok" });
  assert.equal(await client.opsMetrics(), "metric 1\n");
  assert.equal(Buffer.from(await client.opsAuditExport({ format: "csv" })).toString("utf-8"), "event_type\nlicense.lease.acquire\n");
  assert.deepEqual(Array.from(new Uint8Array(await client.opsDiagnosticsExport())), [0x50, 0x4b, 0x03, 0x04]);
  assert.deepEqual(await client.opsUpgradeList(), [{ package_id: "pkg-a" }]);
  assert.deepEqual(await client.opsUpgradeValidate({ packageId: "pkg-a" }), { ok: true, package_id: "pkg-a" });
  assert.deepEqual(await client.opsUpgradeApply({ package_id: "pkg-a" }), { applied_package_id: "pkg-a" });
  assert.deepEqual(await client.opsUpgradeRollback(), { applied_package_id: "pkg-prev" });
  assert.deepEqual(await client.opsUpgradeUpload({ fileName: "upgrade.zip", bytes: Buffer.from("ZIPDATA") }), { package_id: "pkg-up" });

  const openHeaders = { "x-beacon-token": "token-open-001" };
  assert.equal(calls[0].url, "http://localhost:9991/open/ops/health");
  assert.deepEqual(calls[0].options, { method: "GET", headers: openHeaders, credentials: "include" });
  assert.equal(calls[2].url, "http://localhost:9991/open/ops/metrics");
  assert.equal(calls[3].url, "http://localhost:9991/open/ops/audit/export?format=csv");
  assert.equal(calls[4].url, "http://localhost:9991/open/ops/diagnostics/export");
  assert.equal(calls[5].url, "http://localhost:9991/open/ops/upgrade/list");
  assert.equal(calls[6].url, "http://localhost:9991/open/ops/upgrade/validate?package_id=pkg-a");
  assert.equal(calls[7].url, "http://localhost:9991/open/ops/upgrade/apply");
  assert.equal(calls[8].url, "http://localhost:9991/open/ops/upgrade/rollback");
  assert.equal(calls[7].options.body, JSON.stringify({ package_id: "pkg-a" }));
  assert.equal(calls[8].options.body, JSON.stringify({}));
  assert.ok(calls[9].options.body instanceof FormData);
  assert.equal(calls[9].options.headers["x-beacon-token"], "token-open-001");
});

test("low-level openapi methods use expected payloads", async () => {
  const queue = [
    makeResponse({ code: 1000, msg: "success", data: { engine: "api", detects: [] } }),
    makeResponse({ code: 1000, msg: "success", data: { engine: "api", text: "ni hao", language: "zh-CN", segments: [] } }),
    makeResponse({ code: 1000, msg: "success", info: { code: "node-1" } }),
    makeResponse({ code: 1000, msg: "success", data: [{ code: "stream-1" }] }),
    makeResponse({ code: 1000, msg: "success", data: [{ code: "algo-1" }] }),
    makeResponse({ code: 1000, msg: "success", data: [{ process_index: 0 }], info: { processNum: 1 } }),
    makeResponse({ code: 1000, msg: "success", info: { processNum: 1, controlCount: 2 } }),
    makeResponse({ code: 1000, msg: "restarting" }),
    makeResponse({ code: 1000, msg: "restarting" }),
    makeResponse(null, { body: new TextEncoder().encode("hello") }),
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return queue.shift();
  };
  const client = new BeaconClient("http://localhost:9991", {
    fetchImpl,
    openApiToken: "token-open-001",
  });

  assert.deepEqual(await client.imageDetect({ code: "alg-api", image_base64: "Zm9v" }), { engine: "api", detects: [] });
  assert.deepEqual(await client.audioDetect({ code: "asr-api", audio_base64: "YmFy", language: "zh-CN" }), { engine: "api", text: "ni hao", language: "zh-CN", segments: [] });
  assert.deepEqual(await client.discover(), { code: "node-1" });
  assert.deepEqual(await client.getAllStreamData(), [{ code: "stream-1" }]);
  assert.deepEqual(await client.getAllAlgorithmFlowData(), [{ code: "algo-1" }]);
  assert.deepEqual(await client.getAllCoreProcessData(), { data: [{ process_index: 0 }], info: { processNum: 1 } });
  assert.deepEqual(await client.getAllCoreProcessData2(), { processNum: 1, controlCount: 2 });
  assert.deepEqual(await client.restartSoftware(), { code: 1000, msg: "restarting" });
  assert.deepEqual(await client.restartSystem(), { code: 1000, msg: "restarting" });
  assert.equal(Buffer.from(await client.downloadFile("hello.txt")).toString("utf-8"), "hello");

  const openHeaders = { "x-beacon-token": "token-open-001" };
  assert.deepEqual(calls, [
    { url: "http://localhost:9991/open/algorithm/imageDetect", options: { method: "POST", headers: { "content-type": "application/json", ...openHeaders }, body: JSON.stringify({ code: "alg-api", image_base64: "Zm9v" }), credentials: "include" } },
    { url: "http://localhost:9991/open/algorithm/audioDetect", options: { method: "POST", headers: { "content-type": "application/json", ...openHeaders }, body: JSON.stringify({ code: "asr-api", audio_base64: "YmFy", language: "zh-CN" }), credentials: "include" } },
    { url: "http://localhost:9991/open/discover", options: { method: "GET", headers: openHeaders, credentials: "include" } },
    { url: "http://localhost:9991/open/getAllStreamData", options: { method: "GET", headers: openHeaders, credentials: "include" } },
    { url: "http://localhost:9991/open/getAllAlgroithmFlowData", options: { method: "GET", headers: openHeaders, credentials: "include" } },
    { url: "http://localhost:9991/open/getAllCoreProcessData", options: { method: "GET", headers: openHeaders, credentials: "include" } },
    { url: "http://localhost:9991/open/getAllCoreProcessData2", options: { method: "GET", headers: openHeaders, credentials: "include" } },
    { url: "http://localhost:9991/open/platform/restartSoftware", options: { method: "POST", headers: { "content-type": "application/json", ...openHeaders }, body: JSON.stringify({}), credentials: "include" } },
    { url: "http://localhost:9991/open/platform/restartSystem", options: { method: "POST", headers: { "content-type": "application/json", ...openHeaders }, body: JSON.stringify({}), credentials: "include" } },
    { url: "http://localhost:9991/open/fileService/hello.txt", options: { method: "GET", headers: openHeaders, credentials: "include" } },
  ]);
});

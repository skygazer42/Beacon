# Beacon Python SDK

Python SDK for Beacon developer integration and core OpenAPI query endpoints.

## Included APIs

- `login()`
- `get_controls()` / `get_stream_info()`
- `get_algorithms()` / `get_algorithm_info()`
- `report_detection()`
- `upload_alarm()`
- `check_version()`
- `get_license_info()`
- `get_license_usage()`
- `get_control_data()`
- `get_stream_data()`
- `get_platform_basic_info()`
- `get_platform_storage_info()`
- `acquire_license_lease()`
- `renew_license_lease()`
- `release_license_lease()`
- `add_recording_plan()` / `list_recording_plans()` / `edit_recording_plan()` / `delete_recording_plan()`
- `add_task_plan()` / `list_task_plans()` / `edit_task_plan()` / `delete_task_plan()`
- `list_recording_files()`
- `get_recording_file_play_url()`
- `start_recording()` / `stop_recording()`
- `capture_snapshot()`
- `list_faces()`
- `add_face()` / `delete_face()`
- `search_face()`
- `enable_face_search()` / `disable_face_search()`
- `cloud_presign_image()` / `cloud_ingest_alarm_created()`
- `ops_cleanup()` / `ops_outbox_replay()` / `ops_set_logging_level()`
- `ops_health()` / `ops_ready()` / `ops_metrics()`
- `ops_audit_export()` / `ops_diagnostics_export()`
- `ops_upgrade_list()` / `ops_upgrade_validate()` / `ops_upgrade_apply()` / `ops_upgrade_rollback()` / `ops_upgrade_upload()`
- `image_detect()`
- `audio_detect()`
- `discover()`
- `get_all_stream_data()` / `get_all_algorithm_flow_data()`
- `get_all_core_process_data()` / `get_all_core_process_data2()`
- `restart_software()` / `restart_system()`
- `download_file()`

## Example

```python
from beacon_sdk import BeaconClient

client = BeaconClient(
    "http://localhost:9991",
    open_api_token="token-open-001",
    cloud_edge_token="edge-token-001",
)
client.login("admin", "<your-admin-password>")

controls = client.get_controls()
print(controls)
print(client.get_license_info())
print(client.get_platform_basic_info())
lease = client.acquire_license_lease(
    node_id="node-1",
    control_code="ctrl-1",
    algorithm_code="alg-1",
)
print(lease)
print(client.list_recording_plans())
print(client.list_recording_files(streamCode="stream001"))
print(client.list_faces())
print(client.ops_cleanup(targets=["logs"], dry_run=True))
print(client.audio_detect(code="asr-api", audio_base64="YmFy", language="en-US"))

client.report_detection(
    control_code="control_12345",
    detections=[{"class_name": "person", "confidence": 0.95}],
    trigger_alarm=True,
)
```

package beaconsdk

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strings"
	"time"
)

const (
	defaultBaseURL    = "http://localhost:9991"
	headerContentType = "Content-Type"
	headerBeaconToken = "X-Beacon-Token"
)

type APIError struct {
	Message string
	Code    int
	Payload map[string]any
}

func (e *APIError) Error() string {
	if e == nil || strings.TrimSpace(e.Message) == "" {
		return "Beacon API request failed"
	}
	return e.Message
}

type APIResponse struct {
	Code int
	Msg  string
	Data json.RawMessage
}

type Detection struct {
	ClassName  string         `json:"class_name"`
	Confidence float64        `json:"confidence,omitempty"`
	BBox       []float64      `json:"bbox,omitempty"`
	Extra      map[string]any `json:"extra,omitempty"`
}

type ReportDetectionRequest struct {
	ControlCode  string      `json:"control_code"`
	FrameIndex   int         `json:"frame_index"`
	Timestamp    int64       `json:"timestamp"`
	Detections   []Detection `json:"detections"`
	TriggerAlarm bool        `json:"trigger_alarm"`
	ImageBase64  string      `json:"image_base64,omitempty"`
}

type UploadAlarmRequest struct {
	ControlCode       string           `json:"control_code,omitempty"`
	Desc              string           `json:"desc,omitempty"`
	ImagePath         string           `json:"image_path,omitempty"`
	VideoPath         string           `json:"video_path,omitempty"`
	ImageBase64       string           `json:"image_base64,omitempty"`
	VideoBase64       string           `json:"video_base64,omitempty"`
	ImageExt          string           `json:"image_ext,omitempty"`
	VideoExt          string           `json:"video_ext,omitempty"`
	AlarmType         string           `json:"alarm_type,omitempty"`
	AlarmLevel        int              `json:"alarm_level,omitempty"`
	AlgorithmCode     string           `json:"algorithm_code,omitempty"`
	ObjectCode        string           `json:"object_code,omitempty"`
	RecognitionRegion string           `json:"recognition_region,omitempty"`
	RegionIndex       int              `json:"region_index,omitempty"`
	ClassThresh       float64          `json:"class_thresh,omitempty"`
	OverlapThresh     float64          `json:"overlap_thresh,omitempty"`
	MinInterval       int              `json:"min_interval,omitempty"`
	StreamCode        string           `json:"stream_code,omitempty"`
	StreamApp         string           `json:"stream_app,omitempty"`
	StreamName        string           `json:"stream_name,omitempty"`
	StreamURL         string           `json:"stream_url,omitempty"`
	ExtraImages       []map[string]any `json:"extra_images,omitempty"`
}

type AcquireLicenseLeaseRequest struct {
	NodeID        string `json:"node_id"`
	ControlCode   string `json:"control_code"`
	AlgorithmCode string `json:"algorithm_code"`
	StreamCode    string `json:"stream_code,omitempty"`
	TTLSeconds    int    `json:"ttl_seconds,omitempty"`
}

type RenewLicenseLeaseRequest struct {
	LeaseID    string `json:"lease_id"`
	TTLSeconds int    `json:"ttl_seconds,omitempty"`
}

type Client struct {
	baseURL        string
	httpClient     *http.Client
	openAPIToken   string
	cloudEdgeToken string
}

type Option func(*Client) error

func WithHTTPClient(httpClient *http.Client) Option {
	return func(c *Client) error {
		if httpClient == nil {
			return errors.New("http client is required")
		}
		c.httpClient = httpClient
		return nil
	}
}

func WithTimeout(timeout time.Duration) Option {
	return func(c *Client) error {
		if timeout > 0 {
			c.httpClient.Timeout = timeout
		}
		return nil
	}
}

func WithOpenAPIToken(token string) Option {
	return func(c *Client) error {
		c.openAPIToken = strings.TrimSpace(token)
		return nil
	}
}

func WithCloudEdgeToken(token string) Option {
	return func(c *Client) error {
		c.cloudEdgeToken = strings.TrimSpace(token)
		return nil
	}
}

func NewClient(baseURL string, opts ...Option) (*Client, error) {
	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, err
	}

	client := &Client{
		baseURL: strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
			Jar:     jar,
		},
	}
	if client.baseURL == "" {
		client.baseURL = defaultBaseURL
	}

	for _, opt := range opts {
		if opt == nil {
			continue
		}
		if err := opt(client); err != nil {
			return nil, err
		}
	}

	if client.httpClient == nil {
		client.httpClient = &http.Client{Timeout: 10 * time.Second, Jar: jar}
	}
	if client.httpClient.Jar == nil {
		client.httpClient.Jar = jar
	}

	return client, nil
}

func (c *Client) Login(username, password, verifyCode string) (*APIResponse, error) {
	form := url.Values{}
	form.Set("username", username)
	form.Set("password", password)
	if strings.TrimSpace(verifyCode) != "" {
		form.Set("verify_code", strings.TrimSpace(verifyCode))
	}

	req, err := http.NewRequest(http.MethodPost, c.baseURL+"/login", strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set(headerContentType, "application/x-www-form-urlencoded")
	return c.do(req)
}

func (c *Client) GetControls() ([]map[string]any, error) {
	var items []map[string]any
	if _, err := c.getData("/developer/getStreamInfo", &items); err != nil {
		return nil, err
	}
	return items, nil
}

func (c *Client) GetStreamInfo() ([]map[string]any, error) {
	return c.GetControls()
}

func (c *Client) GetAlgorithms() ([]map[string]any, error) {
	var items []map[string]any
	if _, err := c.getData("/developer/getAlgorithmInfo", &items); err != nil {
		return nil, err
	}
	return items, nil
}

func (c *Client) GetAlgorithmInfo() ([]map[string]any, error) {
	return c.GetAlgorithms()
}

func (c *Client) ReportDetection(payload ReportDetectionRequest) (*APIResponse, error) {
	if payload.Timestamp == 0 {
		payload.Timestamp = time.Now().Unix()
	}
	if payload.Detections == nil {
		payload.Detections = []Detection{}
	}
	return c.postJSON("/developer/algorithmCallback", payload, "")
}

func (c *Client) UploadAlarm(payload UploadAlarmRequest) (*APIResponse, error) {
	return c.postJSON("/open/alarm/upload", payload, c.openAPIToken)
}

func (c *Client) CheckVersion(params map[string]string) (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery("/open/checkVersion", params, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) GetLicenseInfo() (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery("/open/license/info", nil, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) GetLicenseUsage() (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery("/open/license/usage", nil, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) GetControlData(code string) ([]map[string]any, error) {
	var items []map[string]any
	params := map[string]string{}
	if strings.TrimSpace(code) != "" {
		params["code"] = strings.TrimSpace(code)
	}
	if _, err := c.getDataWithQuery("/open/getControlData", params, c.openAPIToken, &items); err != nil {
		return nil, err
	}
	return items, nil
}

func (c *Client) GetStreamData(code string) ([]map[string]any, error) {
	var items []map[string]any
	params := map[string]string{}
	if strings.TrimSpace(code) != "" {
		params["code"] = strings.TrimSpace(code)
	}
	if _, err := c.getDataWithQuery("/open/getStreamData", params, c.openAPIToken, &items); err != nil {
		return nil, err
	}
	return items, nil
}

func (c *Client) GetPlatformBasicInfo() (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery("/open/platform/basicInfo", nil, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) GetPlatformStorageInfo() (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery("/open/platform/storageInfo", nil, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) AcquireLicenseLease(payload AcquireLicenseLeaseRequest) (map[string]any, error) {
	resp, err := c.postJSON("/open/license/lease/acquire", payload, c.openAPIToken)
	if err != nil {
		return nil, err
	}
	data := map[string]any{}
	if len(resp.Data) > 0 && string(resp.Data) != "null" {
		if err := json.Unmarshal(resp.Data, &data); err != nil {
			return nil, err
		}
	}
	return data, nil
}

func (c *Client) RenewLicenseLease(payload RenewLicenseLeaseRequest) (map[string]any, error) {
	resp, err := c.postJSON("/open/license/lease/renew", payload, c.openAPIToken)
	if err != nil {
		return nil, err
	}
	data := map[string]any{}
	if len(resp.Data) > 0 && string(resp.Data) != "null" {
		if err := json.Unmarshal(resp.Data, &data); err != nil {
			return nil, err
		}
	}
	return data, nil
}

func (c *Client) ReleaseLicenseLease(leaseID string) (*APIResponse, error) {
	return c.postJSON(
		"/open/license/lease/release",
		map[string]any{"lease_id": strings.TrimSpace(leaseID)},
		c.openAPIToken,
	)
}

func (c *Client) AddRecordingPlan(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/recordingPlan/add", payload)
}

func (c *Client) ListRecordingPlans(payload map[string]any) ([]map[string]any, error) {
	return c.postOpenList("/open/recordingPlan/list", payload)
}

func (c *Client) EditRecordingPlan(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/recordingPlan/edit", payload)
}

func (c *Client) DeleteRecordingPlan(code string) (map[string]any, error) {
	return c.postOpenMap("/open/recordingPlan/delete", map[string]any{"code": strings.TrimSpace(code)})
}

func (c *Client) AddTaskPlan(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/taskPlan/add", payload)
}

func (c *Client) ListTaskPlans(payload map[string]any) ([]map[string]any, error) {
	return c.postOpenList("/open/taskPlan/list", payload)
}

func (c *Client) EditTaskPlan(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/taskPlan/edit", payload)
}

func (c *Client) DeleteTaskPlan(code string) (map[string]any, error) {
	return c.postOpenMap("/open/taskPlan/delete", map[string]any{"code": strings.TrimSpace(code)})
}

func (c *Client) ListRecordingFiles(payload map[string]any) ([]map[string]any, error) {
	return c.postOpenList("/open/recording/file/list", payload)
}

func (c *Client) GetRecordingFilePlayURL(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/recording/file/playUrl", payload)
}

func (c *Client) StartRecording(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/recording/startRecording", payload)
}

func (c *Client) StopRecording(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/recording/stopRecording", payload)
}

func (c *Client) CaptureSnapshot(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/recording/captureSnapshot", payload)
}

func (c *Client) ListFaces() (map[string]any, error) {
	return c.postOpenMap("/open/face/list", map[string]any{})
}

func (c *Client) AddFace(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/face/add", payload)
}

func (c *Client) DeleteFace(faceID string) (map[string]any, error) {
	return c.postOpenMap("/open/face/delete", map[string]any{"id": strings.TrimSpace(faceID)})
}

func (c *Client) SearchFace(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/face/search", payload)
}

func (c *Client) EnableFaceSearch() (map[string]any, error) {
	return c.postOpenMap("/open/face/enable", map[string]any{})
}

func (c *Client) DisableFaceSearch() (map[string]any, error) {
	return c.postOpenMap("/open/face/disable", map[string]any{})
}

func (c *Client) CloudPresignImage(payload map[string]any) (map[string]any, error) {
	return c.postCloudMap("/open/cloud/v1/presign/image", payload)
}

func (c *Client) CloudIngestAlarmCreated(payload map[string]any) (*APIResponse, error) {
	return c.postCloudJSON("/open/cloud/v1/events/alarm-created", payload)
}

func (c *Client) OpsCleanup(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/ops/cleanup", payload)
}

func (c *Client) OpsOutboxReplay(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/ops/outbox/replay", payload)
}

func (c *Client) OpsSetLoggingLevel(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/ops/logging/level", payload)
}

func (c *Client) OpsHealth() (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery("/open/ops/health", nil, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) OpsReady() (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery("/open/ops/ready", nil, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) OpsMetrics() (string, error) {
	body, err := c.getRaw("/open/ops/metrics", nil, c.openAPIToken)
	if err != nil {
		return "", err
	}
	return string(body), nil
}

func (c *Client) OpsAuditExport(format string) ([]byte, error) {
	params := map[string]string{"format": strings.TrimSpace(format)}
	return c.getRaw("/open/ops/audit/export", params, c.openAPIToken)
}

func (c *Client) OpsDiagnosticsExport(params map[string]string) ([]byte, error) {
	return c.getRaw("/open/ops/diagnostics/export", params, c.openAPIToken)
}

func (c *Client) OpsUpgradeList(onlyCompatible bool) ([]map[string]any, error) {
	params := map[string]string{}
	if onlyCompatible {
		params["only_compatible"] = "1"
	}
	return c.getOpenList("/open/ops/upgrade/list", params)
}

func (c *Client) OpsUpgradeValidate(packageID string) (map[string]any, error) {
	return c.getOpenMap("/open/ops/upgrade/validate", map[string]string{"package_id": strings.TrimSpace(packageID)})
}

func (c *Client) OpsUpgradeApply(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/ops/upgrade/apply", payload)
}

func (c *Client) OpsUpgradeRollback() (map[string]any, error) {
	return c.postOpenMap("/open/ops/upgrade/rollback", map[string]any{})
}

func (c *Client) OpsUpgradeUpload(fileName string, content []byte, contentType string) (map[string]any, error) {
	if strings.TrimSpace(contentType) == "" {
		contentType = "application/zip"
	}
	return c.postOpenMultipart("/open/ops/upgrade/upload", "file", fileName, content, contentType)
}

func (c *Client) ImageDetect(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/algorithm/imageDetect", payload)
}

func (c *Client) AudioDetect(payload map[string]any) (map[string]any, error) {
	return c.postOpenMap("/open/algorithm/audioDetect", payload)
}

func (c *Client) Discover() (map[string]any, error) {
	env, err := c.getOpenEnvelope("/open/discover", nil)
	if err != nil {
		return nil, err
	}
	info, _ := env["info"].(map[string]any)
	if info == nil {
		info = map[string]any{}
	}
	return info, nil
}

func (c *Client) GetAllStreamDataOpen() ([]map[string]any, error) {
	return c.getOpenList("/open/getAllStreamData", nil)
}

func (c *Client) GetAllAlgorithmFlowDataOpen() ([]map[string]any, error) {
	return c.getOpenList("/open/getAllAlgroithmFlowData", nil)
}

func (c *Client) GetAllCoreProcessDataOpen() (map[string]any, error) {
	env, err := c.getOpenEnvelope("/open/getAllCoreProcessData", nil)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"data": env["data"],
		"info": env["info"],
	}, nil
}

func (c *Client) GetAllCoreProcessData2Open() (map[string]any, error) {
	env, err := c.getOpenEnvelope("/open/getAllCoreProcessData2", nil)
	if err != nil {
		return nil, err
	}
	info, _ := env["info"].(map[string]any)
	if info == nil {
		info = map[string]any{}
	}
	return info, nil
}

func (c *Client) RestartSoftware() (*APIResponse, error) {
	return c.postJSON("/open/platform/restartSoftware", map[string]any{}, c.openAPIToken)
}

func (c *Client) RestartSystem() (*APIResponse, error) {
	return c.postJSON("/open/platform/restartSystem", map[string]any{}, c.openAPIToken)
}

func (c *Client) DownloadFile(relPath string) ([]byte, error) {
	parts := []string{}
	for _, part := range strings.Split(strings.TrimLeft(strings.TrimSpace(relPath), "/"), "/") {
		if part == "" {
			continue
		}
		parts = append(parts, url.PathEscape(part))
	}
	return c.getRaw("/open/fileService/"+strings.Join(parts, "/"), nil, c.openAPIToken)
}

func (c *Client) getData(path string, target any) (*APIResponse, error) {
	return c.getDataWithQuery(path, nil, "", target)
}

func (c *Client) getOpenEnvelope(path string, params map[string]string) (map[string]any, error) {
	body, err := c.getRaw(path, params, c.openAPIToken)
	if err != nil {
		return nil, err
	}
	env := map[string]any{}
	if err := json.Unmarshal(body, &env); err != nil {
		return nil, err
	}
	return env, nil
}

func (c *Client) getOpenMap(path string, params map[string]string) (map[string]any, error) {
	data := map[string]any{}
	if _, err := c.getDataWithQuery(path, params, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func (c *Client) getOpenList(path string, params map[string]string) ([]map[string]any, error) {
	var data []map[string]any
	if _, err := c.getDataWithQuery(path, params, c.openAPIToken, &data); err != nil {
		return nil, err
	}
	if data == nil {
		data = []map[string]any{}
	}
	return data, nil
}

func (c *Client) postOpenMap(path string, payload map[string]any) (map[string]any, error) {
	resp, err := c.postJSON(path, payload, c.openAPIToken)
	if err != nil {
		return nil, err
	}
	data := map[string]any{}
	if len(resp.Data) > 0 && string(resp.Data) != "null" {
		if err := json.Unmarshal(resp.Data, &data); err != nil {
			return nil, err
		}
	}
	return data, nil
}

func (c *Client) postOpenList(path string, payload map[string]any) ([]map[string]any, error) {
	resp, err := c.postJSON(path, payload, c.openAPIToken)
	if err != nil {
		return nil, err
	}
	var data []map[string]any
	if len(resp.Data) > 0 && string(resp.Data) != "null" {
		if err := json.Unmarshal(resp.Data, &data); err != nil {
			return nil, err
		}
	}
	if data == nil {
		data = []map[string]any{}
	}
	return data, nil
}

func (c *Client) postCloudMap(path string, payload map[string]any) (map[string]any, error) {
	resp, err := c.postCloudJSON(path, payload)
	if err != nil {
		return nil, err
	}
	data := map[string]any{}
	if len(resp.Data) > 0 && string(resp.Data) != "null" {
		if err := json.Unmarshal(resp.Data, &data); err != nil {
			return nil, err
		}
	}
	return data, nil
}

func (c *Client) getRaw(path string, params map[string]string, token string) ([]byte, error) {
	req, err := http.NewRequest(http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	if len(params) > 0 {
		query := req.URL.Query()
		for key, value := range params {
			if strings.TrimSpace(key) == "" || strings.TrimSpace(value) == "" {
				continue
			}
			query.Set(key, strings.TrimSpace(value))
		}
		req.URL.RawQuery = query.Encode()
	}
	if strings.TrimSpace(token) != "" {
		req.Header.Set(headerBeaconToken, strings.TrimSpace(token))
	}
	res, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	return io.ReadAll(res.Body)
}

func (c *Client) getDataWithQuery(path string, params map[string]string, token string, target any) (*APIResponse, error) {
	req, err := http.NewRequest(http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	if len(params) > 0 {
		query := req.URL.Query()
		for key, value := range params {
			if strings.TrimSpace(key) == "" || strings.TrimSpace(value) == "" {
				continue
			}
			query.Set(key, strings.TrimSpace(value))
		}
		req.URL.RawQuery = query.Encode()
	}
	if strings.TrimSpace(token) != "" {
		req.Header.Set(headerBeaconToken, strings.TrimSpace(token))
	}
	resp, err := c.do(req)
	if err != nil {
		return nil, err
	}
	if target != nil && len(resp.Data) > 0 && string(resp.Data) != "null" {
		if err := json.Unmarshal(resp.Data, target); err != nil {
			return nil, err
		}
	}
	return resp, nil
}

func (c *Client) postJSON(path string, payload any, token string) (*APIResponse, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest(http.MethodPost, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set(headerContentType, "application/json")
	if strings.TrimSpace(token) != "" {
		req.Header.Set(headerBeaconToken, strings.TrimSpace(token))
	}
	return c.do(req)
}

func (c *Client) postOpenMultipart(path, fieldName, fileName string, content []byte, contentType string) (map[string]any, error) {
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	part, err := writer.CreateFormFile(fieldName, fileName)
	if err != nil {
		return nil, err
	}
	if _, err := part.Write(content); err != nil {
		return nil, err
	}
	if err := writer.Close(); err != nil {
		return nil, err
	}

	req, err := http.NewRequest(http.MethodPost, c.baseURL+path, &buf)
	if err != nil {
		return nil, err
	}
	req.Header.Set(headerContentType, writer.FormDataContentType())
	if strings.TrimSpace(c.openAPIToken) != "" {
		req.Header.Set(headerBeaconToken, strings.TrimSpace(c.openAPIToken))
	}

	resp, err := c.do(req)
	if err != nil {
		return nil, err
	}
	data := map[string]any{}
	if len(resp.Data) > 0 && string(resp.Data) != "null" {
		if err := json.Unmarshal(resp.Data, &data); err != nil {
			return nil, err
		}
	}
	return data, nil
}

func (c *Client) postCloudJSON(path string, payload any) (*APIResponse, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest(http.MethodPost, c.baseURL+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set(headerContentType, "application/json")
	if strings.TrimSpace(c.cloudEdgeToken) != "" {
		req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(c.cloudEdgeToken))
	}
	return c.do(req)
}

func (c *Client) do(req *http.Request) (*APIResponse, error) {
	res, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()

	body, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, err
	}

	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, &APIError{Message: "invalid JSON response"}
	}

	code, _ := payload["code"].(float64)
	msg, _ := payload["msg"].(string)
	if int(code) != 1000 {
		return nil, &APIError{
			Message: msg,
			Code:    int(code),
			Payload: payload,
		}
	}

	rawData := json.RawMessage("null")
	if data, ok := payload["data"]; ok {
		encoded, err := json.Marshal(data)
		if err != nil {
			return nil, err
		}
		rawData = encoded
	}

	return &APIResponse{
		Code: int(code),
		Msg:  msg,
		Data: rawData,
	}, nil
}

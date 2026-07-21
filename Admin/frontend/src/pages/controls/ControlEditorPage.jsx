import React, { useEffect, useRef, useMemo, useCallback, useState } from 'react';
import PropTypes from 'prop-types';
import {
  App,
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
} from 'antd';
import { AimOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import SkeletonPage from '../../components/Skeleton';
import { apiGet, apiPost } from '../../api/client';
import { API } from '../../api/endpoints';
import { getBootstrapQuery, getBootstrapPath } from '../../bootstrap';
import RecognitionRegionEditor from './RecognitionRegionEditor';

/** Maps `control` JSON (snake_case) to POST field names expected by `_parse_control_upsert_payload` / `_control_edit_full`. */
const CONTROL_SNAKE_TO_POST = {
  code: 'controlCode',
  stream_app: 'streamApp',
  stream_name: 'streamName',
  stream_video: 'streamVideo',
  stream_audio: 'streamAudio',
  object_code: 'objectCode',
  push_stream: 'pushStream',
  polygon: 'polygon',
  min_interval: 'minInterval',
  decode_stride: 'decodeStride',
  class_thresh: 'classThresh',
  overlap_thresh: 'overlapThresh',
  remark: 'remark',
  alarm_sound_id: 'alarmSoundId',
  alarm_video_type: 'alarmVideoType',
  alarm_image_count: 'alarmImageCount',
  alarm_image_draw_mode: 'alarmImageDrawMode',
  force_frame_alarm: 'forceFrameAlarm',
  alarm_cover_position: 'alarmCoverPosition',
  alarm_cover_custom_index: 'alarmCoverCustomIndex',
  use_pipeline_mode: 'usePipelineMode',
  algorithm_pipeline_mode: 'pipelineMode',
  enable_hw_decode: 'enableHardwareDecode',
  enable_hw_encode: 'enableHardwareEncode',
  draw_type: 'drawType',
  line_coordinates: 'lineCoordinates',
  line_violation_direction: 'lineViolationDirection',
  enable_tracking: 'enableTracking',
  tracking_config: 'trackingConfig',
  classification_algorithm_code: 'classificationAlgorithmCode',
  classification_config: 'classificationConfig',
  feature_algorithm_code: 'featureAlgorithmCode',
  feature_config: 'featureConfig',
  behavior_algorithm_code: 'behaviorAlgorithmCode',
  behavior_api_url: 'behaviorApiUrl',
  behavior_config: 'behaviorConfig',
  analysis_prompt: 'analysisPrompt',
  enable_hierarchical_algorithm: 'enableHierarchicalAlgorithm',
  secondary_algorithm_code: 'secondaryAlgorithmCode',
  secondary_api_url: 'secondaryApiUrl',
  secondary_conf_thresh: 'secondaryConfThresh',
  osd_enabled: 'osdEnabled',
  osd_text: 'osdText',
  osd_position: 'osdPosition',
  osd_x: 'osdX',
  osd_y: 'osdY',
  osd_font_size: 'osdFontSize',
  osd_font_color: 'osdFontColor',
  osd_bg_enabled: 'osdBgEnabled',
  osd_image_path: 'osdImagePath',
  osd_image_x: 'osdImageX',
  osd_image_y: 'osdImageY',
  osd_image_scale: 'osdImageScale',
  osd_image_alpha: 'osdImageAlpha',
  osd_algo_x: 'osdAlgoX',
  osd_algo_y: 'osdAlgoY',
  osd_fps_x: 'osdFpsX',
  osd_fps_y: 'osdFpsY',
  osd_font_thickness: 'osdFontThickness',
};

const STREAM_SEP = '\u001e';

const ALARM_VIDEO_TYPES = [
  { value: 'mp4', label: 'mp4' },
  { value: 'gif', label: 'gif' },
];

const ALARM_DRAW_MODES = [
  { value: 'boxed', label: 'boxed' },
  { value: 'clean', label: 'clean' },
  { value: 'both', label: 'both' },
];

const ALARM_COVER_POSITION_OPTIONS = [
  { value: 'back', label: '最后一帧（推荐）' },
  { value: 'middle', label: '中间帧' },
  { value: 'front', label: '起始触发帧' },
  { value: 'custom', label: '自定义帧序号' },
];

const OSD_POSITION_OPTIONS = [
  { value: 'top-left', label: '左上' },
  { value: 'top-right', label: '右上' },
  { value: 'bottom-left', label: '左下' },
  { value: 'bottom-right', label: '右下' },
  { value: 'custom', label: '自定义' },
];

function joinAlgorithmCode(base, device) {
  const b = String(base || '').trim();
  const d = String(device || 'CPU').trim();
  if (!b) return '';
  const u = d.toUpperCase();
  if (u === 'CPU') return `${b}_cpu`;
  if (u === 'GPU') return `${b}_gpu`;
  if (u.startsWith('GPU:')) return `${b}_gpu${u.slice(4)}`;
  if (u === 'TRT') return `${b}_trt`;
  if (u.startsWith('TRT:')) return `${b}_trt${u.slice(4)}`;
  if (u === 'AUTO') return `${b}_auto`;
  if (u === 'NPU') return `${b}_npu`;
  return `${b}_cpu`;
}

function joinTrackingAlgorithmCode(base, device, deviceId) {
  const b = String(base || '').trim();
  if (!b) return '';
  const d = String(device || 'CPU').toUpperCase();
  const id = String(deviceId || '').trim();
  if (d === 'CPU') return `${b}_cpu`;
  if (d === 'GPU') return id ? `${b}_gpu${id}` : `${b}_gpu`;
  if (d === 'TRT') return id ? `${b}_trt${id}` : `${b}_trt`;
  if (d === 'AUTO') return `${b}_auto`;
  if (d === 'NPU') return `${b}_npu`;
  return `${b}_cpu`;
}

function controlSnakeToPostFlat(control) {
  const flat = {};
  for (const [snake, camel] of Object.entries(CONTROL_SNAKE_TO_POST)) {
    if (!Object.hasOwn(control, snake)) continue;
    const v = control[snake];
    if (v === undefined || v === null) continue;
    flat[camel] = v;
  }
  return flat;
}

function appendControlFormData(fd, flat) {
  Object.entries(flat).forEach(([k, v]) => {
    if (v === undefined || v === null) return;
    if (typeof v === 'boolean') {
      fd.append(k, v ? '1' : '0');
    } else {
      fd.append(k, String(v));
    }
  });
}

function buildAlgorithmOptions(algorithms, currentValue) {
  const opts = [];
  const seen = new Set();
  const variants = ['', '_cpu', '_gpu', '_auto', '_npu', '_trt'];
  for (const a of algorithms || []) {
    const base = String(a.code || '').trim();
    if (!base) continue;
    for (const s of variants) {
      const value = base + s;
      if (seen.has(value)) continue;
      seen.add(value);
      const suffix = s.replaceAll('_', '');
      const label = s ? `${a.name || base} ${suffix}` : (a.name || base);
      opts.push({ value, label });
    }
  }
  if (currentValue && !seen.has(currentValue)) {
    opts.unshift({ value: currentValue, label: `${currentValue}（当前）` });
  }
  return opts;
}

function resolveAlgorithmMeta(algorithmCode, algorithms) {
  const s = String(algorithmCode || '');
  let best = null;
  for (const a of algorithms || []) {
    const c = String(a.code || '');
    if (!c) continue;
    if (s === c || s.startsWith(`${c}_`)) {
      if (!best || c.length > String(best.code || '').length) best = a;
    }
  }
  return best;
}

function mergeStreamChoices(zlmStreams, dbRows) {
  const map = new Map();
  const add = (app, name, video, audio, label, code = '') => {
    const ap = String(app || '').trim();
    const nm = String(name || '').trim();
    if (!ap || !nm) return;
    const k = `${ap}${STREAM_SEP}${nm}`;
    if (map.has(k)) return;
    map.set(k, {
      code: String(code || '').trim(),
      app: ap,
      name: nm,
      video: String(video || '').trim() || 'video',
      audio: String(audio || '').trim() || 'audio',
      label: String(label || `${ap}/${nm}`),
    });
  };
  for (const s of zlmStreams || []) {
    add(s.app, s.name, s.video, s.audio, s.display_name, s.code || s.name);
  }
  for (const r of dbRows || []) {
    const app = r.app;
    const name = r.name;
    const label = r.nickname || r.code || (app && name ? `${app}/${name}` : '');
    add(app, name, 'video', 'audio', label, r.code || r.name);
  }
  return [...map.values()];
}

function buildControlEditorDefaults(payload) {
  return {
    control: payload.control ? { ...payload.control } : {},
    trackingAlgorithmCode: joinTrackingAlgorithmCode(
      payload.control_tracking_base,
      payload.control_tracking_device,
      payload.control_tracking_device_id,
    ),
  };
}

function valueOr(value, fallback = '') {
  return value || fallback;
}

function valueNullish(value, fallback) {
  return value ?? fallback;
}

function valueNumberOrZero(value) {
  return value == null ? 0 : Number(value);
}

function enabledUnlessFalse(value) {
  return value !== false;
}

function buildStreamComposite(control) {
  if (!control.stream_app || !control.stream_name) {
    return undefined;
  }
  return `${control.stream_app}${STREAM_SEP}${control.stream_name}`;
}

function streamLabelFromParts(app, name) {
  const streamApp = String(app || '').trim();
  const streamName = String(name || '').trim();
  if (!streamApp || !streamName) {
    return '';
  }
  return `${streamApp} / ${streamName}`;
}

function resolvePreviewStreamContext({
  isEdit,
  data,
  mergedStreams,
  streamComposite,
  fallbackStreamApp,
  fallbackStreamName,
}) {
  if (isEdit) {
    const streamApp = String(data?.control?.stream_app || '').trim();
    const streamName = String(data?.control?.stream_name || '').trim();
    return {
      code: String(data?.stream_preview?.stream_code || streamName || '').trim(),
      app: streamApp,
      name: streamName,
      label: streamLabelFromParts(streamApp, streamName),
    };
  }

  if (streamComposite) {
    const row = findStreamRow(mergedStreams, streamComposite);
    if (row) {
      return {
        code: String(row.code || row.name || '').trim(),
        app: row.app,
        name: row.name,
        label: row.label || streamLabelFromParts(row.app, row.name),
      };
    }
    const fallback = streamPartsFromComposite(streamComposite);
    return {
      code: String(fallback.name || '').trim(),
      app: fallback.app,
      name: fallback.name,
      label: streamLabelFromParts(fallback.app, fallback.name),
    };
  }

  return {
    code: String(fallbackStreamName || '').trim(),
    app: String(fallbackStreamApp || '').trim(),
    name: String(fallbackStreamName || '').trim(),
    label: streamLabelFromParts(fallbackStreamApp, fallbackStreamName),
  };
}

function buildControlEditorFormValues(payload) {
  const c = payload.control || {};
  const algo = joinAlgorithmCode(payload.control_algorithm_base, payload.control_algorithm_device);
  return {
    controlCode: c.code,
    algorithmCode: valueOr(algo, undefined),
    streamComposite: buildStreamComposite(c),
    stream_app: valueOr(c.stream_app),
    stream_name: valueOr(c.stream_name),
    object_code: c.object_code,
    polygon: c.polygon,
    min_interval: c.min_interval,
    class_thresh: c.class_thresh,
    overlap_thresh: c.overlap_thresh,
    push_stream: Boolean(c.push_stream),
    remark: c.remark,
    decode_stride: c.decode_stride,
    force_frame_alarm: Boolean(c.force_frame_alarm),
    alarm_sound_id: valueNullish(c.alarm_sound_id, 0),
    alarm_video_type: valueOr(c.alarm_video_type, 'mp4'),
    alarm_image_count: valueNullish(c.alarm_image_count, 3),
    alarm_image_draw_mode: valueOr(c.alarm_image_draw_mode, 'boxed'),
    alarm_cover_position: valueOr(c.alarm_cover_position, 'back'),
    alarm_cover_custom_index: valueNullish(c.alarm_cover_custom_index, 0),
    osd_enabled: Boolean(c.osd_enabled),
    osd_text: valueOr(c.osd_text),
    osd_position: valueOr(c.osd_position, 'top-left'),
    osd_x: valueNullish(c.osd_x, 10),
    osd_y: valueNullish(c.osd_y, 30),
    osd_font_size: valueNullish(c.osd_font_size, 24),
    osd_font_color: valueOr(c.osd_font_color, '255,255,255'),
    osd_bg_enabled: c.osd_bg_enabled !== false,
    osd_image_path: valueOr(c.osd_image_path),
    osd_image_x: valueNullish(c.osd_image_x, 10),
    osd_image_y: valueNullish(c.osd_image_y, 10),
    osd_image_scale: valueNullish(c.osd_image_scale, 1),
    osd_image_alpha: valueNullish(c.osd_image_alpha, 1),
    osd_algo_x: valueNullish(c.osd_algo_x, 20),
    osd_algo_y: valueNullish(c.osd_algo_y, 80),
    osd_fps_x: valueNullish(c.osd_fps_x, 20),
    osd_fps_y: valueNullish(c.osd_fps_y, 140),
    osd_font_thickness: valueNullish(c.osd_font_thickness, 2),
  };
}

function findStreamRow(mergedStreams, composite) {
  const parts = String(composite || '').split(STREAM_SEP);
  const app = (parts[0] || '').trim();
  const name = (parts[1] || '').trim();
  return mergedStreams.find((s) => s.app === app && s.name === name) || null;
}

function streamPartsFromComposite(composite) {
  const parts = String(composite || '').split(STREAM_SEP);
  return {
    app: (parts[0] || '').trim(),
    name: (parts[1] || '').trim(),
  };
}

function assignControlFormValues(raw, values) {
  Object.assign(raw, {
    object_code: values.object_code,
    polygon: values.polygon,
    min_interval: values.min_interval,
    class_thresh: values.class_thresh,
    overlap_thresh: values.overlap_thresh,
    push_stream: values.push_stream,
    remark: values.remark,
    decode_stride: values.decode_stride,
    force_frame_alarm: values.force_frame_alarm,
    alarm_sound_id: valueNumberOrZero(values.alarm_sound_id),
    alarm_video_type: valueOr(values.alarm_video_type, 'mp4'),
    alarm_image_count: valueNullish(values.alarm_image_count, 3),
    alarm_image_draw_mode: valueOr(values.alarm_image_draw_mode, 'boxed'),
    alarm_cover_position: valueOr(values.alarm_cover_position, 'back'),
    alarm_cover_custom_index: valueNullish(values.alarm_cover_custom_index, 0),
    osd_enabled: Boolean(values.osd_enabled),
    osd_text: valueOr(values.osd_text),
    osd_position: valueOr(values.osd_position, 'top-left'),
    osd_x: valueNullish(values.osd_x, 10),
    osd_y: valueNullish(values.osd_y, 30),
    osd_font_size: valueNullish(values.osd_font_size, 24),
    osd_font_color: valueOr(values.osd_font_color, '255,255,255'),
    osd_bg_enabled: enabledUnlessFalse(values.osd_bg_enabled),
    osd_image_path: valueOr(values.osd_image_path),
    osd_image_x: valueNullish(values.osd_image_x, 10),
    osd_image_y: valueNullish(values.osd_image_y, 10),
    osd_image_scale: valueNullish(values.osd_image_scale, 1),
    osd_image_alpha: valueNullish(values.osd_image_alpha, 1),
    osd_algo_x: valueNullish(values.osd_algo_x, 20),
    osd_algo_y: valueNullish(values.osd_algo_y, 80),
    osd_fps_x: valueNullish(values.osd_fps_x, 20),
    osd_fps_y: valueNullish(values.osd_fps_y, 140),
    osd_font_thickness: valueNullish(values.osd_font_thickness, 2),
  });
}

function applySelectedStream(raw, row) {
  raw.stream_app = row.app;
  raw.stream_name = row.name;
  raw.stream_video = row.video;
  raw.stream_audio = row.audio;
}

function applyFallbackStream(raw, app, name) {
  raw.stream_app = app;
  raw.stream_name = name;
  raw.stream_video = raw.stream_video || 'video';
  raw.stream_audio = raw.stream_audio || 'audio';
}

function assignAddStreamValues(raw, values, mergedStreams) {
  if (values.streamComposite) {
    const row = findStreamRow(mergedStreams, values.streamComposite);
    if (row) {
      applySelectedStream(raw, row);
      return;
    }
    const parts = streamPartsFromComposite(values.streamComposite);
    applyFallbackStream(raw, parts.app, parts.name);
    return;
  }
  applyFallbackStream(
    raw,
    String(values.stream_app || '').trim(),
    String(values.stream_name || '').trim(),
  );
}

function buildControlPostFlat({ values, defaults, isEdit, mergedStreams }) {
  const raw = { ...defaults.control };
  assignControlFormValues(raw, values);
  if (!isEdit) {
    assignAddStreamValues(raw, values, mergedStreams);
  }
  const flat = controlSnakeToPostFlat(raw);
  flat.algorithmCode = values.algorithmCode;
  flat.controlCode = values.controlCode;
  flat.trackingAlgorithmCode = defaults.trackingAlgorithmCode || '';
  return flat;
}

function MissingControlCodeState() {
  return (
    <div>
      <PageHeader title="编辑布控" description="布控规则编辑与配置" icon={<AimOutlined />} extra={<Button href="/controls">返回列表</Button>} />
      <Alert type="error" message="缺少布控编号参数 code" showIcon />
    </div>
  );
}

function ControlStreamFields({ isEdit, data, streamOptions }) {
  if (isEdit) {
    return <ControlReadonlyStream data={data} />;
  }
  if (streamOptions.length > 0) {
    return (
      <Form.Item
        name="streamComposite"
        label="视频流"
        rules={[{ required: true, message: '请选择视频流' }]}
      >
        <Select
          options={streamOptions}
          showSearch
          optionFilterProp="label"
          placeholder="选择 ZLM 在线流或已登记流"
        />
      </Form.Item>
    );
  }
  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="未获取到流列表，请手动填写 stream_app / stream_name（须与媒体服务一致）。"
      />
      <Form.Item name="stream_app" label="stream_app" rules={[{ required: true }]}>
        <Input placeholder="例如 live" />
      </Form.Item>
      <Form.Item name="stream_name" label="stream_name" rules={[{ required: true }]}>
        <Input placeholder="流名称" />
      </Form.Item>
    </>
  );
}

function ControlReadonlyStream({ data }) {
  if (!data?.control) {
    return null;
  }
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)', marginBottom: 4 }}>
        视频流（postEditControl 不修改拉流地址；需改流请删建或通过其它接口）
      </div>
      <Input
        readOnly
        value={
          data.control.stream_app && data.control.stream_name
            ? `${data.control.stream_app} / ${data.control.stream_name}`
            : ''
        }
      />
    </div>
  );
}

function ControlObjectField({ isEdit, showObjectSelect, editOptions, addOptions }) {
  if (showObjectSelect) {
    return (
      <Form.Item
        name="object_code"
        label="检测目标 object_code"
        rules={[{ required: true, message: '请选择或填写检测目标' }]}
      >
        <Select
          showSearch
          optionFilterProp="label"
          placeholder="选择目标类别"
          options={isEdit ? editOptions : addOptions}
        />
      </Form.Item>
    );
  }
  return (
    <Form.Item
      name="object_code"
      label="检测目标 object_code"
      rules={[{ required: true, message: '请填写检测目标' }]}
    >
      <Input placeholder="与算法 object 列表一致" />
    </Form.Item>
  );
}

function ControlStreamAlgorithmCard({
  isEdit,
  data,
  streamOptions,
  algorithmOptions,
  showObjectSelect,
  editObjectSelectOptions,
  addObjectSelectOptions,
}) {
  return (
    <Card title="视频流与算法" size="small" style={{ marginBottom: 16 }}>
      <ControlStreamFields isEdit={isEdit} data={data} streamOptions={streamOptions} />
      <Form.Item name="algorithmCode" label="算法 algorithmCode" rules={[{ required: true }]}>
        <Select
          options={algorithmOptions}
          showSearch
          optionFilterProp="label"
          placeholder="选择算法与运行设备后缀"
        />
      </Form.Item>
      <ControlObjectField
        isEdit={isEdit}
        showObjectSelect={showObjectSelect}
        editOptions={editObjectSelectOptions}
        addOptions={addObjectSelectOptions}
      />
    </Card>
  );
}

function ControlThresholdCard({
  previewImageUrl,
  previewLoading,
  previewError,
  onRefreshPreview,
  streamLabel,
}) {
  return (
    <Card title="区域与检测阈值" size="small" style={{ marginBottom: 16 }}>
      <Form.Item name="polygon" label="多边形 / ROI（polygon）">
        <RecognitionRegionEditor
          previewImageUrl={previewImageUrl}
          previewLoading={previewLoading}
          previewError={previewError}
          onRefreshPreview={onRefreshPreview}
          streamLabel={streamLabel}
        />
      </Form.Item>
      <Form.Item name="min_interval" label="报警间隔 minInterval（秒）">
        <InputNumber min={1} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="class_thresh" label="分类阈值 classThresh">
        <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="overlap_thresh" label="重叠阈值 overlapThresh">
        <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="decode_stride" label="解码步进 decodeStride">
        <InputNumber min={1} max={60} style={{ width: '100%' }} />
      </Form.Item>
    </Card>
  );
}

function ControlAlarmOutputCard({ alarmSoundOptions, form }) {
  const alarmCoverPosition = Form.useWatch('alarm_cover_position', form);

  return (
    <Card title="报警与输出" size="small" style={{ marginBottom: 16 }}>
      <Form.Item name="alarm_sound_id" label="报警铃声">
        <Select options={alarmSoundOptions} optionFilterProp="label" />
      </Form.Item>
      <Form.Item name="alarm_video_type" label="报警视频类型">
        <Select options={ALARM_VIDEO_TYPES} />
      </Form.Item>
      <Form.Item name="alarm_image_count" label="报警图片张数">
        <InputNumber min={1} max={20} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="alarm_image_draw_mode" label="报警图绘制模式">
        <Select options={ALARM_DRAW_MODES} />
      </Form.Item>
      <Form.Item
        name="alarm_cover_position"
        label="告警封面帧"
        tooltip="推荐使用最后一帧或中间帧，避免封面图只有区域线但没有检测框。"
      >
        <Select options={ALARM_COVER_POSITION_OPTIONS} />
      </Form.Item>
      {alarmCoverPosition === 'custom' ? (
        <Form.Item
          name="alarm_cover_custom_index"
          label="自定义封面帧序号"
          tooltip="从 1 开始计数，超出范围时会回退到系统可用帧。"
        >
          <InputNumber min={1} max={9999} style={{ width: '100%' }} />
        </Form.Item>
      ) : null}
      <Form.Item name="force_frame_alarm" label="强制帧报警 forceFrameAlarm" valuePropName="checked">
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <Form.Item name="push_stream" label="推流 pushStream" valuePropName="checked">
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
    </Card>
  );
}

function ControlOsdCustomPosition({ visible }) {
  if (!visible) {
    return null;
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      <Form.Item name="osd_x" label="OSD X">
        <InputNumber min={0} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="osd_y" label="OSD Y">
        <InputNumber min={0} style={{ width: '100%' }} />
      </Form.Item>
    </div>
  );
}

function osdAcceptText(values) {
  return values.length > 0 ? values.join(', ') : 'png, jpg, jpeg, webp';
}

function osdInputAccept(values) {
  return values.length > 0 ? values.map((ext) => `.${ext}`).join(',') : 'image/*';
}

function ControlOsdAssets({
  form,
  osdAssetOptions,
  osdAssetBaseUrl,
  osdAssetAccept,
  osdAssetLoading,
  osdUploading,
  onRefresh,
  onUploadFileChange,
  onUpload,
}) {
  return (
    <>
      <Form.Item name="osd_image_path" label="OSD贴图路径">
        <Input placeholder="osd/20260330/logo.png" />
      </Form.Item>
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 6, fontSize: 12, color: '#64748b' }}>
          已上传贴图 {osdAssetBaseUrl ? `(${osdAssetBaseUrl})` : ''}
        </div>
        <Space wrap>
          <Select
            placeholder="从贴图库选择"
            style={{ minWidth: 360 }}
            options={osdAssetOptions}
            optionFilterProp="label"
            showSearch
            loading={osdAssetLoading}
            onChange={(value) => form.setFieldValue('osd_image_path', value)}
            value={undefined}
          />
          <Button onClick={onRefresh} loading={osdAssetLoading}>刷新贴图</Button>
        </Space>
        <div style={{ marginTop: 8, fontSize: 12, color: '#64748b' }}>
          支持格式：{osdAcceptText(osdAssetAccept)}
        </div>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label htmlFor="osdAssetUpload" style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>
          上传贴图
        </label>
        <Space wrap>
          <Input
            id="osdAssetUpload"
            aria-label="上传贴图"
            type="file"
            accept={osdInputAccept(osdAssetAccept)}
            onChange={(e) => onUploadFileChange(e.target.files?.[0] || null)}
            style={{ maxWidth: 320 }}
          />
          <Button onClick={onUpload} loading={osdUploading}>上传贴图</Button>
        </Space>
      </div>
    </>
  );
}

function ControlOsdCard({
  form,
  osdPosition,
  osdAssetOptions,
  osdAssetBaseUrl,
  osdAssetAccept,
  osdAssetLoading,
  osdUploading,
  onRefreshOsdAssets,
  onOsdUploadFileChange,
  onOsdUpload,
}) {
  return (
    <Card title="推流 OSD（文字 / 贴图）" size="small" style={{ marginBottom: 16 }}>
      <Form.Item name="osd_enabled" label="启用 OSD" valuePropName="checked">
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <Form.Item name="osd_text" label="OSD 文字">
        <Input placeholder="例如：{time} {stream_name} {algorithm_name}" />
      </Form.Item>
      <Form.Item name="osd_position" label="OSD 位置">
        <Select options={OSD_POSITION_OPTIONS} />
      </Form.Item>
      <ControlOsdCustomPosition visible={osdPosition === 'custom'} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <Form.Item name="osd_font_size" label="字体大小">
          <InputNumber min={1} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="osd_font_color" label="字体颜色 RGB">
          <Input placeholder="255,255,255" />
        </Form.Item>
      </div>
      <Form.Item name="osd_bg_enabled" label="文字背景" valuePropName="checked">
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <ControlOsdAssets
        form={form}
        osdAssetOptions={osdAssetOptions}
        osdAssetBaseUrl={osdAssetBaseUrl}
        osdAssetAccept={osdAssetAccept}
        osdAssetLoading={osdAssetLoading}
        osdUploading={osdUploading}
        onRefresh={onRefreshOsdAssets}
        onUploadFileChange={onOsdUploadFileChange}
        onUpload={onOsdUpload}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
        <Form.Item name="osd_image_x" label="贴图 X">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="osd_image_y" label="贴图 Y">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="osd_image_scale" label="贴图缩放">
          <InputNumber min={0.1} step={0.1} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="osd_image_alpha" label="贴图透明度">
          <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
        </Form.Item>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <Form.Item name="osd_algo_x" label="算法名 X">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="osd_algo_y" label="算法名 Y">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="osd_font_thickness" label="字体粗细">
          <InputNumber min={1} style={{ width: '100%' }} />
        </Form.Item>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <Form.Item name="osd_fps_x" label="FPS X">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="osd_fps_y" label="FPS Y">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
      </div>
    </Card>
  );
}

function ControlOtherCard() {
  return (
    <Card title="其它" size="small" style={{ marginBottom: 16 }}>
      <Form.Item name="remark" label="备注">
        <Input.TextArea rows={2} />
      </Form.Item>
    </Card>
  );
}

ControlStreamFields.propTypes = {
  isEdit: PropTypes.bool,
  data: PropTypes.object,
  streamOptions: PropTypes.array,
};

ControlReadonlyStream.propTypes = {
  data: PropTypes.object,
};

ControlObjectField.propTypes = {
  isEdit: PropTypes.bool,
  showObjectSelect: PropTypes.bool,
  editOptions: PropTypes.array,
  addOptions: PropTypes.array,
};

ControlStreamAlgorithmCard.propTypes = {
  isEdit: PropTypes.bool,
  data: PropTypes.object,
  streamOptions: PropTypes.array,
  algorithmOptions: PropTypes.array,
  showObjectSelect: PropTypes.bool,
  editObjectSelectOptions: PropTypes.array,
  addObjectSelectOptions: PropTypes.array,
};

ControlAlarmOutputCard.propTypes = {
  alarmSoundOptions: PropTypes.array,
  form: PropTypes.object.isRequired,
};

ControlThresholdCard.propTypes = {
  previewImageUrl: PropTypes.string,
  previewLoading: PropTypes.bool,
  previewError: PropTypes.string,
  onRefreshPreview: PropTypes.func,
  streamLabel: PropTypes.string,
};

ControlOsdCustomPosition.propTypes = {
  visible: PropTypes.bool,
};

ControlOsdAssets.propTypes = {
  form: PropTypes.object,
  osdAssetOptions: PropTypes.array,
  osdAssetBaseUrl: PropTypes.string,
  osdAssetAccept: PropTypes.array,
  osdAssetLoading: PropTypes.bool,
  osdUploading: PropTypes.bool,
  onRefresh: PropTypes.func,
  onUploadFileChange: PropTypes.func,
  onUpload: PropTypes.func,
};

ControlOsdCard.propTypes = {
  form: PropTypes.object,
  osdPosition: PropTypes.string,
  osdAssetOptions: PropTypes.array,
  osdAssetBaseUrl: PropTypes.string,
  osdAssetAccept: PropTypes.array,
  osdAssetLoading: PropTypes.bool,
  osdUploading: PropTypes.bool,
  onRefreshOsdAssets: PropTypes.func,
  onOsdUploadFileChange: PropTypes.func,
  onOsdUpload: PropTypes.func,
};

export default function ControlEditorPage() {
  const { message } = App.useApp();
  const query = getBootstrapQuery();
  const path = getBootstrapPath();
  const code = (query.get('code') || '').trim();
  const isEdit = path === '/control/edit';

  const defaultsRef = useRef({ control: {}, trackingAlgorithmCode: '' });
  const [form] = Form.useForm();
  const [data, setData] = useState(null);
  const [dbStreamRows, setDbStreamRows] = useState([]);
  const [osdAssets, setOsdAssets] = useState([]);
  const [osdAssetAccept, setOsdAssetAccept] = useState([]);
  const [osdAssetBaseUrl, setOsdAssetBaseUrl] = useState('');
  const [osdAssetLoading, setOsdAssetLoading] = useState(false);
  const [osdUploading, setOsdUploading] = useState(false);
  const [osdUploadFile, setOsdUploadFile] = useState(null);
  const [previewImageUrl, setPreviewImageUrl] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [previewRefreshSeed, setPreviewRefreshSeed] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const applyOsdAssetPayload = useCallback((payload, fallback = {}) => {
    let nextRows = [];
    if (Array.isArray(fallback.rows)) {
      nextRows = fallback.rows;
    }
    if (Array.isArray(payload?.rows)) {
      nextRows = payload.rows;
    }
    setOsdAssets(nextRows);
    setOsdAssetAccept(Array.isArray(payload?.accept) ? payload.accept : []);
    setOsdAssetBaseUrl(payload?.base_url || fallback.base_url || '');
  }, []);

  const hydrateForm = useCallback(
    (payload) => {
      defaultsRef.current = buildControlEditorDefaults(payload);
      form.setFieldsValue(buildControlEditorFormValues(payload));
    },
    [form],
  );

  useEffect(() => {
    if (isEdit && !code) {
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const editorParams = isEdit && code ? { code } : {};
        const [editorPayload, streamsPayload, osdAssetPayload] = await Promise.all([
          apiGet(API.controlEditor, editorParams),
          apiGet(API.streams, { p: 1, ps: 500 }).catch(() => null),
          apiGet(API.controlOsdAssets).catch(() => null),
        ]);
        if (cancelled) return;
        setData(editorPayload);
        setDbStreamRows(streamsPayload?.rows || []);
        applyOsdAssetPayload(osdAssetPayload, {
          rows: editorPayload?.osd_assets || [],
          base_url: editorPayload?.osd_asset_base_url || '',
        });
        hydrateForm(editorPayload);
      } catch (e) {
        if (!cancelled) setLoadError(e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isEdit, code, hydrateForm, applyOsdAssetPayload]);

  const algorithms = data?.algorithms || [];
  const zlmStreams = data?.streams || [];
  const mergedStreams = useMemo(
    () => mergeStreamChoices(zlmStreams, dbStreamRows),
    [zlmStreams, dbStreamRows],
  );

  const streamOptions = useMemo(
    () =>
      mergedStreams.map((s) => ({
        value: `${s.app}${STREAM_SEP}${s.name}`,
        label: s.label,
      })),
    [mergedStreams],
  );

  const streamCompositeWatched = Form.useWatch('streamComposite', form);
  const fallbackStreamAppWatched = Form.useWatch('stream_app', form);
  const fallbackStreamNameWatched = Form.useWatch('stream_name', form);

  const algorithmCodeWatched = Form.useWatch('algorithmCode', form);
  const algorithmMeta = useMemo(
    () => resolveAlgorithmMeta(algorithmCodeWatched, algorithms),
    [algorithmCodeWatched, algorithms],
  );

  const addObjectSelectOptions = useMemo(() => {
    const raw = algorithmMeta?.object_options || [];
    return raw.map((o) => ({ value: o, label: o }));
  }, [algorithmMeta]);

  const editObjectSelectOptions = useMemo(() => {
    let opts = [...(data?.object_options || [])];
    const oc = String(data?.control?.object_code || '').trim();
    if (oc && !opts.includes(oc)) opts = [...opts, oc];
    return opts.map((o) => ({ value: o, label: o }));
  }, [data]);

  const algorithmOptions = useMemo(() => {
    const cur = data
      ? joinAlgorithmCode(data.control_algorithm_base, data.control_algorithm_device)
      : '';
    return buildAlgorithmOptions(algorithms, cur);
  }, [algorithms, data]);

  const alarmSoundOptions = useMemo(() => {
    const rows = (data?.alarm_sounds || []).map((s) => ({
      value: Number(s.id),
      label: s.is_default ? `${s.name}（默认）` : s.name,
    }));
    return [{ value: 0, label: '无' }, ...rows];
  }, [data]);

  const osdAssetOptions = useMemo(
    () =>
      (osdAssets || []).map((item) => ({
        value: item.path,
        label: item.name ? `${item.name} (${item.path})` : item.path,
      })),
    [osdAssets],
  );

  const osdPosition = Form.useWatch('osd_position', form);

  const previewStream = useMemo(
    () => resolvePreviewStreamContext({
      isEdit,
      data,
      mergedStreams,
      streamComposite: streamCompositeWatched,
      fallbackStreamApp: fallbackStreamAppWatched,
      fallbackStreamName: fallbackStreamNameWatched,
    }),
    [
      isEdit,
      data,
      mergedStreams,
      streamCompositeWatched,
      fallbackStreamAppWatched,
      fallbackStreamNameWatched,
    ],
  );

  const refreshPreviewFrame = useCallback(() => {
    setPreviewRefreshSeed((prev) => prev + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const streamCode = String(previewStream.code || '').trim();
    if (!streamCode) {
      setPreviewImageUrl('');
      setPreviewLoading(false);
      setPreviewError(previewStream.label ? '当前流缺少可抓拍编号，无法加载当前帧' : '');
      return undefined;
    }

    (async () => {
      try {
        setPreviewLoading(true);
        setPreviewError('');
        const payload = await apiPost(API.recordingSnapshot, {
          stream_code: streamCode,
          method: 'ffmpeg',
        });
        if (cancelled) return;
        const rawImageUrl = String(payload?.image_url || '').trim();
        if (!rawImageUrl) {
          setPreviewImageUrl('');
          setPreviewError('当前帧抓取成功，但没有返回预览图片地址');
          return;
        }
        const nextUrl = `${rawImageUrl}${rawImageUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
        setPreviewImageUrl(nextUrl);
      } catch (e) {
        if (!cancelled) {
          setPreviewImageUrl('');
          setPreviewError(e.message || '当前帧抓取失败');
        }
      } finally {
        if (!cancelled) {
          setPreviewLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [previewRefreshSeed, previewStream.code, previewStream.label]);

  const refreshOsdAssets = useCallback(async () => {
    setOsdAssetLoading(true);
    try {
      const payload = await apiGet(API.controlOsdAssets);
      applyOsdAssetPayload(payload, {
        rows: osdAssets,
        base_url: osdAssetBaseUrl,
      });
      message.success('贴图列表已刷新');
    } catch (e) {
      message.error(e.message || '贴图列表加载失败');
    } finally {
      setOsdAssetLoading(false);
    }
  }, [applyOsdAssetPayload, message, osdAssets, osdAssetBaseUrl]);

  const handleOsdUpload = useCallback(async () => {
    if (!osdUploadFile) {
      message.warning('请先选择贴图文件');
      return;
    }
    const formData = new FormData();
    formData.append('file', osdUploadFile);

    setOsdUploading(true);
    try {
      const payload = await apiPost(API.controlOsdAssetsUpload, formData);
      applyOsdAssetPayload(payload, {
        rows: osdAssets,
        base_url: osdAssetBaseUrl,
      });
      const newPath = payload?.asset?.path || '';
      if (newPath) {
        form.setFieldValue('osd_image_path', newPath);
      }
      setOsdUploadFile(null);
      message.success('贴图上传成功');
    } catch (e) {
      message.error(e.message || '贴图上传失败');
    } finally {
      setOsdUploading(false);
    }
  }, [applyOsdAssetPayload, form, message, osdAssetBaseUrl, osdAssets, osdUploadFile]);

  const onFinish = async (values) => {
    const flat = buildControlPostFlat({
      values,
      defaults: defaultsRef.current,
      isEdit,
      mergedStreams,
    });
    const fd = new FormData();
    appendControlFormData(fd, flat);

    setSubmitting(true);
    try {
      if (isEdit) {
        await apiPost(API.controlEditPost, fd);
        message.success('保存成功');
      } else {
        await apiPost(API.controlAdd, fd);
        message.success('添加成功');
      }
      globalThis.location.href = '/controls';
    } catch (e) {
      message.error(e.message || '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const showObjectSelect = isEdit
    ? editObjectSelectOptions.length > 0
    : addObjectSelectOptions.length > 0;

  if (isEdit && !code) {
    return <MissingControlCodeState />;
  }

  if (loading) {
    return <SkeletonPage />;
  }

  return (
    <div>
      <PageHeader
        title={isEdit ? `编辑布控 — ${code}` : '添加布控'}
        icon={<AimOutlined />}
        description="布控规则编辑与配置"
        extra={<Button href="/controls">返回列表</Button>}
      />

      {loadError ? (
        <Alert type="error" message={loadError.message || '加载失败'} showIcon style={{ marginBottom: 16 }} />
      ) : null}

      <Form
        form={form}
        layout="vertical"
        size="small"
        onFinish={onFinish}
        style={{ maxWidth: 900 }}
        disabled={!!loadError}
      >
        <ControlStreamAlgorithmCard
          isEdit={isEdit}
          data={data}
          streamOptions={streamOptions}
          algorithmOptions={algorithmOptions}
          showObjectSelect={showObjectSelect}
          editObjectSelectOptions={editObjectSelectOptions}
          addObjectSelectOptions={addObjectSelectOptions}
        />
        <ControlThresholdCard
          previewImageUrl={previewImageUrl}
          previewLoading={previewLoading}
          previewError={previewError}
          onRefreshPreview={refreshPreviewFrame}
          streamLabel={previewStream.label}
        />
        <ControlAlarmOutputCard alarmSoundOptions={alarmSoundOptions} form={form} />
        <ControlOsdCard
          form={form}
          osdPosition={osdPosition}
          osdAssetOptions={osdAssetOptions}
          osdAssetBaseUrl={osdAssetBaseUrl}
          osdAssetAccept={osdAssetAccept}
          osdAssetLoading={osdAssetLoading}
          osdUploading={osdUploading}
          onRefreshOsdAssets={refreshOsdAssets}
          onOsdUploadFileChange={setOsdUploadFile}
          onOsdUpload={handleOsdUpload}
        />
        <ControlOtherCard />

        <Form.Item name="controlCode" hidden>
          <Input />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {isEdit ? '保存' : '创建'}
          </Button>
        </Form.Item>
      </Form>
    </div>
  );
}

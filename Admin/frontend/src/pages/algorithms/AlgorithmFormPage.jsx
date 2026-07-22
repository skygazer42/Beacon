import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { Alert, App, Button, Card, Result, Space, Tag } from 'antd';
import {
  ApiOutlined,
  ExperimentOutlined,
  PlayCircleOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import {
  getBootstrapPath,
  getBootstrapQueryString,
} from '../../bootstrap';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';
import { readAlgorithmFormTemplate } from './algorithmFormTemplate';

const BASIC_SUBTYPES = new Set(['detection', 'classification', 'ocr', 'tracking', 'speech']);

const formGridStyle = {
  display: 'grid',
  gridTemplateColumns: '180px minmax(0, 1fr)',
  gap: 12,
  alignItems: 'start',
};

const panelStyle = {
  marginBottom: 16,
  borderRadius: 12,
};

const labelStyle = {
  fontSize: 13,
  fontWeight: 600,
  color: '#334155',
  paddingTop: 10,
  textAlign: 'right',
};

const fieldStyle = {
  width: '100%',
  minHeight: 38,
  padding: '8px 12px',
  borderRadius: 8,
  border: '1px solid #d9e2f2',
  background: '#fff',
  fontSize: 14,
};

const textareaStyle = {
  ...fieldStyle,
  minHeight: 96,
  resize: 'vertical',
};

const hintStyle = {
  marginTop: 6,
  color: '#64748b',
  fontSize: 12,
  lineHeight: 1.5,
  overflowWrap: 'anywhere',
};

const compactButtonsStyle = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 8,
};

function normalizeSubtype(algorithmType, algorithmSubtype) {
  if (algorithmType === 1 || algorithmType === 2) return 'behavior';
  if (BASIC_SUBTYPES.has(algorithmSubtype)) return algorithmSubtype;
  return 'detection';
}

function applyAlgorithmRules(nextValues) {
  const algorithmType = Number.parseInt(nextValues.algorithmType, 10) || 0;
  const algorithmSubtype = normalizeSubtype(algorithmType, nextValues.algorithmSubtype);
  let basicSource = nextValues.basicSource || 'model';

  if (algorithmType === 0 && algorithmSubtype === 'tracking') {
    basicSource = 'model';
  }

  if (algorithmType === 0 && algorithmSubtype === 'speech') {
    basicSource = 'api';
  }

  return {
    ...nextValues,
    algorithmType,
    algorithmSubtype,
    basicSource,
  };
}

function getModelExt(file) {
  if (!file?.name) return '';

  let name = String(file.name);
  if (name.toLowerCase().endsWith('.enc')) {
    name = name.slice(0, -4);
  }

  const idx = name.lastIndexOf('.');
  return idx >= 0 ? name.slice(idx).toLowerCase() : '';
}

function CardToggle({ active, title, description, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{
        textAlign: 'left',
        borderRadius: 12,
        border: active ? '1px solid #2563eb' : '1px solid #d9e2f2',
        background: active ? '#edf5ff' : '#fff',
        padding: 14,
        minHeight: 88,
        cursor: 'pointer',
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.5 }}>{description}</div>
    </button>
  );
}

CardToggle.propTypes = {
  active: PropTypes.bool.isRequired,
  title: PropTypes.node.isRequired,
  description: PropTypes.node,
  onClick: PropTypes.func.isRequired,
};

function getAlgorithmSubmitError({
  values,
  handle,
  modelFile,
  pairedFile,
  modelExt,
  isBasicAlgorithm,
  isBehaviorAlgorithm,
  resolvedApiUrl,
}) {
  if (!values.name.trim()) {
    return '请输入算法名称';
  }

  if (isBasicAlgorithm && values.algorithmSubtype === 'tracking') {
    return getTrackingSubmitError({ values, handle, modelFile, pairedFile, modelExt });
  }

  if (isBasicAlgorithm && values.algorithmSubtype === 'speech' && values.basicSource !== 'api') {
    return '语音/ASR 算法在 Wave 1 仅支持“API接口”方式';
  }

  if (isBasicAlgorithm && values.basicSource === 'api' && !resolvedApiUrl.trim()) {
    return 'API接口方式必须填写API地址';
  }

  if (isBehaviorAlgorithm && Number(values.behaviorApiVersion) === 2 && resolvedApiUrl.trim() && !values.builtinBehavior) {
    return 'APIv2 类型必须选择内置行为算法（用于本地后处理）';
  }

  return '';
}

function getTrackingSubmitError({ values, handle, modelFile, pairedFile, modelExt }) {
  if (values.basicSource !== 'model') {
    return '追踪(Tracking)算法仅支持“本地模型”方式';
  }

  if (handle === 'add' && !modelFile) {
    return '请上传追踪模型文件（.onnx 或 OpenVINO .xml + .bin）';
  }

  if (modelExt && modelExt !== '.onnx' && modelExt !== '.xml') {
    return '追踪(Tracking)算法仅支持 .onnx 或 OpenVINO .xml + .bin';
  }

  if (modelExt === '.xml' && handle === 'add' && !pairedFile) {
    return 'OpenVINO .xml 需要同时上传配套的 .bin 文件';
  }

  return '';
}

function AlgorithmFormHeader({ handle, popupMode }) {
  return (
    <>
      {popupMode ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Popup 模式"
          description="当前页面在无侧栏壳层中打开，保留历史算法弹窗工作流。"
        />
      ) : null}

      <PageHeader title={handle === 'edit' ? '编辑算法' : '添加算法'} icon={<ExperimentOutlined />} description="算法配置表单">
        {popupMode ? <Tag color="processing">Popup</Tag> : null}
      </PageHeader>
    </>
  );
}

function AlgorithmHiddenInputs({ handle, popupMode, values, resolvedApiUrl }) {
  return (
    <>
      <input type="hidden" name="handle" value={handle} />
      {popupMode ? <input type="hidden" name="popup" value="1" /> : null}
      <input type="hidden" name="algorithm_type" value={String(values.algorithmType)} />
      <input type="hidden" name="basic_source" value={values.basicSource} />
      <input type="hidden" name="algorithm_subtype" value={values.algorithmSubtype} />
      <input type="hidden" name="builtin_behavior" value={values.builtinBehavior} />
      <input type="hidden" name="api_url" value={resolvedApiUrl} />
    </>
  );
}

function AlgorithmTypeCard({ values, template, patchValues }) {
  return (
    <Card style={panelStyle}>
      <div style={formGridStyle}>
        <div style={labelStyle}>算法类型</div>
        <div style={compactButtonsStyle}>
          <CardToggle
            active={values.algorithmType === 0}
            title="基础算法"
            description="检测、分类、OCR、追踪、语音等基础能力。"
            onClick={() => patchValues({ algorithmType: 0 })}
          />
          <CardToggle
            active={values.algorithmType === 1}
            title="行为算法"
            description="行为分析与业务扩展，支持 API 和动态库接入。"
            onClick={() => patchValues({ algorithmType: 1 })}
          />
          <CardToggle
            active={values.algorithmType === 2}
            title="业务算法"
            description="业务场景自定义算法，复用行为/业务接入能力。"
            onClick={() => patchValues({ algorithmType: 2 })}
          />
        </div>

        <label htmlFor="code" style={labelStyle}>编号</label>
        <div>
          <input
            id="code"
            name="code"
            value={values.code}
            readOnly={template.fields.codeReadonly}
            onChange={event => patchValues({ code: event.target.value })}
            style={fieldStyle}
          />
        </div>

        <label htmlFor="name" style={labelStyle}>名称</label>
        <div>
          <input
            id="name"
            name="name"
            value={values.name}
            onChange={event => patchValues({ name: event.target.value })}
            style={fieldStyle}
          />
        </div>

        <label htmlFor="license_package" style={labelStyle}>授权算法包</label>
        <div>
          <input
            id="license_package"
            name="license_package"
            value={values.licensePackage}
            onChange={event => patchValues({ licensePackage: event.target.value })}
            style={fieldStyle}
          />
          <div style={hintStyle}>保持与后端 License SKU 契约一致，例如 `core` / `ppe` / `behavior_pro`。</div>
        </div>
      </div>
    </Card>
  );
}

function ModelConfigFields({ template, showPairedFile, setModelFile, setPairedFile }) {
  return (
    <>
      <label htmlFor="model_file" style={labelStyle}>模型文件</label>
      <div>
        {template.existingFiles.modelPath ? (
          <div style={{ marginBottom: 8, fontSize: 12, color: '#475569' }}>
            已上传: {template.existingFiles.modelPath}
          </div>
        ) : null}
        <input
          id="model_file"
          name="model_file"
          type="file"
          onChange={event => {
            setModelFile(event.target.files?.[0] || null);
            if (!event.target.files?.[0]) {
              setPairedFile(null);
            }
          }}
          style={fieldStyle}
        />
        <div style={hintStyle}>
          支持 `.pt/.pth/.onnx/.xml/.engine/.trt/.weights/.enc` 等模型格式。
        </div>
      </div>

      {showPairedFile ? (
        <>
          <label htmlFor="paired_file" style={labelStyle}>配套文件</label>
          <div>
            <input
              id="paired_file"
              name="paired_file"
              type="file"
              onChange={event => setPairedFile(event.target.files?.[0] || null)}
              style={fieldStyle}
            />
            <div style={hintStyle}>OpenVINO `.xml` 需要 `.bin`；YOLO `.weights` 需要 `.cfg`。</div>
          </div>
        </>
      ) : null}
    </>
  );
}

function BasicAlgorithmCard({
  values,
  template,
  subtypeOptions,
  modelPrecisionOptions,
  showModelConfig,
  showApiConfig,
  showObjectStr,
  showPairedFile,
  patchValues,
  setModelFile,
  setPairedFile,
}) {
  return (
    <Card style={panelStyle} title="基础算法配置">
      <div style={formGridStyle}>
        <label htmlFor="algorithmSubtype" style={labelStyle}>算法子类型</label>
        <div>
          <select
            id="algorithmSubtype"
            aria-label="算法子类型"
            value={values.algorithmSubtype}
            onChange={event => patchValues({ algorithmSubtype: event.target.value })}
            style={fieldStyle}
          >
            {subtypeOptions.map(option => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <div style={hintStyle}>追踪仅支持本地模型；语音在当前后端契约下仅支持 API 接口。</div>
        </div>

        <div style={labelStyle}>算法来源</div>
        <div style={compactButtonsStyle}>
          <CardToggle
            active={values.basicSource === 'model'}
            title="本地模型"
            description="上传模型文件，本地推理。"
            onClick={() => patchValues({ basicSource: 'model' })}
          />
          <CardToggle
            active={values.basicSource === 'api'}
            title="API接口"
            description="调用外部 API 进行推理。"
            onClick={() => patchValues({ basicSource: 'api' })}
          />
        </div>

        {showModelConfig ? (
          <ModelConfigFields
            template={template}
            showPairedFile={showPairedFile}
            setModelFile={setModelFile}
            setPairedFile={setPairedFile}
          />
        ) : null}

        {showApiConfig ? (
          <>
            <label htmlFor="apiUrl" style={labelStyle}>API地址</label>
            <div>
              <input
                id="apiUrl"
                aria-label="API地址"
                value={values.apiUrl}
                onChange={event => patchValues({ apiUrl: event.target.value })}
                style={fieldStyle}
              />
              <div style={hintStyle}>填写后端当前支持的远程推理接口地址。</div>
            </div>
          </>
        ) : null}

        {showObjectStr ? (
          <>
            <label htmlFor="object_str" style={labelStyle}>检测目标</label>
            <div>
              <input
                id="object_str"
                name="object_str"
                value={values.objectStr}
                onChange={event => patchValues({ objectStr: event.target.value })}
                style={fieldStyle}
              />
              <div style={hintStyle}>多个类别使用逗号分隔。</div>
            </div>
          </>
        ) : null}

        <label htmlFor="model_precision" style={labelStyle}>模型精度</label>
        <div>
          <select
            id="model_precision"
            name="model_precision"
            value={values.modelPrecision}
            onChange={event => patchValues({ modelPrecision: event.target.value })}
            style={fieldStyle}
          >
            {modelPrecisionOptions.map(option => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div style={labelStyle}>预处理尺寸</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <input
            id="input_width"
            name="input_width"
            aria-label="输入宽度"
            type="number"
            value={values.inputWidth}
            onChange={event => patchValues({ inputWidth: event.target.value })}
            style={fieldStyle}
          />
          <input
            id="input_height"
            name="input_height"
            aria-label="输入高度"
            type="number"
            value={values.inputHeight}
            onChange={event => patchValues({ inputHeight: event.target.value })}
            style={fieldStyle}
          />
        </div>

        <div style={labelStyle}>推理阈值</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <input
            id="conf_thresh"
            name="conf_thresh"
            aria-label="置信度阈值"
            type="number"
            min="0"
            max="1"
            step="0.01"
            value={values.confThresh}
            onChange={event => patchValues({ confThresh: event.target.value })}
            style={fieldStyle}
          />
          <input
            id="nms_thresh"
            name="nms_thresh"
            aria-label="NMS阈值"
            type="number"
            min="0"
            max="1"
            step="0.01"
            value={values.nmsThresh}
            onChange={event => patchValues({ nmsThresh: event.target.value })}
            style={fieldStyle}
          />
        </div>
      </div>
    </Card>
  );
}

function BehaviorAlgorithmCard({
  values,
  template,
  behaviorApiVersions,
  builtinBehaviorOptions,
  dllFile,
  patchValues,
  setDllFile,
}) {
  return (
    <Card style={panelStyle} title="行为 / 业务算法配置">
      <div style={formGridStyle}>
        <div style={labelStyle}>直接API模式</div>
        <div>
          <label htmlFor="support_direct_api" style={{ fontSize: 13, color: '#0f172a' }}>
            <input
              id="support_direct_api"
              name="support_direct_api"
              type="checkbox"
              checked={values.supportDirectApi}
              onChange={event => patchValues({ supportDirectApi: event.target.checked })}
              style={{ marginRight: 8 }}
            />
            <span>支持直接 API 调用（流程模式 5）</span>
          </label>
        </div>

        <label htmlFor="behavior_api_version" style={labelStyle}>API类型</label>
        <div>
          <select
            id="behavior_api_version"
            name="behavior_api_version"
            value={String(values.behaviorApiVersion)}
            onChange={event => patchValues({ behaviorApiVersion: Number(event.target.value) })}
            style={fieldStyle}
          >
            {behaviorApiVersions.map(option => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div style={labelStyle}>内置行为算法</div>
        <div style={compactButtonsStyle}>
          {builtinBehaviorOptions.map(option => (
            <button
              key={option.value}
              type="button"
              onClick={() => patchValues({ builtinBehavior: option.value })}
              style={{
                borderRadius: 999,
                border: values.builtinBehavior === option.value ? '1px solid #2563eb' : '1px solid #d9e2f2',
                background: values.builtinBehavior === option.value ? '#edf5ff' : '#fff',
                padding: '6px 12px',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              {option.label}
            </button>
          ))}
        </div>

        <label htmlFor="behaviorApiUrl" style={labelStyle}>自定义API</label>
        <div>
          <input
            id="behaviorApiUrl"
            value={values.apiUrlBehavior}
            onChange={event => patchValues({ apiUrlBehavior: event.target.value })}
            style={fieldStyle}
          />
        </div>

        <label htmlFor="dll_file" style={labelStyle}>动态库</label>
        <div>
          {template.existingFiles.dllPath ? (
            <div style={{ marginBottom: 8, fontSize: 12, color: '#475569' }}>
              已上传: {template.existingFiles.dllPath}
            </div>
          ) : null}
          <input
            id="dll_file"
            name="dll_file"
            type="file"
            onChange={event => setDllFile(event.target.files?.[0] || null)}
            style={fieldStyle}
          />
          {dllFile ? <div style={hintStyle}>当前选择: {dllFile.name}</div> : null}
        </div>

        <label htmlFor="object_str" style={labelStyle}>对象标识</label>
        <div>
          <input
            id="object_str"
            name="object_str"
            value={values.objectStr}
            onChange={event => patchValues({ objectStr: event.target.value })}
            style={fieldStyle}
          />
        </div>
      </div>
    </Card>
  );
}

function CommonAlgorithmCard({ values, patchValues }) {
  return (
    <Card style={panelStyle} title="通用参数">
      <div style={formGridStyle}>
        <label htmlFor="remark" style={labelStyle}>备注</label>
        <div>
          <textarea
            id="remark"
            name="remark"
            value={values.remark}
            onChange={event => patchValues({ remark: event.target.value })}
            style={textareaStyle}
          />
        </div>

        <label htmlFor="max_control_count" style={labelStyle}>布控数量上限</label>
        <div>
          <input
            id="max_control_count"
            name="max_control_count"
            type="number"
            value={values.maxControlCount}
            onChange={event => patchValues({ maxControlCount: event.target.value })}
            style={fieldStyle}
          />
        </div>

        <label htmlFor="model_concurrency" style={labelStyle}>模型并发数</label>
        <div>
          <input
            id="model_concurrency"
            name="model_concurrency"
            type="number"
            value={values.modelConcurrency}
            onChange={event => patchValues({ modelConcurrency: event.target.value })}
            style={fieldStyle}
          />
        </div>
      </div>

      <Space style={{ marginTop: 16 }}>
        <Button icon={<ApiOutlined />} href="/algorithm/index">
          返回列表
        </Button>
        <Button type="primary" htmlType="submit" icon={<SaveOutlined />}>
          提交
        </Button>
      </Space>
    </Card>
  );
}

function AlgorithmInferCard({
  visible,
  inferDevice,
  inferLoading,
  inferResult,
  setInferDevice,
  setInferFile,
  handleInferSubmit,
}) {
  if (!visible) {
    return null;
  }

  return (
    <Card style={panelStyle} title="算法测试（一次推理）">
      <div style={formGridStyle}>
        <label htmlFor="test_infer_device" style={labelStyle}>推理设备</label>
        <div>
          <select
            id="test_infer_device"
            value={inferDevice}
            onChange={event => setInferDevice(event.target.value)}
            style={fieldStyle}
          >
            <option value="CPU">CPU</option>
            <option value="GPU">GPU</option>
            <option value="TRT">TRT</option>
            <option value="AUTO">AUTO</option>
            <option value="NPU">NPU</option>
          </select>
        </div>

        <label htmlFor="test_infer_image" style={labelStyle}>测试图片</label>
        <div>
          <input
            id="test_infer_image"
            aria-label="测试图片"
            type="file"
            accept="image/*"
            onChange={event => setInferFile(event.target.files?.[0] || null)}
            style={fieldStyle}
          />
        </div>

        <div style={labelStyle}>执行</div>
        <div>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={inferLoading}
            aria-label="开始测试"
            onClick={handleInferSubmit}
          >
            开始测试
          </Button>
        </div>

        <div style={labelStyle}>结果</div>
        <pre
          style={{
            margin: 0,
            padding: 12,
            borderRadius: 10,
            border: '1px solid #d9e2f2',
            background: '#0f172a',
            color: '#dbeafe',
            minHeight: 140,
            overflow: 'auto',
          }}
        >
          {inferResult}
        </pre>
      </div>
    </Card>
  );
}

AlgorithmFormHeader.propTypes = {
  handle: PropTypes.string,
  popupMode: PropTypes.bool,
};

AlgorithmHiddenInputs.propTypes = {
  handle: PropTypes.string,
  popupMode: PropTypes.bool,
  values: PropTypes.object,
  resolvedApiUrl: PropTypes.string,
};

AlgorithmTypeCard.propTypes = {
  values: PropTypes.object,
  template: PropTypes.object,
  patchValues: PropTypes.func,
};

ModelConfigFields.propTypes = {
  template: PropTypes.object,
  showPairedFile: PropTypes.bool,
  setModelFile: PropTypes.func,
  setPairedFile: PropTypes.func,
};

BasicAlgorithmCard.propTypes = {
  values: PropTypes.object,
  template: PropTypes.object,
  subtypeOptions: PropTypes.array,
  modelPrecisionOptions: PropTypes.array,
  showModelConfig: PropTypes.bool,
  showApiConfig: PropTypes.bool,
  showObjectStr: PropTypes.bool,
  showPairedFile: PropTypes.bool,
  patchValues: PropTypes.func,
  setModelFile: PropTypes.func,
  setPairedFile: PropTypes.func,
};

BehaviorAlgorithmCard.propTypes = {
  values: PropTypes.object,
  template: PropTypes.object,
  behaviorApiVersions: PropTypes.array,
  builtinBehaviorOptions: PropTypes.array,
  dllFile: PropTypes.object,
  patchValues: PropTypes.func,
  setDllFile: PropTypes.func,
};

CommonAlgorithmCard.propTypes = {
  values: PropTypes.object,
  patchValues: PropTypes.func,
};

AlgorithmInferCard.propTypes = {
  visible: PropTypes.bool,
  inferDevice: PropTypes.string,
  inferLoading: PropTypes.bool,
  inferResult: PropTypes.string,
  setInferDevice: PropTypes.func,
  setInferFile: PropTypes.func,
  handleInferSubmit: PropTypes.func,
};

export default function AlgorithmFormPage() {
  const { message } = App.useApp();
  const path = getBootstrapPath();
  const queryString = getBootstrapQueryString();
  const template = readAlgorithmFormTemplate();
  const [values, setValues] = useState(() => applyAlgorithmRules(template?.values || {
    code: '',
    name: '',
    algorithmType: 0,
    basicSource: 'model',
    algorithmSubtype: 'detection',
    licensePackage: 'core',
    apiUrl: '',
    apiUrlBehavior: '',
    supportDirectApi: false,
    behaviorApiVersion: 1,
    builtinBehavior: '',
    objectStr: '',
    remark: '',
    maxControlCount: '0',
    modelConcurrency: '1',
    modelPrecision: 'FP32',
    inputWidth: '640',
    inputHeight: '640',
    confThresh: '0.25',
    nmsThresh: '0.45',
  }));
  const [modelFile, setModelFile] = useState(null);
  const [pairedFile, setPairedFile] = useState(null);
  const [dllFile, setDllFile] = useState(null);
  const [inferDevice, setInferDevice] = useState('CPU');
  const [inferFile, setInferFile] = useState(null);
  const [inferLoading, setInferLoading] = useState(false);
  const [inferResult, setInferResult] = useState('等待测试...');

  if (!template) {
    return (
      <Result
        status="warning"
        title="未找到算法表单模板"
        subTitle="当前页面缺少后端兼容模板，无法安全对齐现有 Django 表单契约。"
      />
    );
  }

  const handle = template.handle || 'add';
  const popupMode = template.popupMode;
  const subtypeOptions = template.options.subtypes || [];
  const modelPrecisionOptions = template.options.modelPrecisions || [];
  const behaviorApiVersions = template.options.behaviorApiVersions || [];
  const builtinBehaviorOptions = template.options.builtinBehaviors || [];
  const modelExt = getModelExt(modelFile);

  const isBasicAlgorithm = values.algorithmType === 0;
  const isBehaviorAlgorithm = !isBasicAlgorithm;
  const showModelConfig = isBasicAlgorithm && values.basicSource === 'model';
  const showApiConfig = isBasicAlgorithm && values.basicSource === 'api';
  const showObjectStr = !isBasicAlgorithm || values.algorithmSubtype !== 'tracking';
  const showPairedFile = showModelConfig && (modelExt === '.xml' || modelExt === '.weights');
  const resolvedApiUrl = isBasicAlgorithm ? values.apiUrl : values.apiUrlBehavior;
  const formAction = queryString ? `${path}?${queryString}` : path;

  function patchValues(patch) {
    setValues(prev => applyAlgorithmRules({ ...prev, ...patch }));
  }

  function handleFormSubmit(event) {
    const errorMessage = getAlgorithmSubmitError({
      values,
      handle,
      modelFile,
      pairedFile,
      modelExt,
      isBasicAlgorithm,
      isBehaviorAlgorithm,
      resolvedApiUrl,
    });
    if (errorMessage) {
      event.preventDefault();
      message.error(errorMessage);
    }
  }

  async function handleInferSubmit() {
    if (!values.code) {
      message.warning('缺少算法编号');
      return;
    }

    if (!inferFile) {
      message.warning('请先选择测试图片');
      return;
    }

    const formData = new FormData();
    formData.append('code', values.code);
    formData.append('device', inferDevice || 'CPU');
    formData.append('image', inferFile);

    setInferLoading(true);
    try {
      const payload = await apiPost(API.algorithmTestInfer, formData);
      setInferResult(JSON.stringify(payload || {}, null, 2));
      message.success('测试完成');
    } catch (error) {
      setInferResult(String(error?.message || '测试失败'));
      message.error(error?.message || '测试失败');
    } finally {
      setInferLoading(false);
    }
  }

  return (
    <div>
      <AlgorithmFormHeader handle={handle} popupMode={popupMode} />

      <form method="post" action={formAction} encType="multipart/form-data" onSubmit={handleFormSubmit}>
        <AlgorithmHiddenInputs
          handle={handle}
          popupMode={popupMode}
          values={values}
          resolvedApiUrl={resolvedApiUrl}
        />
        <AlgorithmTypeCard values={values} template={template} patchValues={patchValues} />

        {isBasicAlgorithm ? (
          <BasicAlgorithmCard
            values={values}
            template={template}
            subtypeOptions={subtypeOptions}
            modelPrecisionOptions={modelPrecisionOptions}
            showModelConfig={showModelConfig}
            showApiConfig={showApiConfig}
            showObjectStr={showObjectStr}
            showPairedFile={showPairedFile}
            patchValues={patchValues}
            setModelFile={setModelFile}
            setPairedFile={setPairedFile}
          />
        ) : (
          <BehaviorAlgorithmCard
            values={values}
            template={template}
            behaviorApiVersions={behaviorApiVersions}
            builtinBehaviorOptions={builtinBehaviorOptions}
            dllFile={dllFile}
            patchValues={patchValues}
            setDllFile={setDllFile}
          />
        )}

        <CommonAlgorithmCard values={values} patchValues={patchValues} />
      </form>

      <AlgorithmInferCard
        visible={handle === 'edit'}
        inferDevice={inferDevice}
        inferLoading={inferLoading}
        inferResult={inferResult}
        setInferDevice={setInferDevice}
        setInferFile={setInferFile}
        handleInferSubmit={handleInferSubmit}
      />
    </div>
  );
}

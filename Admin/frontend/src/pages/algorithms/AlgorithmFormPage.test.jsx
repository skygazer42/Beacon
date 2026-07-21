import React from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App as AntdApp, ConfigProvider } from 'antd';
import AlgorithmFormPage from './AlgorithmFormPage';
import { resetBootstrapCache } from '../../bootstrap';
import { API } from '../../api/endpoints';

const { mockApiPost } = vi.hoisted(() => ({
  mockApiPost: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  apiPost: (...args) => mockApiPost(...args),
}));

function renderPage() {
  return render(
    <ConfigProvider>
      <AntdApp>
        <AlgorithmFormPage />
      </AntdApp>
    </ConfigProvider>,
  );
}

function mountShell({ path, queryString = '', templateHtml }) {
  document.body.innerHTML = `
    <script id="beacon-bootstrap" type="application/json">
      ${JSON.stringify({
        path,
        queryString,
        siteName: 'Beacon',
        siteTitle: 'Beacon',
        siteLogo: '/static/images/logo.png',
        user: { id: '1', username: 'tester' },
      })}
    </script>
    <template id="beacon-legacy-content">${templateHtml}</template>
  `;
  resetBootstrapCache();
}

function buildTemplate({
  handle = 'add',
  code = '',
  popup = false,
  currentType = 0,
  basicSource = 'model',
  subtype = 'detection',
  apiUrl = '',
  modelPath = '',
}) {
  return `
    <div class="bcn-page" ${popup ? 'data-popup-mode="1"' : ''}>
      <form id="algorithmForm" method="post" enctype="multipart/form-data">
        <input type="hidden" name="handle" value="${handle}">
        ${popup ? '<input type="hidden" name="popup" value="1">' : ''}
        <input type="hidden" name="algorithm_type" id="algorithm_type" value="${currentType}">
        <input type="hidden" name="basic_source" id="basic_source" value="${basicSource}">
        <input type="hidden" name="algorithm_subtype" id="algorithm_subtype" value="${subtype}">
        <input type="text" id="code" name="code" value="${code}" ${handle === 'edit' ? 'readonly' : ''}>
        <input type="text" id="name" name="name" value="${code ? `${code}-name` : ''}">
        <input type="text" id="license_package" name="license_package" value="core">
        <select id="algorithm_subtype_select">
          <option value="detection" ${subtype === 'detection' ? 'selected' : ''}>检测（Detection）</option>
          <option value="classification" ${subtype === 'classification' ? 'selected' : ''}>分类（Classification）</option>
          <option value="ocr" ${subtype === 'ocr' ? 'selected' : ''}>OCR（XcOCR/文本识别）</option>
          <option value="tracking" ${subtype === 'tracking' ? 'selected' : ''}>追踪（Tracking / ReID）</option>
          <option value="speech" ${subtype === 'speech' ? 'selected' : ''}>语音/ASR（Speech / ASR）</option>
        </select>
        <select id="model_precision" name="model_precision">
          <option value="FP32" selected>FP32</option>
          <option value="FP16">FP16</option>
          <option value="INT8">INT8</option>
        </select>
        <select id="behavior_api_version" name="behavior_api_version">
          <option value="1" selected>APIv1</option>
          <option value="2">APIv2</option>
        </select>
        <div class="behavior-select-card">
          <div class="behavior-option" data-value="intrusion">入侵</div>
          <div class="behavior-option" data-value="fight">打架</div>
        </div>
        <input type="hidden" name="builtin_behavior" id="builtin_behavior" value="">
        <input type="text" name="api_url" id="api_url_basic" value="${apiUrl}">
        <input type="text" name="api_url_behavior" id="api_url_behavior" value="${apiUrl}">
        <input type="text" name="object_str" id="object_str" value="person">
        <input type="number" id="max_control_count" name="max_control_count" value="0">
        <input type="number" id="model_concurrency" name="model_concurrency" value="1">
        <input type="number" id="input_width" name="input_width" value="640">
        <input type="number" id="input_height" name="input_height" value="640">
        <input type="number" id="conf_thresh" name="conf_thresh" value="0.25">
        <input type="number" id="nms_thresh" name="nms_thresh" value="0.45">
        <textarea id="remark" name="remark">template remark</textarea>
        <div id="basic_model_config">
          ${modelPath ? `<div class="existing-file"><span>已上传: ${modelPath}</span></div>` : ''}
          <input type="file" name="model_file" id="model_file">
        </div>
        <div id="paired_file_group" style="display:none;">
          <input type="file" name="paired_file" id="paired_file">
        </div>
        <div id="behavior_section">
          <input type="checkbox" name="support_direct_api" id="support_direct_api">
          <input type="file" name="dll_file" id="dll_file">
        </div>
      </form>
    </div>
  `;
}

describe('AlgorithmFormPage', () => {
  beforeAll(() => {
    window.matchMedia = window.matchMedia || (() => ({
      matches: false,
      media: '',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    document.body.innerHTML = '';
    resetBootstrapCache();
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });

  it('hydrates add form from the legacy template and forces api source for speech subtype', async () => {
    mountShell({
      path: '/algorithm/add',
      queryString: 'popup=1',
      templateHtml: buildTemplate({ handle: 'add', popup: true }),
    });

    renderPage();

    expect(screen.getByRole('heading', { name: '添加算法' })).toBeInTheDocument();
    expect(screen.getByLabelText('编号')).toHaveValue('');
    expect(document.querySelector('input[name="popup"]')).toHaveValue('1');
    expect(document.querySelector('input[name="license_package"]')).toHaveValue('core');

    fireEvent.change(screen.getByLabelText('算法子类型'), { target: { value: 'speech' } });

    await waitFor(() => {
      expect(document.querySelector('input[name="algorithm_subtype"]')).toHaveValue('speech');
      expect(document.querySelector('input[name="basic_source"]')).toHaveValue('api');
    });

    expect(screen.getByLabelText('API地址')).toBeInTheDocument();
    expect(screen.queryByLabelText('模型文件')).not.toBeInTheDocument();
  });

  it('keeps edit contract fields and runs one-shot infer via the direct api', async () => {
    mountShell({
      path: '/algorithm/edit',
      queryString: 'code=alg-edit-1',
      templateHtml: buildTemplate({
        handle: 'edit',
        code: 'alg-edit-1',
        basicSource: 'api',
        apiUrl: 'http://example.com/infer',
        modelPath: '/static/upload/models/alg-edit-1.onnx',
      }),
    });

    mockApiPost.mockImplementation((url, body) => {
      if (url === API.algorithmTestInfer) {
        expect(body).toBeInstanceOf(FormData);
        expect(body.get('code')).toBe('alg-edit-1');
        expect(body.get('device')).toBe('CPU');
        expect(body.get('image')).toBeInstanceOf(File);
        expect(body.get('image').name).toBe('sample.jpg');
        return Promise.resolve({
          code: 1000,
          data: { detects: [{ class_name: 'helmet', confidence: 0.91 }] },
        });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });

    renderPage();

    expect(screen.getByRole('heading', { name: '编辑算法' })).toBeInTheDocument();
    expect(screen.getByLabelText('编号')).toHaveValue('alg-edit-1');
    expect(screen.getByLabelText('编号')).toHaveAttribute('readonly');
    expect(document.querySelector('input[name="handle"]')).toHaveValue('edit');
    expect(document.querySelector('input[name="algorithm_type"]')).toHaveValue('0');

    const file = new File(['fake-image'], 'sample.jpg', { type: 'image/jpeg' });
    fireEvent.change(screen.getByLabelText('测试图片'), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole('button', { name: /^开始测试$/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.algorithmTestInfer, expect.any(FormData));
    });

    expect(await screen.findByText(/helmet/)).toBeInTheDocument();
  });
});

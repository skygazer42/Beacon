import React from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App as AntdApp, ConfigProvider } from 'antd';
import LicensePage from './LicensePage';
import { API } from '../../api/endpoints';

const { mockApiGet, mockApiPostFormRaw } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiPostFormRaw: vi.fn(),
}));

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual('../../api/client');
  return {
    ...actual,
    apiGet: (...args) => mockApiGet(...args),
    apiPostFormRaw: (...args) => mockApiPostFormRaw(...args),
  };
});

function buildLicensePayload(overrides = {}) {
  return {
    api_base_url: 'http://testserver',
    license_type: 'pool',
    top_msg: '最近导入已生效',
    info_source: 'analyzer',
    info: {
      type: 'pool',
      machine_code: 'ANZ-001',
      extra: {
        license_id: 'LIC-1',
        cluster_id: 'cluster-a',
      },
    },
    fallback_info: {
      machine_code: 'LOCAL-001',
    },
    transport_ok: false,
    transport_message: 'Analyzer 接口暂不可达',
    state: {
      type: 'pool',
      license_id: 'LIC-1',
      customer: 'City Lab',
      cluster_id: 'cluster-a',
      packages: ['core', 'ppe'],
      package_limits: {
        ppe: {
          max_active_controls: 2,
        },
      },
      valid: false,
      last_error_code: 'license_expired',
      last_error_message: 'expired soon',
    },
    usage: {
      valid: true,
      package_usage: {
        ppe: 1,
      },
      limits: {
        max_active_controls: 8,
        max_nodes: 3,
      },
      active_controls: 1,
      active_streams: 1,
      active_nodes: 1,
      edition: 'enterprise',
      thread_priority_policy: {
        worker: 'high',
      },
    },
    leases: [
      {
        lease_id: 'lease-001',
        node_id: 'node-a',
        stream_code: 'cam-001',
        control_code: 'ctrl-001',
        algorithm_code: 'alg-001',
        package: 'ppe',
        expires_at: '2026-03-31 12:00:00',
        update_time: '2026-03-31 11:59:00',
      },
    ],
    license_error: {
      code: 'malformed_json',
      message: 'bad json',
    },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <ConfigProvider>
      <AntdApp>
        <LicensePage />
      </AntdApp>
    </ConfigProvider>,
  );
}

describe('LicensePage', () => {
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
    vi.spyOn(window, 'getComputedStyle').mockImplementation(() => ({
      getPropertyValue: () => '',
      overflow: 'auto',
      overflowX: 'auto',
      overflowY: 'auto',
    }));
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });

  it('loads dense license diagnostics from the app-shell api and renders package usage details', async () => {
    mockApiGet.mockResolvedValue(buildLicensePayload());

    renderPage();

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith(API.license, undefined);
    });

    expect(screen.getByTestId('license-overview-grid')).toHaveClass('beacon-support-grid', 'beacon-equal-height-grid');
    expect(screen.getByText('上传授权文件').closest('.beacon-panel-card')).toHaveClass('beacon-panel-card--tone-orange');
    expect(screen.getByText('授权状态').closest('.beacon-summary-card')).toHaveClass('beacon-panel-card--tone-green');
    expect(screen.getByText('授权诊断').closest('.beacon-summary-card')).toHaveClass('beacon-panel-card--tone-orange');
    expect(screen.getByText('上游 / 回退信息').closest('.beacon-summary-card')).toHaveClass('beacon-panel-card--tone-blue');
    expect(screen.getByText('活跃布控')).toBeInTheDocument();
    expect(screen.getByText('活跃流')).toBeInTheDocument();
    expect(screen.getByText('活跃节点')).toBeInTheDocument();
    expect(screen.getByText('授权包数')).toBeInTheDocument();
    expect(await screen.findAllByText('最近导入已生效')).toHaveLength(2);
    expect(screen.getByText('analyzer')).toBeInTheDocument();
    expect(screen.getByText('http://testserver')).toBeInTheDocument();
    expect(screen.getByText('LOCAL-001')).toBeInTheDocument();
    expect(screen.getByText('malformed_json')).toBeInTheDocument();
    expect(screen.getByText('授权包用量')).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    expect(screen.getByText('worker: high')).toBeInTheDocument();
    expect(screen.getByText('lease-001')).toBeInTheDocument();
  });

  it('keeps the upload error payload from the backend and shows the returned license diagnostics', async () => {
    mockApiGet.mockResolvedValue(buildLicensePayload({ top_msg: '', license_error: null, transport_ok: true, transport_message: '' }));
    mockApiPostFormRaw.mockResolvedValue({
      code: 0,
      msg: '导入失败',
      data: buildLicensePayload({
        top_msg: 'JSON 文件解析失败',
        transport_ok: true,
        transport_message: '',
        license_error: {
          code: 'malformed_json',
          message: 'bad json',
        },
      }),
    });

    const { container } = renderPage();

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith(API.license, undefined);
    });

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();

    const file = new File(['bad'], 'license.json', { type: 'application/json' });
    await fireEvent.change(input, {
      target: {
        files: [file],
      },
    });

    await waitFor(() => {
      expect(mockApiPostFormRaw).toHaveBeenCalledWith(API.licenseUpload, expect.any(FormData));
    });

    expect(await screen.findAllByText('JSON 文件解析失败')).toHaveLength(2);
    expect(screen.getByText('malformed_json')).toBeInTheDocument();
  });
});

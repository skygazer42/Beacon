import React from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App as AntdApp, ConfigProvider } from 'antd';
import StreamsPage from './StreamsPage';
import { API } from '../../api/endpoints';

const { mockUseApi, mockApiGet, mockApiPost } = vi.hoisted(() => ({
  mockUseApi: vi.fn(),
  mockApiGet: vi.fn(),
  mockApiPost: vi.fn(),
}));

vi.mock('../../hooks/useApi', () => ({
  default: (...args) => mockUseApi(...args),
}));

vi.mock('../../api/client', () => ({
  apiGet: (...args) => mockApiGet(...args),
  apiPost: (...args) => mockApiPost(...args),
}));

vi.mock('../../bootstrap', () => ({
  getBootstrapQuery: () => new URLSearchParams(''),
}));

function renderPage() {
  return render(
    <ConfigProvider>
      <AntdApp>
        <StreamsPage />
      </AntdApp>
    </ConfigProvider>,
  );
}

describe('StreamsPage', () => {
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

  it('renders the stream operations workspace layout shell', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [],
        pageData: { page: 1, page_size: 20, count: 3 },
        stats: { total: 3, online: 0, forwarding: 0 },
        appChoices: [],
        siteChoices: [],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet.mockResolvedValue({ auto_start: false });

    const { container } = renderPage();

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith(API.streamGetAutoStartConfig);
    });

    expect(container.querySelector('.beacon-streams-page')).toBeInTheDocument();
    expect(container.querySelector('.beacon-streams-toolbar')).toBeInTheDocument();
    expect(container.querySelector('.beacon-streams-overview')).toBeInTheDocument();
    expect(container.querySelectorAll('.beacon-streams-metric-card')).toHaveLength(3);
    expect(container.querySelector('.beacon-streams-table-card')).toBeInTheDocument();
  });

  it('shows stream forwarding actions and the batch import entry', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 1,
            code: 'stream-1',
            app: 'live',
            name: 'gate',
            nickname: '北门摄像头',
            site_label: 'A区',
            state: 1,
            forward_state: 0,
            last_update_time: '2026-03-30 10:00:00',
          },
        ],
        pageData: { page: 1, page_size: 20, count: 1 },
        stats: { total: 1, online: 1, forwarding: 0 },
        appChoices: [],
        siteChoices: [],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet.mockResolvedValue({ auto_start: true });
    mockApiPost.mockResolvedValue({});

    renderPage();

    expect(screen.getByText('视频流总览')).toBeInTheDocument();
    expect(document.querySelector('.beacon-streams-toolbar')).toBeInTheDocument();
    expect(document.querySelectorAll('.beacon-streams-metric-card')).toHaveLength(3);
    expect(screen.getByText('批量导入')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '开启转发' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.streamAddProxy, expect.any(FormData));
    });
  });

  it('enables a disabled stream from the row actions', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 1,
            code: 'usbcam',
            app: 'live',
            name: 'usbcam',
            nickname: 'USB Camera',
            site_label: '',
            state: 0,
            forward_state: 0,
            last_update_time: '2026-06-01 14:19:01',
          },
        ],
        pageData: { page: 1, page_size: 20, count: 1 },
        stats: { total: 1, online: 0, forwarding: 0 },
        appChoices: [],
        siteChoices: [],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet.mockResolvedValue({ auto_start: false });
    mockApiPost.mockResolvedValue({ msg: '启用成功' });

    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '启用' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/api/app-shell/stream/action/openSetState', {
        code: 'usbcam',
        state: 1,
      });
    });
  });

  it('submits selected stream codes for batch forwarding instead of row ids', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 101,
            code: 'stream-1',
            app: 'live',
            name: 'gate',
            nickname: '北门摄像头',
            site_label: 'A区',
            state: 1,
            forward_state: 0,
            last_update_time: '2026-03-30 10:00:00',
          },
        ],
        pageData: { page: 1, page_size: 20, count: 1 },
        stats: { total: 1, online: 1, forwarding: 0 },
        appChoices: [],
        siteChoices: [],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet.mockResolvedValue({ auto_start: false });
    mockApiPost.mockResolvedValue({});

    const { container } = renderPage();

    const rowCheckbox = await waitFor(() => container.querySelectorAll('input[type="checkbox"]')[1]);
    fireEvent.click(rowCheckbox);
    fireEvent.click(screen.getByRole('button', { name: /批量开启转发/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.streamBatchAddProxy, { codes: 'stream-1' });
    });
  });

  it('builds the player link from app and name instead of stream code', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 1,
            code: 'stream-1',
            app: 'live',
            name: 'gate',
            nickname: '北门摄像头',
            site_label: 'A区',
            state: 1,
            forward_state: 0,
            last_update_time: '2026-03-30 10:00:00',
          },
        ],
        pageData: { page: 1, page_size: 20, count: 1 },
        stats: { total: 1, online: 1, forwarding: 0 },
        appChoices: [],
        siteChoices: [],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet.mockResolvedValue({ auto_start: false });

    const { container } = renderPage();

    await screen.findByText('北门摄像头');
    const playLink = container.querySelector('.beacon-streams-row-actions a');
    expect(playLink).not.toBeNull();
    expect(playLink).toHaveAttribute('href', '/stream/player?app=live&name=gate');
  });

  it('opens talkback, PTZ, and pusher proxy actions for a stream', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 1,
            code: 'stream-1',
            app: 'live',
            name: 'gate',
            nickname: '北门摄像头',
            site_label: 'A区',
            state: 1,
            forward_state: 1,
            pull_stream_type: 21,
            last_update_time: '2026-03-30 10:00:00',
          },
        ],
        pageData: { page: 1, page_size: 20, count: 1 },
        stats: { total: 1, online: 1, forwarding: 1 },
        appChoices: [],
        siteChoices: [],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet
      .mockResolvedValueOnce({ auto_start: false })
      .mockResolvedValueOnce({ ok: true, active: true });
    mockApiPost
      .mockResolvedValueOnce({
        enabled: true,
        transport_mode: 'webrtc_to_rtsp',
        onvif_service_url: '',
        onvif_username: '',
        backchannel_uri: 'rtsp://talkback/device',
        relay_app: 'talkback',
        relay_stream_prefix: 'tb',
        sample_rate: 16000,
        codec_hint: 'pcma',
        remark: '',
      })
      .mockResolvedValue({ ok: true });

    renderPage();

    expect(screen.getByText('视频流总览')).toBeInTheDocument();
    expect(document.querySelector('.beacon-streams-table-card')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '回讲' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.talkbackConfigGet, { stream_code: 'stream-1' });
    });

    fireEvent.click(await screen.findByRole('button', { name: '开启回讲' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.talkbackStart, { stream_code: 'stream-1', session_id: 'web_stream-1' });
    });

    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith(API.talkbackStatus, { session_id: 'web_stream-1' });
    });

    fireEvent.click(screen.getByRole('button', { name: '停止回讲' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.talkbackStop, { session_id: 'web_stream-1' });
    });

    fireEvent.click(screen.getByRole('button', { name: /关\s*闭/ }));
    fireEvent.click(screen.getByRole('button', { name: '云台' }));
    fireEvent.click(await screen.findByRole('button', { name: '上' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        API.streamGb28181Ptz,
        expect.objectContaining({ code: 'stream-1', action: 'up', speed: 32 }),
      );
    });

    fireEvent.click(screen.getByRole('button', { name: /关\s*闭/ }));
    fireEvent.click(screen.getByRole('button', { name: '转推代理' }));
    fireEvent.change(await screen.findByLabelText('目标主机'), { target: { value: '10.0.0.9' } });
    fireEvent.click(screen.getByRole('button', { name: '开始转推' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.streamAddPusherProxy, {
        stream_app: 'live',
        stream_name: 'gate',
        dst_host: '10.0.0.9',
        dst_stream_app: 'live',
        dst_stream_name: 'gate',
        dst_rtsp_port: 554,
      });
    });
  });
});

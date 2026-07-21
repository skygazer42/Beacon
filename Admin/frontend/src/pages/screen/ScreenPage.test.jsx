import React from 'react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { ConfigProvider } from 'antd';
import ScreenPage from './ScreenPage';
import { API } from '../../api/endpoints';

const { mockUseApi, mockApiGetRaw } = vi.hoisted(() => ({
  mockUseApi: vi.fn(),
  mockApiGetRaw: vi.fn(),
}));

vi.mock('../../hooks/useApi', () => ({
  default: (...args) => mockUseApi(...args),
}));

vi.mock('../../api/client', () => ({
  apiGetRaw: (...args) => mockApiGetRaw(...args),
}));

let screenRows;
let onlineRows;

function renderPage() {
  return render(
    <ConfigProvider>
      <ScreenPage />
    </ConfigProvider>,
  );
}

function configureApi() {
  mockUseApi.mockImplementation((endpoint) => {
    if (endpoint === API.screen) {
      return { data: { rows: screenRows }, loading: false, error: null, run: vi.fn() };
    }
    if (endpoint === API.streamOnline) {
      return {
        data: { rows: onlineRows, summary: { total_count: onlineRows.length } },
        loading: false,
        error: null,
        run: vi.fn(),
      };
    }
    return { data: {}, loading: false, error: null, run: vi.fn() };
  });
}

function onlineStream(overrides = {}) {
  return {
    app: 'live',
    name: 'cam-1',
    display_name: 'Camera 1',
    source_nickname: 'Camera 1',
    source_type: 1,
    ...overrides,
  };
}

function focusRow(overrides = {}) {
  return {
    stream_code: 'cam-1',
    stream_app: 'live',
    stream_name: 'cam-1',
    label: 'Camera 1',
    group: 'live',
    alarm_count: 0,
    recent_events: [],
    ...overrides,
  };
}

describe('ScreenPage', () => {
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
    global.ResizeObserver = global.ResizeObserver || class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  beforeEach(() => {
    screenRows = [];
    onlineRows = [];
    configureApi();
    mockApiGetRaw.mockResolvedValue({
      code: 1000,
      data: {
        url: 'ws://media.example/live/cam-1.live.flv',
        embed_url: 'http://media.example/webrtc/index.html?app=live&stream=cam-1&type=play',
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    delete window.__BEACON_SCREEN_PLAY_URL_CACHE__;
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });

  it('renders backend links for stream detail and latest alarm', async () => {
    screenRows = [focusRow({
      label: 'East Crossing',
      alarm_count: 2,
      stream_detail_url: '/stream/edit?code=cam-1',
      latest_alarm_url: '/alarm/detail?id=99',
      recent_events: [
        { id: 99, desc: 'East Crossing congestion', detail_url: '/alarm/detail?id=99' },
      ],
    })];
    onlineRows = [onlineStream({ display_name: 'East Crossing' })];

    renderPage();

    expect(await screen.findByRole('link', { name: '打开视频流' })).toHaveAttribute(
      'href',
      '/stream/edit?code=cam-1',
    );
    expect(screen.getByRole('link', { name: '最近报警' })).toHaveAttribute(
      'href',
      '/alarm/detail?id=99',
    );
    expect(screen.getAllByText('East Crossing congestion').length).toBeGreaterThanOrEqual(1);
  });

  it('plays the current online stream through the MediaServer WebRTC page', async () => {
    screenRows = [focusRow({
      stream_code: 'offline',
      stream_app: 'old',
      stream_name: 'offline',
      label: 'Offline Camera',
    })];
    onlineRows = [onlineStream({ display_name: 'Current Camera' })];

    renderPage();

    const frame = await screen.findByTitle('Current Camera');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute(
      'src',
      'http://media.example/webrtc/index.html?app=live&stream=cam-1&type=play',
    );
    expect(screen.queryByTitle('Offline Camera')).not.toBeInTheDocument();
    expect(mockApiGetRaw).toHaveBeenCalledWith(API.streamGetPlayUrl, {
      app: 'live',
      name: 'cam-1',
      layout: 4,
      prefer: 'compat',
      quality: 'auto',
    });
  });

  it('supports the two-window layout without a proprietary player runtime', async () => {
    onlineRows = [onlineStream()];
    renderPage();

    fireEvent.click(screen.getByText('2 画面'));

    expect(await screen.findByText('监控画面 (2 宫格)')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /选择播放窗口/ })).toHaveLength(2);
    await waitFor(() => {
      expect(mockApiGetRaw).toHaveBeenCalledWith(
        API.streamGetPlayUrl,
        expect.objectContaining({ layout: 2 }),
      );
    });
  });

  it('prefers an analyzer stream over its duplicate raw camera stream', async () => {
    onlineRows = [
      onlineStream({ display_name: 'Raw Camera' }),
      onlineStream({
        app: 'analyzer',
        name: 'control-1',
        display_name: 'Detection Result',
        source_type: 2,
        control_stream_app: 'live',
        control_stream_name: 'cam-1',
      }),
    ];
    mockApiGetRaw.mockResolvedValue({
      code: 1000,
      data: {
        url: 'ws://media.example/analyzer/control-1.live.flv',
        embed_url: 'http://media.example/webrtc/index.html?app=analyzer&stream=control-1&type=play',
      },
    });

    renderPage();

    expect(await screen.findByTitle('Detection Result')).toBeInTheDocument();
    expect(mockApiGetRaw).toHaveBeenCalledWith(
      API.streamGetPlayUrl,
      expect.objectContaining({ app: 'analyzer', name: 'control-1' }),
    );
    expect(mockApiGetRaw).not.toHaveBeenCalledWith(
      API.streamGetPlayUrl,
      expect.objectContaining({ app: 'live', name: 'cam-1' }),
    );
  });

  it('makes stream slots keyboard selectable', async () => {
    onlineRows = [onlineStream()];
    renderPage();

    const secondSlot = await screen.findByRole('button', { name: '选择播放窗口 02 号窗' });
    fireEvent.keyDown(secondSlot, { key: 'Enter' });

    expect(secondSlot).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '投放到 02 号窗' })).toBeInTheDocument();
  });

  it('reuses a resolved play URL when the page remounts', async () => {
    onlineRows = [onlineStream()];

    const first = renderPage();
    expect(await screen.findByTitle('Camera 1')).toBeInTheDocument();
    await waitFor(() => expect(mockApiGetRaw).toHaveBeenCalledTimes(1));
    first.unmount();

    renderPage();
    expect(await screen.findByTitle('Camera 1')).toBeInTheDocument();
    expect(mockApiGetRaw).toHaveBeenCalledTimes(1);
  });
});

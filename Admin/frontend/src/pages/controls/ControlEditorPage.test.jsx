import React from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App as AntdApp, ConfigProvider } from 'antd';
import ControlEditorPage from './ControlEditorPage';
import { API } from '../../api/endpoints';

const { mockApiGet, mockApiGetRaw, mockApiPost } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiGetRaw: vi.fn(),
  mockApiPost: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  apiGet: (...args) => mockApiGet(...args),
  apiGetRaw: (...args) => mockApiGetRaw(...args),
  apiPost: (...args) => mockApiPost(...args),
}));

vi.mock('../../bootstrap', () => ({
  getBootstrapQuery: () => new URLSearchParams('code=ctl-1'),
  getBootstrapPath: () => '/control/edit',
}));

function renderPage() {
  return render(
    <ConfigProvider>
      <AntdApp>
        <ControlEditorPage />
      </AntdApp>
    </ConfigProvider>,
  );
}

describe('ControlEditorPage', () => {
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
    vi.clearAllMocks();
  });

  function buildEditorPayload(overrides = {}) {
    const { control: controlOverrides = {}, ...restOverrides } = overrides;
    return {
      mode: 'edit',
      control: {
        code: 'ctl-1',
        stream_app: 'live',
        stream_name: 'gate',
        object_code: 'person',
        polygon: '',
        min_interval: 10,
        class_thresh: 0.5,
        overlap_thresh: 0.4,
        push_stream: true,
        remark: 'test control',
        decode_stride: 1,
        force_frame_alarm: false,
        alarm_sound_id: 0,
        alarm_video_type: 'mp4',
        alarm_image_count: 3,
        alarm_image_draw_mode: 'boxed',
        alarm_cover_position: 'back',
        alarm_cover_custom_index: 0,
        osd_enabled: true,
        osd_text: '{time}',
        osd_position: 'top-left',
        osd_x: 10,
        osd_y: 30,
        osd_font_size: 24,
        osd_font_color: '255,255,255',
        osd_bg_enabled: true,
        osd_image_path: 'osd/base/logo.png',
        osd_image_x: 10,
        osd_image_y: 10,
        osd_image_scale: 1,
        osd_image_alpha: 1,
        osd_algo_x: 20,
        osd_algo_y: 80,
        osd_fps_x: 20,
        osd_fps_y: 140,
        osd_font_thickness: 2,
        ...controlOverrides,
      },
      algorithms: [{ code: 'alg-person', name: 'Person Detector', object_options: ['person'] }],
      alarm_sounds: [],
      object_options: ['person'],
      control_algorithm_base: 'alg-person',
      control_algorithm_device: 'CPU',
      control_tracking_base: '',
      control_tracking_device: 'CPU',
      control_tracking_device_id: '',
      osd_assets: [],
      ...restOverrides,
    };
  }

  it('loads direct osd assets and uploads new osd images through the direct asset api', async () => {
    mockApiGetRaw.mockResolvedValue({
      code: 1000,
      data: {
        url: 'ws://demo/live/gate.live.flv',
      },
    });
    mockApiGet.mockImplementation((url, params) => {
      if (url === API.controlEditor) {
        expect(params).toEqual({ code: 'ctl-1' });
        return Promise.resolve(buildEditorPayload({ control: { polygon: '[]' } }));
      }
      if (url === API.streams) {
        return Promise.resolve({ rows: [] });
      }
      if (url === API.controlOsdAssets) {
        return Promise.resolve({
          rows: [
            {
              path: 'osd/base/logo.png',
              name: 'logo.png',
              url: '/static/upload/osd/base/logo.png',
              update_time: '2026-03-30 10:00:00',
            },
          ],
          base_url: '/static/upload/',
          accept: ['png', 'jpg'],
        });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });

    mockApiPost.mockImplementation((url, body) => {
      if (url === API.controlOsdAssetsUpload) {
        expect(body).toBeInstanceOf(FormData);
        expect(body.get('file')).toBeInstanceOf(File);
        expect(body.get('file').name).toBe('brand.png');
        return Promise.resolve({
          rows: [
            {
              path: 'osd/base/logo.png',
              name: 'logo.png',
              url: '/static/upload/osd/base/logo.png',
              update_time: '2026-03-30 10:00:00',
            },
            {
              path: 'osd/20260330/brand.png',
              name: 'brand.png',
              url: '/static/upload/osd/20260330/brand.png',
              update_time: '2026-03-30 11:00:00',
            },
          ],
          asset: {
            path: 'osd/20260330/brand.png',
            name: 'brand.png',
            url: '/static/upload/osd/20260330/brand.png',
            update_time: '2026-03-30 11:00:00',
          },
        });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });

    renderPage();

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith(API.controlOsdAssets);
    });

    expect(await screen.findByDisplayValue('osd/base/logo.png')).toBeInTheDocument();

    const file = new File(['png-binary'], 'brand.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('上传贴图'), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole('button', { name: /^上传贴图$/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.controlOsdAssetsUpload, expect.any(FormData));
    });

    expect(await screen.findByDisplayValue('osd/20260330/brand.png')).toBeInTheDocument();
  }, 20000);

  it('binds the visual recognition region editor back into the control form payload', async () => {
    const originalLocation = window.location;
    delete window.location;
    window.location = { href: 'http://127.0.0.1:5173/control/edit?code=ctl-1' };

    mockApiGet.mockImplementation((url, params) => {
      if (url === API.controlEditor) {
        expect(params).toEqual({ code: 'ctl-1' });
        return Promise.resolve(buildEditorPayload());
      }
      if (url === API.streams) {
        return Promise.resolve({ rows: [] });
      }
      if (url === API.controlOsdAssets) {
        return Promise.resolve({ rows: [], base_url: '/static/upload/', accept: ['png', 'jpg'] });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiGetRaw.mockResolvedValue({
      code: 1000,
      data: {
        url: 'ws://demo/live/gate.live.flv',
      },
    });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'ok' });

    renderPage();

    expect(await screen.findByText('识别区域')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '全屏区域' }));
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.controlEditPost, expect.any(FormData));
    });

    const [, formData] = mockApiPost.mock.calls.find(([url]) => url === API.controlEditPost);
    expect(formData.get('polygon')).toBe('0,0,1,0,1,1,0,1');

    window.location = originalLocation;
  });

  it('captures and shows a current-frame preview for ROI drawing instead of a raw stream url', async () => {
    mockApiGet.mockImplementation((url, params) => {
      if (url === API.controlEditor) {
        expect(params).toEqual({ code: 'ctl-1' });
        return Promise.resolve(buildEditorPayload());
      }
      if (url === API.streams) {
        return Promise.resolve({
          rows: [{ code: 'gate', app: 'live', name: 'gate', nickname: 'Gate Cam' }],
        });
      }
      if (url === API.controlOsdAssets) {
        return Promise.resolve({ rows: [], base_url: '/static/upload/', accept: ['png', 'jpg'] });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiGetRaw.mockResolvedValue({
      code: 1000,
      data: {
        url: 'ws://demo/live/gate.live.flv',
      },
    });
    mockApiPost.mockImplementation((url, body) => {
      if (url === API.recordingSnapshot) {
        expect(body).toEqual({ stream_code: 'gate', method: 'ffmpeg' });
        return Promise.resolve({
          image_url: '/static/upload/snapshots/gate/gate-preview.jpg',
          image_path: 'snapshots/gate/gate-preview.jpg',
        });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });

    renderPage();

    const preview = await screen.findByAltText('布控区域当前帧');
    expect(preview.getAttribute('src')).toContain('/static/upload/snapshots/gate/gate-preview.jpg');

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.recordingSnapshot, { stream_code: 'gate', method: 'ffmpeg' });
    });
  });

  it('shows the alarm cover position control and serializes custom cover settings', async () => {
    const originalLocation = window.location;
    delete window.location;
    window.location = { href: 'http://127.0.0.1:5173/control/edit?code=ctl-1' };

    mockApiGet.mockImplementation((url, params) => {
      if (url === API.controlEditor) {
        expect(params).toEqual({ code: 'ctl-1' });
        return Promise.resolve(
          buildEditorPayload({
            control: {
              alarm_cover_position: 'custom',
              alarm_cover_custom_index: 7,
            },
          }),
        );
      }
      if (url === API.streams) {
        return Promise.resolve({ rows: [] });
      }
      if (url === API.controlOsdAssets) {
        return Promise.resolve({ rows: [], base_url: '/static/upload/', accept: ['png', 'jpg'] });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiGetRaw.mockResolvedValue({
      code: 1000,
      data: {
        url: 'ws://demo/live/gate.live.flv',
      },
    });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'ok' });

    renderPage();

    expect(await screen.findByText('告警封面帧')).toBeInTheDocument();
    expect(screen.getByDisplayValue('7')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(API.controlEditPost, expect.any(FormData));
    });

    const [, formData] = mockApiPost.mock.calls.find(([url]) => url === API.controlEditPost);
    expect(formData.get('alarmCoverPosition')).toBe('custom');
    expect(formData.get('alarmCoverCustomIndex')).toBe('7');

    window.location = originalLocation;
  });
});

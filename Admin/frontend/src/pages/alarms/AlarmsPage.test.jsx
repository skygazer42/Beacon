import React from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App as AntdApp, ConfigProvider } from 'antd';
import AlarmsPage from './AlarmsPage';
import { API } from '../../api/endpoints';

const { mockUseApi, mockApiGet, mockApiPost, mockGetBootstrapQuery, mockGetBootstrapPath } = vi.hoisted(() => ({
  mockUseApi: vi.fn(),
  mockApiGet: vi.fn(),
  mockApiPost: vi.fn(),
  mockGetBootstrapQuery: vi.fn(() => new URLSearchParams('')),
  mockGetBootstrapPath: vi.fn(() => '/alarms'),
}));

vi.mock('../../hooks/useApi', () => ({
  default: (...args) => mockUseApi(...args),
}));

vi.mock('../../api/client', () => ({
  apiGet: (...args) => mockApiGet(...args),
  apiPost: (...args) => mockApiPost(...args),
}));

vi.mock('../../bootstrap', () => ({
  getBootstrapQuery: (...args) => mockGetBootstrapQuery(...args),
  getBootstrapPath: (...args) => mockGetBootstrapPath(...args),
}));

function renderPage() {
  return render(
    <ConfigProvider>
      <AntdApp>
        <AlarmsPage />
      </AntdApp>
    </ConfigProvider>,
  );
}

async function waitForButton(name) {
  await waitFor(() => {
    expect(screen.getByRole('button', { name })).toBeEnabled();
  });
  return screen.getByRole('button', { name });
}

describe('AlarmsPage', () => {
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

  it('opens semantic search preview and queries the direct semantic api', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 101,
            desc: 'Helmet detected',
            workflow_status: 'new',
            stream_name: 'Dock Camera',
            stream_code: 'dock-1',
            algorithm_code: 'helmet-detector',
            control_code: 'dock-control',
            create_time: '2026-03-30 12:00:00',
            image_path: '',
          },
        ],
        total: 1,
        presets: { items: [], target_mode: 'list' },
        page: 1,
        page_size: 20,
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });

    mockApiGet.mockImplementation((url) => {
      if (url === API.alarmSemanticSearch) {
        return Promise.resolve({
          backend: 'structured_fallback',
          fallback_reason: 'semantic backend unavailable',
          ids: [101],
          items: [
            {
              id: 101,
              desc: 'Helmet detected',
              control_code: 'dock-control',
              stream_name: 'Dock Camera',
            },
          ],
        });
      }
      if (url === API.alarmPoll) {
        return Promise.resolve({ new_count: 0, newest_id: 101 });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'success' });

    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /语义检索/i }));

    const dialog = await screen.findByRole('dialog', { name: '语义检索' });
    fireEvent.change(within(dialog).getByLabelText('检索语句'), { target: { value: 'helmet loading' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /^检索$/ }));

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith(
        API.alarmSemanticSearch,
        expect.objectContaining({ q: 'helmet loading' }),
      );
    });

    expect(await within(dialog).findByText('Helmet detected')).toBeInTheDocument();
    expect(within(dialog).getByText('structured_fallback')).toBeInTheDocument();
  });

  it('initializes unread review params from the bootstrap query so notification jumps land correctly', () => {
    mockGetBootstrapQuery.mockReturnValue(new URLSearchParams('mode=review&review_tab=unread&unread=1&p=2&ps=50'));
    mockUseApi.mockReturnValue({
      data: {
        rows: [],
        total: 0,
        presets: { items: [], target_mode: 'review' },
        page: 2,
        page_size: 50,
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet.mockResolvedValue({ new_count: 0, newest_id: 0 });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'success' });

    renderPage();

    expect(mockUseApi.mock.calls[0][0]).toBe(API.alarms);
    expect(mockUseApi.mock.calls[0][1]).toMatchObject({
      mode: 'review',
      review_tab: 'unread',
      unread: '1',
      p: '2',
      ps: '50',
    });
  });

  it('derives review mode from the review route even when the query string omits mode', () => {
    mockGetBootstrapPath.mockReturnValue('/alarm/review');
    mockGetBootstrapQuery.mockReturnValue(new URLSearchParams('review_tab=unread&unread=1'));
    mockUseApi.mockReturnValue({
      data: {
        rows: [],
        total: 0,
        presets: { items: [], target_mode: 'review' },
        page: 1,
        page_size: 20,
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });
    mockApiGet.mockResolvedValue({ new_count: 0, newest_id: 0 });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'success' });

    renderPage();

    expect(mockUseApi.mock.calls[0][1]).toMatchObject({
      mode: 'review',
      review_tab: 'unread',
      unread: '1',
    });
  });

  it('renders alarm thumbnails from image_url so preview can open from the list', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 101,
            desc: 'Helmet detected',
            workflow_status: 'new',
            stream_name: 'Dock Camera',
            stream_code: 'dock-1',
            algorithm_code: 'helmet-detector',
            control_code: 'dock-control',
            create_time: '2026-03-30 12:00:00',
            image_url: '/static/upload/alarm/dock-1/frame-1.jpg',
          },
        ],
        total: 1,
        presets: { items: [], target_mode: 'list' },
        page: 1,
        page_size: 20,
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });

    mockApiGet.mockImplementation((url) => {
      if (url === API.alarmPoll) {
        return Promise.resolve({ new_count: 0, newest_id: 101 });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'success' });

    const { container } = renderPage();

    await screen.findByText('Helmet detected');

    expect(screen.getByRole('link', { name: 'Helmet detected' })).toHaveAttribute(
      'href',
      '/alarm/detail?id=101',
    );

    const thumbnail = container.querySelector('.ant-image-img');
    expect(thumbnail).toHaveAttribute('src', '/static/upload/alarm/dock-1/frame-1.jpg');
  });

  it('renders a video preview launcher when the alarm only has video media', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 102,
            desc: 'Person detected',
            workflow_status: 'new',
            stream_name: 'Dock Camera',
            stream_code: 'dock-1',
            algorithm_code: 'person-detector',
            control_code: 'dock-control',
            create_time: '2026-03-30 12:01:00',
            image_url: '',
            video_url: '/static/upload/alarm/dock-1/clip-1.mp4',
          },
        ],
        total: 1,
        presets: { items: [], target_mode: 'list' },
        page: 1,
        page_size: 20,
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });

    mockApiGet.mockImplementation((url) => {
      if (url === API.alarmPoll) {
        return Promise.resolve({ new_count: 0, newest_id: 102 });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'success' });

    const { container } = renderPage();

    await screen.findByText('Person detected');

    const previewButton = screen.getByRole('button', { name: '预览视频 102' });
    fireEvent.click(previewButton);

    const video = container.ownerDocument.body.querySelector('video');
    expect(video).toBeInTheDocument();
    expect(video).toHaveAttribute('src', '/static/upload/alarm/dock-1/clip-1.mp4');
  });

  it('sends batch read, unhandled, and delete actions through the legacy alarm handle api', async () => {
    const run = vi.fn();
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 101,
            desc: 'Helmet detected',
            workflow_status: 'new',
            stream_name: 'Dock Camera',
            stream_code: 'dock-1',
            algorithm_code: 'helmet-detector',
            control_code: 'dock-control',
            create_time: '2026-03-30 12:00:00',
            image_path: '',
          },
        ],
        total: 1,
        presets: { items: [], target_mode: 'list' },
        page: 1,
        page_size: 20,
      },
      loading: false,
      error: null,
      run,
    });

    mockApiGet.mockImplementation((url) => {
      if (url === API.alarmPoll) {
        return Promise.resolve({ new_count: 0, newest_id: 101 });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'success' });

    renderPage();

    const checkboxes = await screen.findAllByRole('checkbox');
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByRole('button', { name: '批量已读' }));
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        API.postHandleAlarm,
        expect.objectContaining({ handle: 'read', alarm_ids_str: '101' }),
      );
    });

    fireEvent.click(await waitForButton('恢复未处理'));
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        API.postHandleAlarm,
        expect.objectContaining({ handle: 'unhandled', alarm_ids_str: '101' }),
      );
    });

    fireEvent.click(await waitForButton('删除告警'));
    const deleteDialog = await screen.findByRole('dialog', { name: '确认删除告警？' });
    fireEvent.click(within(deleteDialog).getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        API.postHandleAlarm,
        expect.objectContaining({ handle: 'delete', alarm_ids_str: '101' }),
      );
    });

    expect(run).toHaveBeenCalled();
  });

  it('opens a handled remark modal and submits batch handled through the legacy alarm handle api', async () => {
    mockUseApi.mockReturnValue({
      data: {
        rows: [
          {
            id: 101,
            desc: 'Helmet detected',
            workflow_status: 'new',
            stream_name: 'Dock Camera',
            stream_code: 'dock-1',
            algorithm_code: 'helmet-detector',
            control_code: 'dock-control',
            create_time: '2026-03-30 12:00:00',
            image_path: '',
          },
        ],
        total: 1,
        presets: { items: [], target_mode: 'list' },
        page: 1,
        page_size: 20,
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });

    mockApiGet.mockImplementation((url) => {
      if (url === API.alarmPoll) {
        return Promise.resolve({ new_count: 0, newest_id: 101 });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockApiPost.mockResolvedValue({ code: 1000, msg: 'success' });

    renderPage();

    const checkboxes = await screen.findAllByRole('checkbox');
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByRole('button', { name: '批量已处理' }));

    const dialog = await screen.findByRole('dialog', { name: '批量处理告警' });
    fireEvent.change(within(dialog).getByLabelText('处理备注'), { target: { value: '人工复核完成' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '提交处理' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        API.postHandleAlarm,
        expect.objectContaining({
          handle: 'handled',
          alarm_ids_str: '101',
          handled_remark: '人工复核完成',
        }),
      );
    });
  });
});

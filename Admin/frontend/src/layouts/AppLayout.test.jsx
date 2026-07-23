import React from 'react';
import { fireEvent } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

/* polyfill matchMedia before any module-level code in themeStore.js runs */
vi.hoisted(() => {
  if (typeof window !== 'undefined' && !window.matchMedia) {
    window.matchMedia = (query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }
});

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import AppLayout from './AppLayout';
import { resetBootstrapCache } from '../bootstrap';
import { API } from '../api/endpoints';

const { mockUseApi } = vi.hoisted(() => ({
  mockUseApi: vi.fn(),
}));

vi.mock('../hooks/useApi', () => ({
  default: (...args) => mockUseApi(...args),
}));

function mountBootstrap(queryString = '', userOverrides = {}, deploymentMode = 'edge') {
  document.body.innerHTML = `
    <script id="beacon-bootstrap" type="application/json">
      ${JSON.stringify({
        path: '/algorithm/add',
        queryString,
        siteName: 'Beacon',
        siteTitle: 'Beacon 智能边缘平台',
        siteLogo: '/static/images/logo.png',
        projectVersion: 'v1.0.0',
        deploymentMode,
        user: { id: '1', username: 'admin', isStaff: true, isSuperuser: false, ...userOverrides },
      })}
    </script>
  `;
  resetBootstrapCache();
}

describe('AppLayout', () => {
  beforeAll(() => {
    window.matchMedia = window.matchMedia || vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  beforeEach(() => {
    mockUseApi.mockReturnValue({
      data: { items: [] },
      loading: false,
      error: null,
      run: vi.fn(),
    });
  });

  afterEach(() => {
    cleanup();
    document.body.innerHTML = '';
    window.sessionStorage.clear();
    resetBootstrapCache();
    vi.clearAllMocks();
  });

  it('keeps the full shell chrome in normal mode', async () => {
    mountBootstrap('');
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <AppLayout currentPath="/algorithm/add">
        <div>algorithm form</div>
      </AppLayout>,
    );

    expect(screen.getByText('Beacon 智能边缘平台')).toBeInTheDocument();
    expect(screen.getByText('系统总览')).toBeInTheDocument();
    expect(screen.getByText('视频资源')).toBeInTheDocument();
    expect(screen.getByText('大屏监控')).toBeInTheDocument();
    expect(screen.getByText('告警中心')).toBeInTheDocument();
    expect(screen.getByText('布控中心')).toBeInTheDocument();
    expect(screen.getByText('视频与算法')).toBeInTheDocument();
    expect(screen.getByText('云中心')).toBeInTheDocument();
    expect(screen.getByText('平台运维')).toBeInTheDocument();
    expect(screen.getByText('系统管理')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /算法管理/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('button', { name: /系统设置/ })).not.toBeInTheDocument();
    expect(screen.getByText('Beacon v1.0.0')).toBeInTheDocument();
    expect(screen.getByLabelText('通知中心')).toBeInTheDocument();
    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(screen.getByText('algorithm form')).toBeInTheDocument();
    await waitFor(() => {
      expect(consoleErrorSpy.mock.calls.flat().join('\n')).not.toContain('not wrapped in act');
    });
    consoleErrorSpy.mockRestore();
  });

  it('uses the backend project version in the compact sidebar', () => {
    mountBootstrap('');

    render(
      <AppLayout currentPath="/algorithm/add">
        <div>algorithm form</div>
      </AppLayout>,
    );

    fireEvent.click(screen.getByLabelText('折叠侧边栏'));

    expect(screen.getByText('v1.0.0')).toBeInTheDocument();
    expect(screen.queryByText('v2.3')).not.toBeInTheDocument();
    expect(document.querySelectorAll('.beacon-shell-nav__item')).toHaveLength(6);
    expect(screen.queryByText('视频与算法')).not.toBeInTheDocument();
  });

  it('removes sider and header chrome in popup mode', () => {
    mountBootstrap('popup=1&code=alg-popup');

    render(
      <AppLayout currentPath="/algorithm/add">
        <div>popup algorithm form</div>
      </AppLayout>,
    );

    expect(screen.getByText('popup algorithm form')).toBeInTheDocument();
    expect(screen.queryByText('系统总览')).not.toBeInTheDocument();
    expect(screen.queryByText('admin')).not.toBeInTheDocument();
  });

  it('keeps only one sidebar item selected when multiple nav entries share a route', () => {
    mountBootstrap('');

    render(
      <AppLayout currentPath="/ops/platform">
        <div>platform page</div>
      </AppLayout>,
    );

    const selectedItems = document.querySelectorAll('.beacon-shell-nav__item[aria-current="page"]');
    expect(selectedItems).toHaveLength(1);
    expect(screen.getByRole('button', { name: /平台概览/ })).toHaveAttribute('aria-current', 'page');
  });

  it('shows a dedicated license manager entry instead of selecting generic system settings', () => {
    mountBootstrap('');

    render(
      <AppLayout currentPath="/license/manager">
        <div>license page</div>
      </AppLayout>,
    );

    const selectedItems = document.querySelectorAll('.beacon-shell-nav__item[aria-current="page"]');
    expect(selectedItems).toHaveLength(1);
    expect(screen.getByRole('button', { name: /授权管理/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTitle('系统设置')).not.toHaveAttribute('aria-current');
  });

  it('shows a dedicated entry for the cloud permissions workspace', () => {
    mountBootstrap('', {}, 'cloud');

    render(
      <AppLayout currentPath="/cloud/iam">
        <div>cloud iam</div>
      </AppLayout>,
    );

    expect(screen.getByRole('button', { name: /云端权限/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('云中心')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /远程共享/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /数字人监管/ })).toBeInTheDocument();
  });

  it('keeps one digital human entry selected across its existing routes', () => {
    mountBootstrap('');

    render(
      <AppLayout currentPath="/digital-human/ops-report">
        <div>digital human ops report</div>
      </AppLayout>,
    );

    expect(screen.getByRole('button', { name: /数字人监管/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('button', { name: /运维报告/ })).not.toBeInTheDocument();
  });

  it('keeps digital human system settings separate from the global config route', () => {
    mountBootstrap('');

    render(
      <AppLayout currentPath="/digital-human/system-settings">
        <div>digital human system settings</div>
      </AppLayout>,
    );

    expect(screen.getByRole('button', { name: /数字人监管/ })).toHaveAttribute('aria-current', 'page');
    expect(document.querySelectorAll('.beacon-shell-nav__item[aria-current="page"]')).toHaveLength(1);
  });

  it('hides digital human entries from non-admin bootstrap users', () => {
    mountBootstrap('', { id: '2', username: 'viewer', isStaff: false, isSuperuser: false });

    render(
      <AppLayout currentPath="/algorithm/add">
        <div>viewer page</div>
      </AppLayout>,
    );

    expect(screen.queryByRole('button', { name: /数字人监管/ })).not.toBeInTheDocument();
    expect(screen.getByText('云中心')).toBeInTheDocument();
  });

  it('renders real notification links from the notifications api', async () => {
    mountBootstrap('');
    mockUseApi.mockReturnValue({
      data: {
        items: [
          {
            id: 'alarm-unread-1-101',
            kind: 'alarm_unread',
            title: '1 条未处理告警',
            description: '最近告警：东门逆行',
            time: '4 分钟前',
            href: '/alarm/review?mode=review&review_tab=unread&unread=1',
            level: 'warning',
          },
        ],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });

    render(
      <AppLayout currentPath="/algorithm/add">
        <div>algorithm form</div>
      </AppLayout>,
    );

    expect(mockUseApi).toHaveBeenCalledWith(API.notifications, undefined, expect.any(Object));

    fireEvent.click(screen.getByLabelText('通知中心'));

    const link = await screen.findByRole('link', { name: /1 条未处理告警/i });
    expect(link).toHaveAttribute('href', '/alarm/review?mode=review&review_tab=unread&unread=1');
    expect(screen.getByText('最近告警：东门逆行')).toBeInTheDocument();
  });

  it('persists clicked notifications as read across remounts so the badge clears after navigation', async () => {
    mountBootstrap('');
    mockUseApi.mockReturnValue({
      data: {
        items: [
          {
            id: 'alarm-unread-1-101',
            kind: 'alarm_unread',
            title: '1 条未处理告警',
            description: '最近告警：东门逆行',
            time: '4 分钟前',
            href: '/alarm/review?mode=review&review_tab=unread&unread=1',
            level: 'warning',
          },
        ],
      },
      loading: false,
      error: null,
      run: vi.fn(),
    });

    const { unmount } = render(
      <AppLayout currentPath="/algorithm/add">
        <div>algorithm form</div>
      </AppLayout>,
    );

    expect(document.querySelector('.ant-badge-count')).not.toBeNull();

    fireEvent.click(screen.getByLabelText('通知中心'));
    const link = await screen.findByRole('link', { name: /1 条未处理告警/i });
    link.addEventListener('click', (event) => event.preventDefault());
    fireEvent.click(link);

    await waitFor(() => {
      expect(document.querySelector('.ant-badge-count')).toBeNull();
    });

    unmount();

    render(
      <AppLayout currentPath="/alarm/review">
        <div>alarm review</div>
      </AppLayout>,
    );

    expect(document.querySelector('.ant-badge-count')).toBeNull();
  });

  it('keeps only one secondary section open and opens the active section after navigation', () => {
    mountBootstrap('');

    const { unmount } = render(
      <AppLayout currentPath="/controls">
        <div>controls</div>
      </AppLayout>,
    );

    expect(screen.queryByRole('button', { name: /平台概览/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /系统设置/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /平台运维/ }));
    expect(screen.getByRole('button', { name: /平台概览/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /系统管理/ }));
    expect(screen.queryByRole('button', { name: /平台概览/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /系统设置/ })).toBeInTheDocument();

    unmount();

    render(
      <AppLayout currentPath="/config/system">
        <div>system settings</div>
      </AppLayout>,
    );

    expect(screen.getByRole('button', { name: /系统设置/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('button', { name: /平台概览/ })).not.toBeInTheDocument();
  });
});

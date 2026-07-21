import React from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App as AntdApp, ConfigProvider } from 'antd';
import ProfilePage from './ProfilePage';
import { resetBootstrapCache } from '../../bootstrap';

function renderPage() {
  return render(
    <ConfigProvider>
      <AntdApp>
        <ProfilePage />
      </AntdApp>
    </ConfigProvider>,
  );
}

function buildTemplate({
  username = 'tester',
  email = 'tester@example.com',
  totpEnabled = false,
  totpSecret = '',
  totpOtpauthUri = '',
  recoveryUnusedCount = 0,
  recoveryCodes = [],
}) {
  return `
    <div class="bcn-page">
      <div id="profileMsg"></div>
      <input id="username" value="${username}" readonly>
      <input id="email" value="${email}">
      <input type="password" id="old_password" value="">
      <input type="password" id="new_password" value="">
      <div class="totp-section">
        <div class="totp-status">
          ${totpEnabled
            ? '<span class="bcn-pill bcn-pill-success">已启用</span>'
            : '<span class="bcn-pill bcn-pill-muted">未启用</span>'}
        </div>
        ${totpSecret ? `
          <div class="totp-secret-block">
            <span class="label-text">TOTP 密钥</span>
            ${totpSecret}
          </div>
        ` : ''}
        ${totpOtpauthUri ? `
          <div class="totp-secret-block">
            <span class="label-text">otpauth:// URI (可复制到认证器 App)</span>
            ${totpOtpauthUri}
          </div>
        ` : ''}
        <input type="text" id="totp_code" value="">
        <button type="button" data-totp="totp_generate">生成密钥</button>
        <button type="button" data-totp="totp_enable">启用 TOTP</button>
        <button type="button" data-totp="totp_disable">停用 TOTP</button>
        <button type="button" data-totp="totp_reauth">敏感操作二次确认</button>
        <button type="button" data-totp="totp_recovery_generate">生成恢复码</button>
        <p>
          恢复码：用于在无法获取 TOTP 时登录（一次性）。剩余：
          <strong>${recoveryUnusedCount}</strong>
        </p>
        ${recoveryCodes.length ? `
          <div class="recovery-codes">
            ${recoveryCodes.map(code => `<code>${code}</code>`).join('')}
          </div>
        ` : ''}
      </div>
      <button type="button" id="btnCancel">返回</button>
      <button type="button" id="btnSave">保存资料</button>
    </div>
  `;
}

function wrapHtml(templateHtml) {
  return `
    <!DOCTYPE html>
    <html lang="zh-Hans">
      <body>
        <template id="beacon-legacy-content">${templateHtml}</template>
      </body>
    </html>
  `;
}

function mountShell(templateHtml) {
  document.body.innerHTML = `
    <script id="beacon-bootstrap" type="application/json">
      ${JSON.stringify({
        path: '/profile',
        queryString: '',
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

describe('ProfilePage', () => {
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
    vi.restoreAllMocks();
    document.body.innerHTML = '';
    resetBootstrapCache();
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });

  it('hydrates profile fields from the legacy template and submits save_profile back to the html endpoint', async () => {
    mountShell(buildTemplate({
      username: 'alice',
      email: 'alice@example.com',
      totpEnabled: false,
      recoveryUnusedCount: 0,
    }));

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'text/html; charset=utf-8' },
      text: async () => wrapHtml(buildTemplate({
        username: 'alice',
        email: 'alice+next@example.com',
        totpEnabled: false,
        recoveryUnusedCount: 0,
      })),
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    expect(screen.getByRole('heading', { name: '个人资料' })).toBeInTheDocument();
    expect(screen.getByLabelText('用户名')).toHaveValue('alice');
    expect(screen.getByLabelText('邮箱')).toHaveValue('alice@example.com');

    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'alice+next@example.com' } });
    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'Correct12345' } });
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'Changed12345' } });
    fireEvent.click(screen.getByRole('button', { name: /保存资料/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/profile');
    expect(options.method).toBe('POST');
    expect(options.body.get('action')).toBe('save_profile');
    expect(options.body.get('email')).toBe('alice+next@example.com');
    expect(options.body.get('old_password')).toBe('Correct12345');
    expect(options.body.get('new_password')).toBe('Changed12345');

    await waitFor(() => {
      expect(screen.getByLabelText('邮箱')).toHaveValue('alice+next@example.com');
    });

    expect(screen.getByLabelText('当前密码')).toHaveValue('');
    expect(screen.getByLabelText('新密码')).toHaveValue('');
  });

  it('submits totp_generate and refreshes the server returned totp state from html', async () => {
    mountShell(buildTemplate({
      username: 'alice',
      email: 'alice@example.com',
      totpEnabled: false,
      recoveryUnusedCount: 0,
    }));

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'text/html; charset=utf-8' },
      text: async () => wrapHtml(buildTemplate({
        username: 'alice',
        email: 'alice@example.com',
        totpEnabled: false,
        totpSecret: 'JBSWY3DPEHPK3PXP',
        totpOtpauthUri: 'otpauth://totp/Beacon:alice?secret=JBSWY3DPEHPK3PXP',
        recoveryUnusedCount: 0,
      })),
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /生成密钥/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/profile');
    expect(options.body.get('action')).toBe('totp_generate');
    expect(options.body.get('totp_code')).toBe('');

    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument();
    expect(screen.getByText(/otpauth:\/\/totp\/Beacon:alice/)).toBeInTheDocument();
  });
});

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { App as AntdApp, ConfigProvider } from 'antd';
import LoginPage from './LoginPage';

function renderPage() {
  return render(
    <ConfigProvider>
      <AntdApp>
        <LoginPage />
      </AntdApp>
    </ConfigProvider>
  );
}

describe('LoginPage', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () => `
          <div id="loginConfig" data-captcha-enabled="1"></div>
          <a href="/login/oidc/start">SSO 登录</a>
        `,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: async () => ({ code: 0, msg: '验证码错误' }),
      });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    global.fetch = originalFetch;
  });

  it('hydrates backend login capabilities and submits the aligned login contract', async () => {
    renderPage();

    expect(await screen.findByLabelText('图形验证码')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'SSO 登录' })).toHaveAttribute('href', '/__beacon_backend/login/oidc/start');

    fireEvent.change(screen.getByLabelText('用户名 / 邮箱'), { target: { value: 'ops-user' } });
    fireEvent.change(screen.getByLabelText('登录密码'), { target: { value: 'Secret123' } });
    fireEvent.change(screen.getByLabelText('TOTP / 恢复码'), { target: { value: '654321' } });
    fireEvent.change(screen.getByLabelText('图形验证码'), { target: { value: '1234' } });
    fireEvent.click(screen.getByRole('button', { name: /进入控制台/ }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    const [submitUrl, submitOptions] = global.fetch.mock.calls[1];
    expect(submitUrl).toBe('/__beacon_backend/login');
    expect(submitOptions.method).toBe('POST');
    expect(submitOptions.body.get('username')).toBe('ops-user');
    expect(submitOptions.body.get('password')).toBe('Secret123');
    expect(submitOptions.body.get('totp_code')).toBe('654321');
    expect(submitOptions.body.get('verify_code')).toBe('1234');
    expect(await screen.findByText('验证码错误')).toBeInTheDocument();
  });
});

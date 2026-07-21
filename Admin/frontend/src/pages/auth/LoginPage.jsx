import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Spin } from 'antd';
import {
  LockOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { apiPostFormRaw } from '../../api/client';
import { getSiteBranding } from '../../bootstrap';

const DEV_BACKEND_PREFIX = import.meta.env.DEV ? '/__beacon_backend' : '';
const DEFAULT_CAPABILITIES = {
  captchaEnabled: false,
  oidcEnabled: false,
  workspaceName: '',
};

function authUrl(path) {
  return `${DEV_BACKEND_PREFIX}${path}`;
}

function parseLoginCapabilities(html) {
  if (!html) return DEFAULT_CAPABILITIES;

  const doc = new DOMParser().parseFromString(html, 'text/html');
  const loginConfig = doc.getElementById('loginConfig');
  const supportStrong = doc.querySelector('.login-support-item strong');

  return {
    captchaEnabled: loginConfig?.dataset?.captchaEnabled === '1',
    oidcEnabled: Boolean(doc.querySelector('a[href="/login/oidc/start"]')),
    workspaceName: supportStrong?.textContent?.trim() || '',
  };
}

function createFeedback(type, message) {
  return { type, message };
}

export default function LoginPage() {
  const branding = getSiteBranding();
  const redirectRef = useRef(null);
  const [capabilities, setCapabilities] = useState(DEFAULT_CAPABILITIES);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(true);
  const [probeError, setProbeError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [captchaSeed, setCaptchaSeed] = useState(() => Date.now());
  const [form, setForm] = useState({
    username: '',
    password: '',
    totpCode: '',
    verifyCode: '',
  });

  useLayoutEffect(() => {
    const root = document.documentElement;
    const prevTheme = root.dataset.theme;
    const prevPage = root.dataset.page;
    root.dataset.theme = 'dark';
    root.dataset.page = 'login';
    return () => {
      if (prevTheme === undefined) delete root.dataset.theme;
      else root.dataset.theme = prevTheme;
      if (prevPage === undefined) delete root.dataset.page;
      else root.dataset.page = prevPage;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function probeBackendLogin() {
      try {
        const res = await fetch(authUrl('/login'), {
          method: 'GET',
          credentials: 'same-origin',
          headers: {
            Accept: 'text/html',
          },
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const html = await res.text();
        if (!active) return;

        setCapabilities({
          ...DEFAULT_CAPABILITIES,
          ...parseLoginCapabilities(html),
        });
        setProbeError('');
      } catch {
        if (!active) return;
        setCapabilities(DEFAULT_CAPABILITIES);
        setProbeError('未能读取后端登录策略,当前以基础登录模式展示。');
      } finally {
        if (active) {
          setCapabilitiesLoading(false);
        }
      }
    }

    probeBackendLogin();

    return () => {
      active = false;
      if (redirectRef.current) {
        globalThis.clearTimeout(redirectRef.current);
      }
    };
  }, []);

  const captchaSrc = useMemo(() => {
    return `${authUrl('/getVerifyCode?action=login')}&t=${captchaSeed}`;
  }, [captchaSeed]);

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function refreshCaptcha() {
    setCaptchaSeed(Date.now());
  }

  function validateForm() {
    const username = String(form.username || '').trim();
    const password = String(form.password || '').trim();
    const verifyCode = String(form.verifyCode || '').trim();

    if (!username) {
      setFeedback(createFeedback('error', '请输入用户名或邮箱'));
      return false;
    }

    if (!password) {
      setFeedback(createFeedback('error', '请输入登录密码'));
      return false;
    }

    if (capabilities.captchaEnabled && verifyCode.length !== 4) {
      setFeedback(createFeedback('error', '验证码格式不正确'));
      return false;
    }

    return true;
  }

  async function handleSubmit(event) {
    event.preventDefault();

    if (submitting || !validateForm()) {
      return;
    }

    const payload = new FormData();
    payload.append('username', String(form.username || '').trim());
    payload.append('password', String(form.password || '').trim());
    payload.append('totp_code', String(form.totpCode || '').trim());

    if (capabilities.captchaEnabled) {
      payload.append('verify_code', String(form.verifyCode || '').trim());
    }

    setSubmitting(true);
    setFeedback(null);

    try {
      const result = await apiPostFormRaw(authUrl('/login'), payload);
      const code = Number(result?.code || 0);
      const message = String(result?.msg || '');

      if (code === 1000) {
        setFeedback(createFeedback('success', message || '登录成功,正在进入控制台'));
        redirectRef.current = globalThis.setTimeout(() => {
          globalThis.location.assign('/');
        }, 900);
        return;
      }

      setFeedback(createFeedback('error', message || '登录失败'));
      if (capabilities.captchaEnabled) {
        updateField('verifyCode', '');
        refreshCaptcha();
      }
    } catch (error) {
      setFeedback(createFeedback('error', error?.message || '网络异常,请确认服务连接正常'));
      if (capabilities.captchaEnabled) {
        refreshCaptcha();
      }
    } finally {
      setSubmitting(false);
    }
  }

  const workspaceName = capabilities.workspaceName || branding.title || branding.name;
  let securityMode = 'Password / TOTP';
  if (capabilities.captchaEnabled) {
    securityMode = 'Password / TOTP / Captcha';
  }
  if (capabilitiesLoading) {
    securityMode = '读取安全策略中';
  }
  const brandInitial = String(branding.name || 'B').slice(0, 1);

  return (
    <main className="beacon-login" aria-label="Beacon 登录">
      <div className="beacon-login__shell">
        <section className="beacon-login__copy">
          <div className="beacon-login__eyebrow">
            <span className="beacon-login__eyebrow-dot" aria-hidden="true" />
            <span>Beacon · Operator</span>
          </div>

          <h1 className="beacon-login__hero">
            Quiet access.<br />
            Strict contract.
          </h1>

          <p className="beacon-login__tagline">
            面向视频接入、告警处置与分析器可用性的统一入口。前端只做契约适配,实际字段与返回结果以后端当前登录能力为准。
          </p>

          <div className="beacon-login__workspace">
            <div className="beacon-login__mark">
              {branding.logo ? (
                <img src={branding.logo} alt={branding.name || 'Beacon'} />
              ) : (
                <span>{brandInitial}</span>
              )}
            </div>
            <div className="beacon-login__workspace-body">
              <span className="beacon-login__workspace-label">Workspace</span>
              <span className="beacon-login__workspace-value">{workspaceName}</span>
            </div>
          </div>
        </section>

        <section className="beacon-login__panel">
          <header className="beacon-login__panel-header">
            <span className="beacon-login__panel-label">Sign in</span>
            <span className="beacon-login__panel-status">
              {capabilitiesLoading ? (
                <Spin size="small" />
              ) : (
                <span className="beacon-login__panel-status-dot" aria-hidden="true" />
              )}
              <span className="beacon-login__panel-status-text">{securityMode}</span>
            </span>
          </header>

          {probeError ? (
            <Alert
              className="beacon-login__alert beacon-login__alert--warning"
              type="warning"
              message={probeError}
              showIcon
              role="alert"
              aria-live="polite"
            />
          ) : null}

          {feedback ? (
            <Alert
              className={`beacon-login__alert beacon-login__alert--${feedback.type}`}
              type={feedback.type}
              message={feedback.message}
              showIcon
              role="alert"
              aria-live="polite"
            />
          ) : null}

          <form className="beacon-login__form" onSubmit={handleSubmit} aria-busy={submitting}>
            <label className="beacon-login__field">
              <span className="beacon-login__field-label">用户名 / 邮箱</span>
              <Input
                aria-label="用户名 / 邮箱"
                autoComplete="username"
                size="large"
                prefix={<UserOutlined />}
                placeholder="请输入用户名或邮箱"
                value={form.username}
                onChange={(event) => updateField('username', event.target.value)}
              />
            </label>

            <label className="beacon-login__field">
              <span className="beacon-login__field-label">登录密码</span>
              <Input.Password
                aria-label="登录密码"
                autoComplete="current-password"
                size="large"
                prefix={<LockOutlined />}
                placeholder="请输入登录密码"
                value={form.password}
                onChange={(event) => updateField('password', event.target.value)}
              />
            </label>

            <div className="beacon-login__divider beacon-login__divider--second-factor" aria-hidden="true">
              <span className="beacon-login__divider-line" />
              <span className="beacon-login__divider-text">Second factor</span>
              <span className="beacon-login__divider-line" />
            </div>

            <div className="beacon-login__field beacon-login__field--with-hint">
              <label>
                <span className="beacon-login__field-label">TOTP / 恢复码</span>
                <Input
                  aria-label="TOTP / 恢复码"
                  autoComplete="one-time-code"
                  size="large"
                  prefix={<SafetyCertificateOutlined />}
                  placeholder="输入 6 位 TOTP 验证码或恢复码"
                  value={form.totpCode}
                  onChange={(event) => updateField('totpCode', event.target.value)}
                  className="beacon-login__input beacon-login__input--mono"
                />
              </label>
              <span className="beacon-login__field-hint">仅启用 TOTP 时必填</span>
            </div>

            {capabilities.captchaEnabled ? (
              <div className="beacon-login__captcha-row">
                <label className="beacon-login__field">
                  <span className="beacon-login__field-label">图形验证码</span>
                  <Input
                    aria-label="图形验证码"
                    inputMode="numeric"
                    maxLength={4}
                    size="large"
                    placeholder="输入右侧验证码"
                    value={form.verifyCode}
                    onChange={(event) => updateField('verifyCode', event.target.value)}
                  />
                </label>

                <button
                  type="button"
                  className="beacon-login__captcha"
                  onClick={refreshCaptcha}
                  aria-label="刷新验证码"
                >
                  <span className="beacon-login__captcha-img">
                    <img src={captchaSrc} alt="验证码" />
                  </span>
                  <span className="beacon-login__captcha-refresh" aria-hidden="true">
                    <ReloadOutlined />
                  </span>
                </button>
              </div>
            ) : null}

            <Button
              className="beacon-login__cta"
              type="primary"
              htmlType="submit"
              size="large"
              loading={submitting}
              block
            >
              {submitting ? (
                <span>验证中…</span>
              ) : (
                <>
                  <span>进入控制台</span>
                  <span className="beacon-login__cta-arrow" aria-hidden="true">→</span>
                </>
              )}
            </Button>

            {capabilities.oidcEnabled ? (
              <>
                <div className="beacon-login__divider beacon-login__divider--or" aria-hidden="true">
                  <span className="beacon-login__divider-line" />
                  <span className="beacon-login__divider-text">Or</span>
                  <span className="beacon-login__divider-line" />
                </div>
                <Button
                  className="beacon-login__sso"
                  href={authUrl('/login/oidc/start')}
                >
                  SSO 登录
                </Button>
              </>
            ) : null}
          </form>
        </section>
      </div>
    </main>
  );
}

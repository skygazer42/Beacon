import React, { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  Result,
  Row,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  KeyOutlined,
  SafetyCertificateOutlined,
  SaveOutlined,
  UserOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import { getBootstrapPath } from '../../bootstrap';
import { getCsrfToken } from '../../api/client';
import { parseProfileTemplateFromHtml, readProfileTemplate } from './profileTemplate';

const { Paragraph, Text } = Typography;

const cardStyle = {
  borderRadius: 16,
  marginBottom: 16,
};

function buildActionMessage(action, previousState, nextState, submittedFields) {
  if (nextState.messageText) {
    return { level: 'info', text: nextState.messageText };
  }

  if (action === 'save_profile') {
    return buildSaveProfileMessage(previousState, nextState, submittedFields);
  }

  if (action === 'totp_generate') {
    return buildTotpGenerateMessage(previousState, nextState);
  }

  if (action === 'totp_enable') {
    return buildTotpToggleMessage(nextState.totpEnabled, true);
  }

  if (action === 'totp_disable') {
    return buildTotpToggleMessage(nextState.totpEnabled, false);
  }

  if (action === 'totp_recovery_generate') {
    return buildRecoveryMessage(previousState, nextState);
  }

  if (action === 'totp_reauth') {
    return { level: 'info', text: '二次确认请求已提交。当前后端页面不会返回可直接判定的成功标记，请继续执行敏感操作验证。' };
  }

  return { level: 'info', text: '页面已按后端状态刷新。' };
}

function buildSaveProfileMessage(previousState, nextState, submittedFields) {
  const previousEmail = String(previousState.email || '');
  const submittedEmail = String(submittedFields.email || '');
  if (!submittedEmail || submittedEmail === previousEmail) {
    return { level: 'info', text: '保存请求已提交。密码变更是否生效需以后端实际登录结果为准。' };
  }
  if (nextState.email === submittedEmail) {
    return { level: 'success', text: '资料已按后端状态刷新。' };
  }
  return { level: 'error', text: '保存未生效。当前后端要求原密码正确且新密码满足策略。' };
}

function buildTotpGenerateMessage(previousState, nextState) {
  if (nextState.totpSecret && nextState.totpSecret !== previousState.totpSecret) {
    return { level: 'success', text: 'TOTP 密钥已刷新，请录入认证器后再启用。' };
  }
  return { level: 'error', text: 'TOTP 密钥未更新。' };
}

function buildTotpToggleMessage(totpEnabled, enabling) {
  if (enabling) {
    return totpEnabled
      ? { level: 'success', text: 'TOTP 已按后端状态启用。' }
      : { level: 'error', text: '启用未生效，请检查 6 位验证码。' };
  }
  return totpEnabled
    ? { level: 'error', text: '停用未生效，请检查 6 位验证码。' }
    : { level: 'success', text: 'TOTP 已按后端状态停用。' };
}

function buildRecoveryMessage(previousState, nextState) {
  const refreshed = nextState.recoveryCodes.length > 0 || nextState.recoveryUnusedCount > previousState.recoveryUnusedCount;
  return refreshed
    ? { level: 'success', text: '恢复码已按后端状态刷新。' }
    : { level: 'error', text: '恢复码未生成，请确认 TOTP 已启用。' };
}

function showActionMessage(messageApi, actionMessage) {
  if (actionMessage.level === 'success') {
    messageApi.success(actionMessage.text);
    return;
  }

  if (actionMessage.level === 'error') {
    messageApi.error(actionMessage.text);
    return;
  }

  messageApi.info(actionMessage.text);
}

export default function ProfilePage() {
  const { message } = App.useApp();
  const path = getBootstrapPath();
  const template = readProfileTemplate();
  const [serverState, setServerState] = useState(template);
  const [email, setEmail] = useState(template?.email || '');
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [submittingAction, setSubmittingAction] = useState('');

  if (!template || !serverState) {
    return (
      <Result
        status="warning"
        title="未找到个人资料模板"
        subTitle="当前页面缺少后端兼容模板，无法安全对齐现有 Django /profile 契约。"
      />
    );
  }

  async function submitProfileAction(action, fields = {}) {
    const previousState = serverState;
    const formData = new FormData();
    formData.append('action', action);
    Object.entries(fields).forEach(([key, value]) => {
      formData.append(key, String(value ?? ''));
    });

    setSubmittingAction(action);

    try {
      const response = await fetch(path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': getCsrfToken(),
        },
        body: formData,
      });

      if (response.status === 401 || response.status === 403) {
        globalThis.location.href = '/login';
        return;
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const html = await response.text();
      const nextState = parseProfileTemplateFromHtml(html);
      if (!nextState) {
        throw new Error('后端返回内容无法解析');
      }

      setServerState(nextState);
      setEmail(nextState.email || '');
      setOldPassword('');
      setNewPassword('');
      setTotpCode('');

      showActionMessage(message, buildActionMessage(action, previousState, nextState, fields));
    } catch (error) {
      message.error(error?.message || '请求失败');
    } finally {
      setSubmittingAction('');
    }
  }

  function handleSave() {
    const nextEmail = String(email || '').trim();
    if (!nextEmail) {
      message.error('请填写邮箱地址');
      return;
    }
    if (!oldPassword) {
      message.error('当前后端保存资料需要填写当前密码');
      return;
    }
    if (!newPassword || newPassword.length < 6) {
      message.error('当前后端保存资料需要填写至少 6 位的新密码');
      return;
    }
    if (newPassword.length > 128) {
      message.error('新密码长度不能超过 128 位');
      return;
    }

    submitProfileAction('save_profile', {
      email: nextEmail,
      old_password: oldPassword,
      new_password: newPassword,
    });
  }

  function handleTotpAction(action) {
    if ((action === 'totp_enable' || action === 'totp_disable' || action === 'totp_reauth') && !String(totpCode || '').trim()) {
      message.error('请输入 6 位 TOTP 验证码');
      return;
    }

    submitProfileAction(action, {
      totp_code: String(totpCode || '').trim(),
    });
  }

  return (
    <div>
      <PageHeader
        title="个人资料"
        icon={<UserOutlined />}
        description="个人信息与安全设置"
        extra={(
          <Button icon={<ArrowLeftOutlined />} onClick={() => globalThis.history.back()}>
            返回
          </Button>
        )}
      />

      <Alert
        showIcon
        type="info"
        style={{ marginBottom: 16, borderRadius: 14 }}
        message="后端兼容说明"
        description="当前页面完全沿用现有 Django /profile 契约。保存资料时，后端要求同时提交当前密码和新密码；提交后页面会以后端返回的 HTML 结果重新同步状态。"
      />

      <Card
        title={(
          <Space size={8}>
            <UserOutlined />
            <span>基本信息</span>
          </Space>
        )}
        style={cardStyle}
        styles={{ body: { paddingBottom: 8 } }}
      >
        <Form layout="vertical">
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="用户名">
                <Input aria-label="用户名" value={serverState.username} readOnly />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="邮箱">
                <Input aria-label="邮箱" type="email" value={email} onChange={event => setEmail(event.target.value)} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item
                label="当前密码"
                extra="后端保存资料时会校验当前密码。"
              >
                <Input.Password
                  aria-label="当前密码"
                  value={oldPassword}
                  onChange={event => setOldPassword(event.target.value)}
                  autoComplete="current-password"
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                label="新密码"
                extra="当前后端要求至少 6 位。"
              >
                <Input.Password
                  aria-label="新密码"
                  value={newPassword}
                  onChange={event => setNewPassword(event.target.value)}
                  autoComplete="new-password"
                />
              </Form.Item>
            </Col>
          </Row>
          <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={submittingAction === 'save_profile'}
              onClick={handleSave}
            >
              保存资料
            </Button>
          </Space>
        </Form>
      </Card>

      <Card
        title={(
          <Space size={8}>
            <SafetyCertificateOutlined />
            <span>TOTP 二次验证</span>
          </Space>
        )}
        style={cardStyle}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div>
            <Text type="secondary" style={{ marginRight: 8 }}>状态</Text>
            {serverState.totpEnabled ? <Tag color="success">已启用</Tag> : <Tag>未启用</Tag>}
          </div>

          {serverState.totpSecret ? (
            <Card size="small" style={{ borderRadius: 12 }}>
              <Text strong>TOTP 密钥</Text>
              <Paragraph copyable style={{ margin: '8px 0 0' }}>
                {serverState.totpSecret}
              </Paragraph>
            </Card>
          ) : (
            <Alert
              type="warning"
              showIcon
              message="尚未生成密钥"
              description="点击“生成密钥”后，可将返回的 TOTP 密钥或 otpauth URI 录入认证器 App。"
            />
          )}

          {serverState.totpOtpauthUri ? (
            <Card size="small" style={{ borderRadius: 12 }}>
              <Text strong>otpauth:// URI</Text>
              <Paragraph copyable style={{ margin: '8px 0 0', wordBreak: 'break-all' }}>
                {serverState.totpOtpauthUri}
              </Paragraph>
              <Text type="secondary">
                当前前端不额外生成二维码，直接复制 URI 到认证器 App 即可。
              </Text>
            </Card>
          ) : null}

          <Form layout="vertical">
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item label="TOTP 验证码">
                  <Input
                    aria-label="TOTP 验证码"
                    maxLength={6}
                    value={totpCode}
                    onChange={event => setTotpCode(event.target.value)}
                    placeholder="输入 6 位验证码"
                  />
                </Form.Item>
              </Col>
            </Row>
          </Form>

          <Space wrap>
            <Button
              icon={<KeyOutlined />}
              loading={submittingAction === 'totp_generate'}
              onClick={() => handleTotpAction('totp_generate')}
            >
              生成密钥
            </Button>
            <Button
              type="primary"
              loading={submittingAction === 'totp_enable'}
              onClick={() => handleTotpAction('totp_enable')}
            >
              启用 TOTP
            </Button>
            <Button
              danger
              loading={submittingAction === 'totp_disable'}
              onClick={() => handleTotpAction('totp_disable')}
            >
              停用 TOTP
            </Button>
            <Button
              loading={submittingAction === 'totp_reauth'}
              onClick={() => handleTotpAction('totp_reauth')}
            >
              敏感操作二次确认
            </Button>
            <Button
              loading={submittingAction === 'totp_recovery_generate'}
              onClick={() => handleTotpAction('totp_recovery_generate')}
            >
              生成恢复码
            </Button>
          </Space>

          <Card size="small" style={{ borderRadius: 12 }}>
            <Text strong>恢复码</Text>
            <Paragraph type="secondary" style={{ marginTop: 8 }}>
              用于在无法获取 TOTP 时登录。当前未使用数量：{serverState.recoveryUnusedCount}
            </Paragraph>
            {serverState.recoveryCodes.length ? (
              <Space wrap>
                {serverState.recoveryCodes.map(code => (
                  <Text code key={code}>{code}</Text>
                ))}
              </Space>
            ) : (
              <Text type="secondary">当前页面没有一次性恢复码展示。</Text>
            )}
          </Card>
        </Space>
      </Card>
    </div>
  );
}

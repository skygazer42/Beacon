import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
} from 'antd';
import {
  ReloadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { getBootstrapQuery } from '../../bootstrap';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import SkeletonPage from '../../components/Skeleton';
import useDigitalHumanResource from './useDigitalHumanResource';
import {
  createDigitalHumanJwtAccount,
  deleteDigitalHumanDeviceAuthorization,
  deleteDigitalHumanJwtAccount,
  getDigitalHumanAiDiagnosisConfig,
  getDigitalHumanDeviceAuthorizationDetail,
  listDigitalHumanDeviceAuthorizations,
  listDigitalHumanJwtAccounts,
  rotateDigitalHumanJwtAccountSecret,
  saveDigitalHumanAiDiagnosisConfig,
  testDigitalHumanAiDiagnosisConnection,
  updateDigitalHumanDeviceAuthorization,
  updateDigitalHumanJwtAccountStatus,
} from './dataAdapter';
import './digitalHumanStyles.css';

const SYSTEM_SETTINGS_TABS = [
  { key: 'jwt-account', label: 'JWT 账户管理' },
  { key: 'authorization', label: '设备授权管理' },
  { key: 'llm', label: '大模型配置' },
];

const JWT_TTL_OPTIONS = [
  { label: '5 分钟', value: 5 },
  { label: '15 分钟', value: 15 },
  { label: '30 分钟', value: 30 },
  { label: '1 小时', value: 60 },
  { label: '6 小时', value: 360 },
  { label: '12 小时', value: 720 },
  { label: '1 天', value: 1440 },
];

const DEFAULT_ALERT_SYSTEM_PROMPT = '你是数字人监管平台的告警诊断助手，请输出简洁、直接、可执行的中文排查建议。';
const DEFAULT_LOG_SYSTEM_PROMPT = '你是数字人监管平台的日志分析助手，请结合日志上下文定位根因并输出优先级明确的处理建议。';

function normalizeSystemSettingsTab(value) {
  const allowed = new Set(SYSTEM_SETTINGS_TABS.map((item) => item.key));
  const normalized = String(Array.isArray(value) ? value[0] : value || '').trim();
  return allowed.has(normalized) ? normalized : 'jwt-account';
}

function formatDateTimeLabel(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '--';
}

function toDateTimeLocalValue(value) {
  if (!value) return '';
  const normalized = String(value).replace(' ', 'T');
  return normalized.length >= 16 ? normalized.slice(0, 16) : normalized;
}

function toDateTimePayload(value) {
  if (!value) return '';
  return `${String(value).replace('T', ' ')}:00`;
}

function syncTabQuery(tabKey) {
  if (typeof window === 'undefined' || !window.history?.replaceState) return;
  const nextUrl = new URL(window.location.href);
  if (tabKey === 'jwt-account') {
    nextUrl.searchParams.delete('tab');
  } else {
    nextUrl.searchParams.set('tab', tabKey);
  }
  window.history.replaceState({}, '', `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);
}

function authorizationStatusLabel(record) {
  if (record.authorizationStatus === 'PENDING') return '待授权';
  if (record.authorizationStatus === 'EXPIRED') return '已过期';
  if (record.authorizationStatus === 'DISABLED') return '已停用';
  if (record.authorizationStatus === 'AUTHORIZED') return '已授权';
  return record.enabled ? '已授权' : '已停用';
}

function authorizationStatusColor(record) {
  if (record.authorizationStatus === 'PENDING') return 'warning';
  if (record.authorizationStatus === 'EXPIRED') return 'error';
  if (record.authorizationStatus === 'DISABLED') return 'default';
  return record.enabled ? 'success' : 'default';
}

function emptyJwtDraft() {
  return {
    projectName: '',
    tenantName: '',
    tokenTtlMinutes: 30,
  };
}

function emptyAuthorizationDraft() {
  return {
    id: null,
    deviceId: '',
    displayName: '',
    region: '',
    mac: '',
    cpu: '',
    tenantName: '',
    registeredByJwtAccountUuid: '',
    registeredByJwtTenantName: '',
    rustdeskId: '',
    rustdeskPassword: '',
    authorizationStatus: '',
    enabled: true,
    createdAt: '',
    validFrom: '',
    validUntil: '',
  };
}

function buildAiDraft(config) {
  return {
    enabled: Boolean(config?.enabled),
    baseUrl: config?.baseUrl || '',
    apiKey: '',
    model: config?.model || '',
    temperature: Number(config?.temperature ?? 0.2),
    alertSystemPrompt: config?.alertSystemPrompt || DEFAULT_ALERT_SYSTEM_PROMPT,
    logSystemPrompt: config?.logSystemPrompt || DEFAULT_LOG_SYSTEM_PROMPT,
    connectTimeoutMs: Number(config?.connectTimeoutMs ?? 10000),
    readTimeoutMs: Number(config?.readTimeoutMs ?? 60000),
    apiKeyConfigured: Boolean(config?.apiKeyConfigured),
    apiKeyMasked: config?.apiKeyMasked || '',
  };
}

export default function DigitalHumanSystemSettingsPage() {
  const { message } = App.useApp();
  const initialTab = normalizeSystemSettingsTab(getBootstrapQuery().get('tab'));
  const [activeTab, setActiveTab] = useState(initialTab);

  const [authorizationFilters, setAuthorizationFilters] = useState({
    region: '',
    displayName: '',
    mac: '',
  });

  const jwtAccountsResource = useDigitalHumanResource(listDigitalHumanJwtAccounts, []);
  const authorizationsResource = useDigitalHumanResource(
    () => listDigitalHumanDeviceAuthorizations(authorizationFilters),
    [authorizationFilters.region, authorizationFilters.displayName, authorizationFilters.mac],
  );
  const aiConfigResource = useDigitalHumanResource(getDigitalHumanAiDiagnosisConfig, []);

  const {
    data: jwtAccountsData,
    loading: jwtAccountsLoading,
    error: jwtAccountsError,
    reload: reloadJwtAccounts,
  } = jwtAccountsResource;
  const {
    data: authorizationsData,
    loading: authorizationsLoading,
    error: authorizationsError,
    reload: reloadAuthorizations,
  } = authorizationsResource;
  const {
    data: aiConfigData,
    loading: aiConfigLoading,
    error: aiConfigError,
    reload: reloadAiConfig,
    setData: setAiConfigData,
  } = aiConfigResource;
  const [jwtDraft, setJwtDraft] = useState(emptyJwtDraft());
  const [jwtModalOpen, setJwtModalOpen] = useState(false);
  const [jwtSaving, setJwtSaving] = useState(false);
  const [jwtActionKey, setJwtActionKey] = useState('');
  const [jwtSecretReveal, setJwtSecretReveal] = useState(null);

  const [authorizationEditorOpen, setAuthorizationEditorOpen] = useState(false);
  const [authorizationEditorLoading, setAuthorizationEditorLoading] = useState(false);
  const [authorizationSaving, setAuthorizationSaving] = useState(false);
  const [authorizationActionId, setAuthorizationActionId] = useState('');
  const [authorizationDraft, setAuthorizationDraft] = useState(emptyAuthorizationDraft());

  const [aiDraft, setAiDraft] = useState(buildAiDraft(null));
  const [aiSaving, setAiSaving] = useState(false);
  const [aiTesting, setAiTesting] = useState(false);
  const [aiTestResult, setAiTestResult] = useState(null);

  const jwtAccounts = jwtAccountsData || [];
  const authorizations = authorizationsData || [];

  useEffect(() => {
    if (aiConfigData) {
      setAiDraft(buildAiDraft(aiConfigData));
    }
  }, [aiConfigData]);

  const authorizationRegionOptions = useMemo(
    () => Array.from(new Set(authorizations.map((item) => item.region).filter(Boolean)))
      .map((item) => ({ label: item, value: item })),
    [authorizations],
  );

  if (
    !jwtAccountsData
    && !authorizationsData
    && !aiConfigData
    && (jwtAccountsLoading || authorizationsLoading || aiConfigLoading)
  ) {
    return <SkeletonPage kpiCount={4} />;
  }

  const jwtEnabledCount = jwtAccounts.filter((item) => item.enabled).length;
  const authorizationEnabledCount = authorizations.filter((item) => item.enabled).length;
  const authorizationPendingCount = authorizations.filter((item) => item.authorizationStatus === 'PENDING').length;

  function refreshAll() {
    reloadJwtAccounts();
    reloadAuthorizations();
    reloadAiConfig();
  }

  function handleTabChange(nextTab) {
    setActiveTab(nextTab);
    syncTabQuery(nextTab);
  }

  async function handleCreateJwtAccount() {
    if (!jwtDraft.tenantName.trim()) {
      message.warning('请填写租户名');
      return;
    }

    setJwtSaving(true);
    try {
      const result = await createDigitalHumanJwtAccount(jwtDraft);
      setJwtSecretReveal(result?.secretReveal || null);
      setJwtModalOpen(false);
      setJwtDraft(emptyJwtDraft());
      await reloadJwtAccounts();
      message.success('JWT 账户已创建');
    } catch (error) {
      message.error(error.message || 'JWT 账户创建失败');
    } finally {
      setJwtSaving(false);
    }
  }

  async function handleRotateJwtSecret(account) {
    setJwtActionKey(`rotate:${account.accountUuid}`);
    try {
      const result = await rotateDigitalHumanJwtAccountSecret(account.accountUuid);
      setJwtSecretReveal({
        ...result,
        tenantName: account.tenantName,
      });
      await reloadJwtAccounts();
      message.success('JWT 密钥已重置');
    } catch (error) {
      message.error(error.message || 'JWT 密钥重置失败');
    } finally {
      setJwtActionKey('');
    }
  }

  async function handleToggleJwtStatus(account) {
    setJwtActionKey(`status:${account.accountUuid}`);
    try {
      await updateDigitalHumanJwtAccountStatus(account.accountUuid, !account.enabled);
      await reloadJwtAccounts();
      message.success(account.enabled ? 'JWT 账户已停用' : 'JWT 账户已启用');
    } catch (error) {
      message.error(error.message || 'JWT 账户状态更新失败');
    } finally {
      setJwtActionKey('');
    }
  }

  async function handleDeleteJwtAccount(account) {
    if (!window.confirm(`确认删除 JWT 账户「${account.tenantName}」吗？`)) {
      return;
    }

    setJwtActionKey(`delete:${account.accountUuid}`);
    try {
      await deleteDigitalHumanJwtAccount(account.accountUuid);
      await reloadJwtAccounts();
      message.success('JWT 账户已删除');
    } catch (error) {
      message.error(error.message || 'JWT 账户删除失败');
    } finally {
      setJwtActionKey('');
    }
  }

  async function openAuthorizationEditor(record) {
    setAuthorizationEditorOpen(true);
    setAuthorizationEditorLoading(true);
    try {
      const detail = await getDigitalHumanDeviceAuthorizationDetail(record.id);
      setAuthorizationDraft({
        ...detail,
        validFrom: toDateTimeLocalValue(detail.validFrom),
        validUntil: toDateTimeLocalValue(detail.validUntil),
      });
    } catch (error) {
      message.error(error.message || '设备授权详情加载失败');
      setAuthorizationEditorOpen(false);
    } finally {
      setAuthorizationEditorLoading(false);
    }
  }

  async function handleSaveAuthorization() {
    if (authorizationDraft.id == null) return;

    setAuthorizationSaving(true);
    try {
      await updateDigitalHumanDeviceAuthorization(authorizationDraft.id, {
        enabled: authorizationDraft.enabled,
        displayName: authorizationDraft.displayName,
        region: authorizationDraft.region,
        rustdeskId: authorizationDraft.rustdeskId,
        rustdeskPassword: authorizationDraft.rustdeskPassword,
        validFrom: toDateTimePayload(authorizationDraft.validFrom),
        validUntil: toDateTimePayload(authorizationDraft.validUntil),
      });
      setAuthorizationEditorOpen(false);
      setAuthorizationDraft(emptyAuthorizationDraft());
      await reloadAuthorizations();
      message.success('设备授权已保存');
    } catch (error) {
      message.error(error.message || '设备授权保存失败');
    } finally {
      setAuthorizationSaving(false);
    }
  }

  async function handleDeleteAuthorization(record) {
    if (!window.confirm(`确认删除设备授权「${record.displayName || record.deviceId}」吗？`)) {
      return;
    }

    setAuthorizationActionId(String(record.id));
    try {
      await deleteDigitalHumanDeviceAuthorization(record.id);
      await reloadAuthorizations();
      message.success('设备授权已删除');
    } catch (error) {
      message.error(error.message || '设备授权删除失败');
    } finally {
      setAuthorizationActionId('');
    }
  }

  async function handleSaveAiConfig() {
    setAiSaving(true);
    try {
      const nextConfig = await saveDigitalHumanAiDiagnosisConfig(aiDraft);
      setAiConfigData(nextConfig);
      setAiDraft(buildAiDraft(nextConfig));
      message.success('AI 诊断配置已保存');
    } catch (error) {
      message.error(error.message || 'AI 诊断配置保存失败');
    } finally {
      setAiSaving(false);
    }
  }

  async function handleTestAiConnection() {
    setAiTesting(true);
    try {
      const result = await testDigitalHumanAiDiagnosisConnection(aiDraft);
      setAiTestResult(result);
      message.success(result.success ? '连接测试成功' : '连接测试已返回失败结果');
    } catch (error) {
      setAiTestResult({
        success: false,
        message: error.message || '连接测试失败',
        reply: '',
      });
      message.error(error.message || '连接测试失败');
    } finally {
      setAiTesting(false);
    }
  }

  const jwtColumns = [
    {
      title: '租户信息',
      width: 240,
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{record.tenantName || '--'}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.projectName || '未命名项目'}</div>
        </div>
      ),
    },
    {
      title: '有效期',
      dataIndex: 'tokenTtlMinutes',
      width: 110,
      render: (value) => `${value || 0} 分钟`,
    },
    {
      title: '密钥掩码',
      dataIndex: 'secretMask',
      width: 180,
      render: (value) => <span className="beacon-dh-mono">{value || '--'}</span>,
    },
    {
      title: '最近签发',
      dataIndex: 'lastTokenIssuedAt',
      width: 160,
      render: (value) => formatDateTimeLabel(value),
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      width: 160,
      render: (value) => formatDateTimeLabel(value),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 100,
      render: (value) => <Tag color={value ? 'success' : 'default'}>{value ? '已启用' : '已停用'}</Tag>,
    },
    {
      title: '操作',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            loading={jwtActionKey === `rotate:${record.accountUuid}`}
            onClick={() => handleRotateJwtSecret(record)}
          >
            重置密钥
          </Button>
          <Button
            type="link"
            size="small"
            loading={jwtActionKey === `status:${record.accountUuid}`}
            onClick={() => handleToggleJwtStatus(record)}
          >
            {record.enabled ? '停用' : '启用'}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            loading={jwtActionKey === `delete:${record.accountUuid}`}
            onClick={() => handleDeleteJwtAccount(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  const authorizationColumns = [
    {
      title: '设备信息',
      width: 260,
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{record.displayName || '--'}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.deviceId || '--'} · {record.region || '--'}</div>
        </div>
      ),
    },
    {
      title: '注册信息',
      width: 220,
      render: (_, record) => (
        <div>
          <div>{record.tenantName || '--'}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.registeredByJwtTenantName || '--'}</div>
        </div>
      ),
    },
    {
      title: 'MAC',
      dataIndex: 'mac',
      width: 170,
      render: (value) => <span className="beacon-dh-mono">{value || '--'}</span>,
    },
    {
      title: '授权状态',
      width: 120,
      render: (_, record) => (
        <Tag color={authorizationStatusColor(record)}>{authorizationStatusLabel(record)}</Tag>
      ),
    },
    {
      title: '有效期',
      width: 210,
      render: (_, record) => (
        <div>
          <div>{formatDateTimeLabel(record.validFrom)}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>至 {formatDateTimeLabel(record.validUntil)}</div>
        </div>
      ),
    },
    {
      title: '操作',
      width: 150,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openAuthorizationEditor(record)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            danger
            loading={authorizationActionId === String(record.id)}
            onClick={() => handleDeleteAuthorization(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="beacon-dh-page">
      <PageHeader
        title="数字人系统设置"
        icon={<SettingOutlined />}
        description="独立于 Beacon 全局 /config/system 的管理员工作台，所有读写均直接落到 Beacon 本地数字人后端。"
        extra={(
          <Button icon={<ReloadOutlined />} onClick={refreshAll}>
            刷新
          </Button>
        )}
      />

      <KpiCardGroup>
        <KpiCard
          title="JWT 账户"
          value={jwtAccounts.length}
          suffix="个"
          color="#2563eb"
          icon={<SafetyCertificateOutlined />}
          metaItems={[
            { label: '启用中', value: jwtEnabledCount },
            { label: '已停用', value: Math.max(jwtAccounts.length - jwtEnabledCount, 0) },
          ]}
        />
        <KpiCard
          title="设备授权"
          value={authorizations.length}
          suffix="台"
          color="#0f766e"
          icon={<SettingOutlined />}
          metaItems={[
            { label: '已授权', value: authorizationEnabledCount },
            { label: '待授权', value: authorizationPendingCount },
          ]}
        />
        <KpiCard
          title="AI 诊断"
          value={aiDraft.enabled ? '已启用' : '未启用'}
          color="#7c3aed"
          icon={<RobotOutlined />}
          metaItems={[
            { label: '模型', value: aiDraft.model || '--' },
            { label: '密钥', value: aiDraft.apiKeyConfigured ? '已配置' : '未配置' },
          ]}
        />
      </KpiCardGroup>

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          {
            key: 'jwt-account',
            label: 'JWT 账户管理',
            children: (
              <>
                {jwtAccountsError ? (
                  <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={jwtAccountsError.message || 'JWT 账户加载失败'} />
                ) : null}

                {jwtSecretReveal ? (
                  <Card className="beacon-panel-card beacon-panel-card--tone-green" size="small" style={{ marginBottom: 16 }}>
                    <div className="beacon-dh-secret-panel">
                      <div>
                        <div className="beacon-dh-secret-panel__title">一次性密钥已生成</div>
                        <div className="beacon-dh-secret-panel__desc">
                          明文密钥只展示一次，请立即交给采集端或妥善保存；丢失后只能再次重置。
                        </div>
                      </div>
                      <Button size="small" onClick={() => setJwtSecretReveal(null)}>关闭</Button>
                    </div>
                    <Descriptions bordered size="small" column={1} style={{ marginTop: 16 }}>
                      <Descriptions.Item label="租户名">{jwtSecretReveal.tenantName || '--'}</Descriptions.Item>
                      <Descriptions.Item label="密钥掩码">
                        <span className="beacon-dh-mono">{jwtSecretReveal.secretMask || '--'}</span>
                      </Descriptions.Item>
                      <Descriptions.Item label="明文密钥">
                        <span className="beacon-dh-mono">{jwtSecretReveal.secret || '--'}</span>
                      </Descriptions.Item>
                    </Descriptions>
                  </Card>
                ) : null}

                <Card
                  className="beacon-panel-card beacon-panel-card--tone-blue"
                  size="small"
                  title="JWT 账户列表"
                  extra={(
                    <Button type="primary" onClick={() => setJwtModalOpen(true)}>
                      新增账户
                    </Button>
                  )}
                >
                  <ProTable
                    rowKey="accountUuid"
                    columns={jwtColumns}
                    dataSource={jwtAccounts}
                    loading={jwtAccountsLoading}
                    pagination={{ pageSize: 10 }}
                  />
                </Card>
              </>
            ),
          },
          {
            key: 'authorization',
            label: '设备授权管理',
            children: (
              <>
                {authorizationsError ? (
                  <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={authorizationsError.message || '设备授权列表加载失败'} />
                ) : null}

                <FilterBar
                  filters={[
                    { key: 'region', label: '设备分组', type: 'select', options: authorizationRegionOptions },
                    { key: 'displayName', label: '设备名', placeholder: '输入设备名' },
                    { key: 'mac', label: 'MAC', placeholder: '输入 MAC' },
                  ]}
                  initialValues={authorizationFilters}
                  onSearch={(values) => setAuthorizationFilters({
                    region: values.region || '',
                    displayName: values.displayName || '',
                    mac: values.mac || '',
                  })}
                  onReset={() => setAuthorizationFilters({ region: '', displayName: '', mac: '' })}
                />

                <Card className="beacon-panel-card beacon-panel-card--tone-cyan" size="small" title="授权设备列表">
                  <ProTable
                    rowKey="id"
                    columns={authorizationColumns}
                    dataSource={authorizations}
                    loading={authorizationsLoading}
                    pagination={{ pageSize: 10 }}
                  />
                </Card>
              </>
            ),
          },
          {
            key: 'llm',
            label: '大模型配置',
            children: (
              <>
                {aiConfigError ? (
                  <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={aiConfigError.message || 'AI 诊断配置加载失败'} />
                ) : null}

                <div className="beacon-dh-grid beacon-dh-grid--two">
                  <Card
                    className="beacon-panel-card beacon-panel-card--tone-purple"
                    size="small"
                    title="AI 诊断配置"
                    extra={(
                      <Space>
                        <Button loading={aiTesting} onClick={handleTestAiConnection}>测试连接</Button>
                        <Button type="primary" loading={aiSaving} onClick={handleSaveAiConfig}>保存配置</Button>
                      </Space>
                    )}
                  >
                    <div className="beacon-dh-form-grid">
                      <div className="beacon-dh-form-grid__span-2 beacon-dh-form-row beacon-dh-form-row--switch">
                        <div className="beacon-dh-form-row__label">AI 诊断</div>
                        <Switch checked={aiDraft.enabled} onChange={(checked) => setAiDraft((prev) => ({ ...prev, enabled: checked }))} />
                      </div>
                      <div className="beacon-dh-form-row">
                        <div className="beacon-dh-form-row__label">Base URL</div>
                        <Input
                          data-testid="digital-human-ai-base-url"
                          value={aiDraft.baseUrl}
                          onChange={(event) => setAiDraft((prev) => ({ ...prev, baseUrl: event.target.value }))}
                          placeholder="https://your-openai-compatible-host"
                        />
                      </div>
                      <div className="beacon-dh-form-row">
                        <div className="beacon-dh-form-row__label">Model</div>
                        <Input
                          value={aiDraft.model}
                          onChange={(event) => setAiDraft((prev) => ({ ...prev, model: event.target.value }))}
                          placeholder="gpt-4.1-mini"
                        />
                      </div>
                      <div className="beacon-dh-form-grid__span-2 beacon-dh-form-row">
                        <div className="beacon-dh-form-row__label">API Key</div>
                        <Input.Password
                          value={aiDraft.apiKey}
                          onChange={(event) => setAiDraft((prev) => ({ ...prev, apiKey: event.target.value }))}
                          placeholder="留空表示保留当前已配置密钥"
                        />
                        <div className="beacon-dh-form-help">
                          当前状态：{aiDraft.apiKeyConfigured ? `已配置 ${aiDraft.apiKeyMasked || ''}` : '未配置'}
                        </div>
                      </div>
                      <div className="beacon-dh-form-row">
                        <div className="beacon-dh-form-row__label">Temperature</div>
                        <InputNumber
                          min={0}
                          max={2}
                          step={0.1}
                          style={{ width: '100%' }}
                          value={aiDraft.temperature}
                          onChange={(value) => setAiDraft((prev) => ({ ...prev, temperature: Number(value ?? 0.2) }))}
                        />
                      </div>
                      <div className="beacon-dh-form-row">
                        <div className="beacon-dh-form-row__label">连接 / 读取超时 (ms)</div>
                        <Space.Compact style={{ width: '100%' }}>
                          <InputNumber
                            min={1000}
                            step={500}
                            style={{ width: '50%' }}
                            value={aiDraft.connectTimeoutMs}
                            onChange={(value) => setAiDraft((prev) => ({ ...prev, connectTimeoutMs: Number(value ?? 10000) }))}
                          />
                          <InputNumber
                            min={1000}
                            step={500}
                            style={{ width: '50%' }}
                            value={aiDraft.readTimeoutMs}
                            onChange={(value) => setAiDraft((prev) => ({ ...prev, readTimeoutMs: Number(value ?? 60000) }))}
                          />
                        </Space.Compact>
                      </div>
                      <div className="beacon-dh-form-grid__span-2 beacon-dh-form-row">
                        <div className="beacon-dh-form-row__label">告警诊断提示词</div>
                        <Input.TextArea
                          rows={6}
                          value={aiDraft.alertSystemPrompt}
                          onChange={(event) => setAiDraft((prev) => ({ ...prev, alertSystemPrompt: event.target.value }))}
                        />
                        <Button size="small" onClick={() => setAiDraft((prev) => ({ ...prev, alertSystemPrompt: DEFAULT_ALERT_SYSTEM_PROMPT }))}>
                          恢复默认提示词
                        </Button>
                      </div>
                      <div className="beacon-dh-form-grid__span-2 beacon-dh-form-row">
                        <div className="beacon-dh-form-row__label">日志分析提示词</div>
                        <Input.TextArea
                          rows={6}
                          value={aiDraft.logSystemPrompt}
                          onChange={(event) => setAiDraft((prev) => ({ ...prev, logSystemPrompt: event.target.value }))}
                        />
                        <Button size="small" onClick={() => setAiDraft((prev) => ({ ...prev, logSystemPrompt: DEFAULT_LOG_SYSTEM_PROMPT }))}>
                          恢复默认提示词
                        </Button>
                      </div>
                    </div>
                  </Card>

                  <Card className="beacon-panel-card beacon-panel-card--tone-orange" size="small" title="连接测试结果">
                    {aiTestResult ? (
                      <Alert
                        type={aiTestResult.success ? 'success' : 'error'}
                        showIcon
                        message={aiTestResult.message || '连接测试已完成'}
                        description={aiTestResult.reply || '当前没有返回更多上下文。'}
                      />
                    ) : (
                      <div className="beacon-dh-detail-note">
                        点击“测试连接”后，在此展示模型连通性与返回摘要。
                      </div>
                    )}
                  </Card>
                </div>
              </>
            ),
          },
        ]}
      />

      <Modal
        title="新增 JWT 账户"
        open={jwtModalOpen}
        onCancel={() => {
          if (jwtSaving) return;
          setJwtModalOpen(false);
          setJwtDraft(emptyJwtDraft());
        }}
        onOk={handleCreateJwtAccount}
        okText="创建账户并生成密钥"
        confirmLoading={jwtSaving}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Input
            placeholder="项目名称（可选）"
            value={jwtDraft.projectName}
            onChange={(event) => setJwtDraft((prev) => ({ ...prev, projectName: event.target.value }))}
          />
          <Input
            data-testid="digital-human-jwt-tenant-name"
            placeholder="租户名"
            value={jwtDraft.tenantName}
            onChange={(event) => setJwtDraft((prev) => ({ ...prev, tenantName: event.target.value }))}
          />
          <Select
            value={jwtDraft.tokenTtlMinutes}
            options={JWT_TTL_OPTIONS}
            onChange={(value) => setJwtDraft((prev) => ({ ...prev, tokenTtlMinutes: value }))}
          />
        </Space>
      </Modal>

      <Modal
        title="编辑设备授权"
        open={authorizationEditorOpen}
        onCancel={() => {
          if (authorizationSaving) return;
          setAuthorizationEditorOpen(false);
          setAuthorizationDraft(emptyAuthorizationDraft());
        }}
        onOk={handleSaveAuthorization}
        okText="保存授权"
        confirmLoading={authorizationSaving}
        width={720}
        destroyOnHidden
      >
        {authorizationEditorLoading ? (
          <SkeletonPage kpiCount={2} />
        ) : (
          <div className="beacon-dh-form-grid">
            <div className="beacon-dh-form-grid__span-2 beacon-dh-form-row">
              <div className="beacon-dh-form-row__label">授权开关</div>
              <Switch
                checked={authorizationDraft.enabled}
                onChange={(checked) => setAuthorizationDraft((prev) => ({ ...prev, enabled: checked }))}
              />
            </div>
            <div className="beacon-dh-form-row">
              <div className="beacon-dh-form-row__label">设备名</div>
              <Input
                value={authorizationDraft.displayName}
                onChange={(event) => setAuthorizationDraft((prev) => ({ ...prev, displayName: event.target.value }))}
              />
            </div>
            <div className="beacon-dh-form-row">
              <div className="beacon-dh-form-row__label">设备分组</div>
              <Input
                value={authorizationDraft.region}
                onChange={(event) => setAuthorizationDraft((prev) => ({ ...prev, region: event.target.value }))}
              />
            </div>
            <div className="beacon-dh-form-row">
              <div className="beacon-dh-form-row__label">RustDesk ID</div>
              <Input
                value={authorizationDraft.rustdeskId}
                onChange={(event) => setAuthorizationDraft((prev) => ({ ...prev, rustdeskId: event.target.value }))}
              />
            </div>
            <div className="beacon-dh-form-row">
              <div className="beacon-dh-form-row__label">RustDesk 密码</div>
              <Input
                value={authorizationDraft.rustdeskPassword}
                onChange={(event) => setAuthorizationDraft((prev) => ({ ...prev, rustdeskPassword: event.target.value }))}
              />
            </div>
            <div className="beacon-dh-form-row">
              <div className="beacon-dh-form-row__label">有效期开始</div>
              <Input
                type="datetime-local"
                value={authorizationDraft.validFrom}
                onChange={(event) => setAuthorizationDraft((prev) => ({ ...prev, validFrom: event.target.value }))}
              />
            </div>
            <div className="beacon-dh-form-row">
              <div className="beacon-dh-form-row__label">有效期结束</div>
              <Input
                type="datetime-local"
                value={authorizationDraft.validUntil}
                onChange={(event) => setAuthorizationDraft((prev) => ({ ...prev, validUntil: event.target.value }))}
              />
            </div>
            <div className="beacon-dh-form-grid__span-2">
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="Device ID">{authorizationDraft.deviceId || '--'}</Descriptions.Item>
                <Descriptions.Item label="MAC">
                  <span className="beacon-dh-mono">{authorizationDraft.mac || '--'}</span>
                </Descriptions.Item>
                <Descriptions.Item label="租户名">{authorizationDraft.tenantName || '--'}</Descriptions.Item>
                <Descriptions.Item label="JWT 账户 UUID">
                  <span className="beacon-dh-mono">{authorizationDraft.registeredByJwtAccountUuid || '--'}</span>
                </Descriptions.Item>
              </Descriptions>
            </div>
          </div>
        )}
      </Modal>

    </div>
  );
}

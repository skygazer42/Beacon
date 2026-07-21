import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Card, Checkbox, Form, Input, InputNumber, Modal, Progress, Space, Statistic, Tag, Typography } from 'antd';
import {
  KeyOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';
import { formatTime } from '../../utils/format';

const { Paragraph, Text } = Typography;

const CREATE_DEFAULTS = {
  scopes: ['ops'],
  expires_days: 30,
  rate_limit_per_minute: 60,
  burst_limit: 10,
};

function resolveKnownScopes(data) {
  if (Array.isArray(data?.known_scopes) && data.known_scopes.length) {
    return data.known_scopes;
  }
  return ['ops', 'openapi'];
}

function resolveCreateDefaults(data, knownScopes) {
  let defaultScopes = [];
  if (knownScopes.length) {
    defaultScopes = [knownScopes[0]];
  }
  if (knownScopes.includes('ops')) {
    defaultScopes = ['ops'];
  }

  return {
    ...CREATE_DEFAULTS,
    ...data?.create_defaults,
    scopes: defaultScopes,
  };
}

function filterApiKeyRows(rows, filters) {
  const keyword = String(filters?.keyword || '').trim().toLowerCase();
  const enabled = String(filters?.enabled || '').trim().toLowerCase();
  const scope = String(filters?.scope || '').trim();

  return (Array.isArray(rows) ? rows : []).filter((row) => {
    if (keyword) {
      const haystack = [
        row?.name,
        row?.token_prefix,
        ...(Array.isArray(row?.scopes) ? row.scopes : []),
        row?.created_by,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(keyword)) {
        return false;
      }
    }

    if (enabled === '1' && !row?.enabled) {
      return false;
    }
    if (enabled === '0' && row?.enabled) {
      return false;
    }
    if (scope && !(Array.isArray(row?.scopes) && row.scopes.includes(scope))) {
      return false;
    }
    return true;
  });
}

export default function ApiKeysPage() {
  const { message, modal } = App.useApp();
  const [filters, setFilters] = useState({ keyword: '', enabled: '', scope: '' });
  const [createOpen, setCreateOpen] = useState(false);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createResult, setCreateResult] = useState(null);
  const [createForm] = Form.useForm();
  const [rawRows, setRawRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { data: metadata } = useApi(API.apikeys, {});

  const loadRows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiPost(API.opsApiKeyList, {});
      const nextRows = Array.isArray(result) ? result : [];
      setRawRows(nextRows);
      return nextRows;
    } catch (err) {
      setError(err);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRows();
  }, [loadRows]);

  const rows = useMemo(() => filterApiKeyRows(rawRows, filters), [filters, rawRows]);
  const stats = useMemo(
    () => ({
      total: rows.length,
      enabled_total: rows.filter(row => row.enabled).length,
      revoked_total: rows.filter(row => !row.enabled).length,
    }),
    [rows],
  );
  const knownScopes = resolveKnownScopes(metadata);
  const createDefaults = resolveCreateDefaults(metadata, knownScopes);
  const canManage = metadata?.can_manage !== false;
  const enabledPercent = stats.total ? Math.round((stats.enabled_total / stats.total) * 100) : 0;
  const revokedPercent = stats.total ? Math.round((stats.revoked_total / stats.total) * 100) : 0;
  const policyItems = useMemo(
    () => [
      { key: 'scopes', label: '默认范围', value: createDefaults.scopes?.join(', ') || '-' },
      { key: 'expires_days', label: '有效天数', value: `${createDefaults.expires_days ?? '-'} 天` },
      {
        key: 'limits',
        label: '限流策略',
        value: `${createDefaults.rate_limit_per_minute ?? '-'} / ${createDefaults.burst_limit ?? '-'}`,
      },
      { key: 'manage', label: '管理能力', value: canManage ? <Tag color="success">可创建 / 轮换 / 吊销</Tag> : <Tag>只读</Tag> },
    ],
    [canManage, createDefaults],
  );

  const openCreate = useCallback(() => {
    createForm.setFieldsValue(createDefaults);
    setCreateResult(null);
    setCreateOpen(true);
  }, [createDefaults, createForm]);

  const submitCreate = useCallback(async () => {
    setCreateSubmitting(true);
    try {
      const values = await createForm.validateFields();
      const result = await apiPost(API.opsApiKeyCreate, {
        name: values.name,
        scopes: JSON.stringify(values.scopes || ['ops']),
        expires_days: values.expires_days,
        rate_limit_per_minute: values.rate_limit_per_minute,
        burst_limit: values.burst_limit,
      });
      setCreateResult(result || null);
      message.success('密钥已创建');
      await loadRows();
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '创建失败');
    } finally {
      setCreateSubmitting(false);
    }
  }, [createForm, loadRows, message]);

  const handleRevoke = useCallback(
    async (id) => {
      modal.confirm({
        title: '确认吊销该密钥？',
        onOk: async () => {
          try {
            const form = new FormData();
            form.append('id', String(id));
            await apiPost(API.opsApiKeyRevoke, form);
            message.success('已吊销');
            await loadRows();
          } catch (e) {
            message.error(e.message || '吊销失败');
            throw e;
          }
        },
      });
    },
    [loadRows, message, modal],
  );

  const handleRotate = useCallback(
    async (id) => {
      modal.confirm({
        title: '确认轮换密钥？',
        content: '旧令牌将立即失效，新令牌仅显示一次。',
        onOk: async () => {
          try {
            const form = new FormData();
            form.append('id', String(id));
            const result = await apiPost(API.opsApiKeyRotate, form);
            const token = result?.token;
            if (token) {
              Modal.success({
                title: '新令牌（请妥善保存）',
                width: 560,
                content: (
                  <Paragraph copyable={{ text: token }} style={{ wordBreak: 'break-all', marginBottom: 0 }}>
                    {token}
                  </Paragraph>
                ),
              });
            }
            message.success('已轮换');
            await loadRows();
          } catch (e) {
            message.error(e.message || '轮换失败');
            throw e;
          }
        },
      });
    },
    [loadRows, message, modal],
  );

  const columns = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '前缀', dataIndex: 'token_prefix', width: 140, ellipsis: true },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v) => (v ? <Tag color="success">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '权限范围',
      dataIndex: 'scopes',
      ellipsis: true,
      render: (scopes) => (Array.isArray(scopes) && scopes.length ? scopes.join(', ') : '-'),
    },
    {
      title: '限流/突发',
      key: 'limits',
      width: 110,
      render: (_, r) => `${Number(r.rate_limit_per_minute || 0)} / ${Number(r.burst_limit || 0)}`,
    },
    { title: '创建人', dataIndex: 'created_by', width: 120, ellipsis: true, render: (v) => v || '-' },
    { title: '创建时间', dataIndex: 'create_time', width: 170, render: (v) => formatTime(v) },
    { title: '过期时间', dataIndex: 'expires_at', width: 170, render: (v) => formatTime(v) },
    { title: '最后使用', dataIndex: 'last_used_at', width: 170, render: (v) => formatTime(v) },
    { title: '吊销时间', dataIndex: 'revoked_at', width: 170, render: (v) => formatTime(v) },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" danger icon={<StopOutlined />} onClick={() => handleRevoke(r.id)} disabled={!r.enabled || !canManage}>
            吊销
          </Button>
          <Button type="link" size="small" icon={<SyncOutlined />} onClick={() => handleRotate(r.id)} disabled={!canManage}>
            轮换
          </Button>
        </Space>
      ),
    },
  ];

  const filterDefs = useMemo(
    () => [
      { key: 'keyword', label: '关键词', type: 'input', placeholder: '名称/前缀/创建人' },
      {
        key: 'enabled',
        label: '状态',
        type: 'select',
        options: [
          { value: '', label: '全部状态' },
          { value: '1', label: '启用' },
          { value: '0', label: '停用' },
        ],
      },
      {
        key: 'scope',
        label: '权限范围',
        type: 'select',
        options: [{ value: '', label: '全部范围' }, ...knownScopes.map((item) => ({ value: item, label: item }))],
      },
    ],
    [knownScopes],
  );

  return (
    <div>
      <PageHeader
        title="API 密钥"
        icon={<KeyOutlined />}
        description="API 密钥管理"
        extra={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => loadRows()}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!canManage}>
              新建密钥
            </Button>
          </Space>
        )}
      />

      {error ? <Alert type="error" showIcon style={{ marginBottom: 12 }} message={error.message || '加载失败'} /> : null}

      <div className="beacon-support-grid beacon-equal-height-grid" data-layout="full-width" style={{ marginBottom: 16 }}>
        <SummaryCard title="签发策略" meta="后端默认创建参数" icon={<SafetyCertificateOutlined />} tone="blue" items={policyItems}>
          <div className="beacon-summary-card__extra">
            <Text type="secondary" style={{ fontSize: 12 }}>
              可用 scope
            </Text>
            <Space wrap size={[6, 6]}>
              {knownScopes.map((scope) => (
                <Tag key={scope} color={filters.scope === scope ? 'processing' : undefined}>
                  {scope}
                </Tag>
              ))}
            </Space>
          </div>
        </SummaryCard>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-slate beacon-stat-panel"
          title={<PanelTitle title="总密钥" meta="当前列表返回" icon={<KeyOutlined />} tone="slate" />}
          size="small"
        >
          <Statistic value={stats.total} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            支持按关键词、状态和 scope 过滤
          </Text>
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-green beacon-stat-panel"
          title={<PanelTitle title="已启用" meta="可用密钥占比" icon={<SyncOutlined />} tone="green" />}
          size="small"
        >
          <Statistic value={stats.enabled_total} />
          <Progress percent={enabledPercent} size="small" status={enabledPercent >= 80 ? 'success' : 'active'} />
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-orange beacon-stat-panel"
          title={<PanelTitle title="已吊销" meta="停用 / 轮换后失效" icon={<StopOutlined />} tone="orange" />}
          size="small"
        >
          <Statistic value={stats.revoked_total} />
          <Progress percent={revokedPercent} size="small" status={stats.revoked_total ? 'exception' : 'normal'} />
        </Card>
      </div>

      <FilterBar
        filters={filterDefs}
        onSearch={(values) => setFilters({
          keyword: values.keyword || '',
          enabled: values.enabled || '',
          scope: values.scope || '',
        })}
        onReset={() => setFilters({ keyword: '', enabled: '', scope: '' })}
      />

      <Card
        className="beacon-panel-card beacon-panel-card--tone-slate"
        title={<PanelTitle title="密钥列表" meta="直连列表接口与后台元数据" icon={<KeyOutlined />} tone="slate" />}
        size="small"
        styles={{ body: { padding: 0 } }}
      >
        <ProTable columns={columns} dataSource={rows} loading={loading} rowKey="id" pagination={{ pageSize: 20 }} />
      </Card>

      <Modal
        title="新建 API 密钥"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={submitCreate}
        okText="创建"
        okButtonProps={{ loading: createSubmitting }}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" initialValues={createDefaults}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="scopes" label="权限范围" rules={[{ required: true, message: '请选择至少一个 scope' }]}>
            <Checkbox.Group options={knownScopes.map((item) => ({ label: item, value: item }))} />
          </Form.Item>
          <Form.Item name="expires_days" label="有效天数">
            <InputNumber min={1} max={3650} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="rate_limit_per_minute" label="每分钟限流">
            <InputNumber min={0} max={100000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="burst_limit" label="突发上限">
            <InputNumber min={0} max={100000} style={{ width: '100%' }} />
          </Form.Item>
        </Form>

        {createResult ? (
          <Alert
            style={{ marginTop: 8 }}
            type="success"
            showIcon
            message="新密钥已生成"
            description={(
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <Text type="secondary">该令牌只会返回一次，请立即保存。</Text>
                <Paragraph copyable={{ text: createResult.token }} style={{ wordBreak: 'break-all', marginBottom: 0 }}>
                  {createResult.token}
                </Paragraph>
              </Space>
            )}
          />
        ) : null}
      </Modal>
    </div>
  );
}

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  ArrowRightOutlined,
  CloudOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';
import { formatTime } from '../../utils/format';

const { Paragraph, Text } = Typography;

const STATUS_TEXT = {
  fresh: '心跳正常',
  ok: '正常',
  stale: '心跳陈旧',
  never: '尚未心跳',
};

function ClusterCard({
  record,
  manageAllowed,
  onToggle,
  onRotate,
  onEditRemote,
}) {
  const heartbeatTone = ['ok', 'fresh'].includes(record.heartbeat_state)
    ? 'success'
    : record.heartbeat_state === 'stale'
      ? 'warning'
      : 'default';
  const remoteTone = record.remote_status === 'ok'
    ? 'success'
    : record.remote_error
      ? 'error'
      : 'processing';

  return (
    <Card
      size="small"
      title={(
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontWeight: 600 }}>{record.name || '-'}</div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.node_code || '未配置节点编号'}
            </Text>
          </div>
          <Space size={[6, 6]} wrap>
            <Tag color={record.enabled ? 'success' : 'default'}>{record.enabled ? '启用' : '禁用'}</Tag>
            <Tag color={heartbeatTone}>{STATUS_TEXT[record.heartbeat_state] || '状态未知'}</Tag>
            <Tag color={record.remote_configured ? 'processing' : 'default'}>
              {record.remote_configured ? '远控已配置' : '未配置远控'}
            </Tag>
          </Space>
        </div>
      )}
      extra={(
        <Space size={6} wrap>
          {manageAllowed ? (
            <>
              <Button size="small" onClick={() => onEditRemote(record)}>
                远控配置
              </Button>
              <Button size="small" onClick={() => onRotate(record)}>
                轮换 Token
              </Button>
              <Button size="small" danger={record.enabled} onClick={() => onToggle(record)}>
                {record.enabled ? '禁用' : '启用'}
              </Button>
            </>
          ) : null}
        </Space>
      )}
      styles={{ body: { display: 'grid', gap: 12 } }}
    >
      <div style={{ display: 'grid', gap: 8 }}>
        <Text ellipsis={{ tooltip: record.edge_admin_base_url || '-' }}>
          <Text type="secondary">Edge：</Text>
          {record.edge_admin_base_url || '-'}
        </Text>
        <Text>
          <Text type="secondary">版本：</Text>
          <strong>{record.version || '-'}</strong>
        </Text>
        <Text>
          <Text type="secondary">最近心跳：</Text>
          {record.heartbeat_age_text || formatTime(record.last_seen_at) || '-'}
        </Text>
        <Text>
          <Text type="secondary">远控状态：</Text>
          <Tag color={remoteTone} style={{ marginInlineStart: 8 }}>
            {record.remote_error ? '探测失败' : (record.remote_status || 'unknown')}
          </Tag>
        </Text>
      </div>

      {record.remote_configured ? (
        <Space size={6} wrap>
          <Button size="small" href={`/cloud/remote/streams?cluster_id=${encodeURIComponent(record.id)}`}>
            视频资源
          </Button>
          <Button size="small" href={`/cloud/remote/recordings?cluster_id=${encodeURIComponent(record.id)}`}>
            录像
          </Button>
          <Button size="small" href={`/cloud/remote/platform?cluster_id=${encodeURIComponent(record.id)}`}>
            运行状态
          </Button>
        </Space>
      ) : null}

      {record.has_rollout ? (
        <div
          style={{
            display: 'grid',
            gap: 8,
            padding: 12,
            border: '1px solid var(--beacon-border-soft)',
            borderRadius: 8,
            background: 'var(--beacon-surface-muted)',
          }}
        >
          <Space wrap size={[8, 8]}>
            <Tag color={record.rollout_status_tone || 'default'}>
              {record.rollout_status_label || '升级推进'}
            </Tag>
            {record.rollout_channel ? <Tag>{record.rollout_channel}</Tag> : null}
            {record.rollout_target_version ? <Tag color="blue">{record.rollout_target_version}</Tag> : null}
          </Space>
          {record.rollout_error ? (
            <Text type="danger">{record.rollout_error}</Text>
          ) : null}
          {Array.isArray(record.rollout_node_versions) && record.rollout_node_versions.length > 0 ? (
            <div style={{ display: 'grid', gap: 6 }}>
              {record.rollout_node_versions.slice(0, 3).map((item, idx) => (
                <div
                  key={`${record.id}-version-${idx}`}
                  style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}
                >
                  <Text type="secondary">{item.node_code || '-'}</Text>
                  <Text>{item.version || '-'}</Text>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {record.issues?.length ? (
        <Space wrap size={[6, 6]}>
          {record.issues.map((issue) => (
            <Tag key={`${record.id}-${issue}`} color="error">
              {issue}
            </Tag>
          ))}
        </Space>
      ) : (
        <Text type="secondary">当前未发现明显异常。</Text>
      )}
    </Card>
  );
}

const EDGE_CONNECTION_STATUS = {
  connected: { color: 'success', label: '服务可达' },
  unreachable: { color: 'error', label: '连接失败' },
  incomplete: { color: 'warning', label: '待补充配置' },
  disabled: { color: 'default', label: '未启用' },
};

function EdgeCloudConnection({ connection, loading, error, run }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const status = EDGE_CONNECTION_STATUS[connection?.status] || EDGE_CONNECTION_STATUS.disabled;

  useEffect(() => {
    form.setFieldsValue({
      cloudBaseUrl: connection?.base_url || '',
      cloudEdgeToken: '',
    });
  }, [connection?.base_url, form]);

  const saveConnection = async () => {
    try {
      const values = await form.validateFields();
      const token = String(values.cloudEdgeToken || '').trim();
      const payload = {
        cloudEnabled: true,
        cloudBaseUrl: String(values.cloudBaseUrl || '').trim(),
      };
      if (token) payload.cloudEdgeToken = token;

      setSaving(true);
      await apiPost(API.configSystemSave, payload);
      message.success('云平台连接已保存');
      form.setFieldValue('cloudEdgeToken', '');
      await run();
    } catch (e) {
      if (!e?.errorFields) message.error(e?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const disableConnection = async () => {
    setSaving(true);
    try {
      await apiPost(API.configSystemSave, { cloudEnabled: false });
      message.success('云平台连接已停用');
      await run();
    } catch (e) {
      message.error(e?.message || '停用失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="云平台接入"
        icon={<CloudOutlined />}
        description="将当前 Edge 节点连接到 Beacon Cloud，告警与截图会通过现有云协议上报。"
        extra={<Button icon={<ReloadOutlined />} onClick={() => run()}>重新检测</Button>}
      />

      {error ? <Alert type="error" showIcon message={error.message || '连接信息加载失败'} style={{ marginBottom: 16 }} /> : null}

      <Spin spinning={loading}>
        <Row gutter={[16, 16]} align="stretch">
          <Col xs={24} lg={13}>
            <Card title="接入路径" style={{ height: '100%' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: 10,
                  padding: 16,
                  marginBottom: 20,
                  border: '1px solid var(--beacon-border-soft)',
                  borderRadius: 'var(--beacon-radius-md)',
                  background: 'var(--beacon-surface-muted)',
                }}
              >
                <Tag color="blue">当前 Edge</Tag>
                <ArrowRightOutlined style={{ color: 'var(--beacon-text-faint)' }} />
                <Tag color={status.color}>Beacon Cloud · {status.label}</Tag>
                {connection?.version ? <Text type="secondary">v{connection.version}</Text> : null}
              </div>

              <Space direction="vertical" size={14} style={{ width: '100%' }}>
                <div>
                  <Text strong>1. 在 Cloud 创建边缘节点</Text>
                  <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
                    Cloud 会生成一次性 Edge Token，用于识别当前节点。
                  </Paragraph>
                </div>
                <div>
                  <Text strong>2. 在右侧填写地址与 Token</Text>
                  <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
                    云平台地址填写 Cloud 登录地址，例如 http://cloud.example.com:9991。
                  </Paragraph>
                </div>
                <div>
                  <Text strong>3. 用真实告警确认接入</Text>
                  <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
                    保存后，新告警会进入云端告警列表；这里不生成演示数据。
                  </Paragraph>
                </div>
              </Space>

              <Alert
                type="info"
                showIcon
                style={{ marginTop: 20 }}
                message="当前支持 Beacon Cloud 告警接入协议；其他厂商需要兼容该协议。"
              />
            </Card>
          </Col>

          <Col xs={24} lg={11}>
            <Card
              title="连接配置"
              extra={<Tag color={status.color}>{status.label}</Tag>}
              style={{ height: '100%' }}
            >
              <Form form={form} layout="vertical" requiredMark={false}>
                <Form.Item
                  name="cloudBaseUrl"
                  label="Beacon Cloud 地址"
                  rules={[
                    { required: true, message: '请输入 Beacon Cloud 地址' },
                    { type: 'url', message: '请输入完整的 http:// 或 https:// 地址' },
                  ]}
                >
                  <Input prefix={<LinkOutlined />} placeholder="http://cloud.example.com:9991" />
                </Form.Item>
                <Form.Item
                  name="cloudEdgeToken"
                  label="Edge Token"
                  extra={connection?.token_configured ? '已保存 Token；留空表示保持不变。' : '从 Cloud 的边缘节点页面创建并复制。'}
                  rules={[{ required: !connection?.token_configured, message: '请输入 Edge Token' }]}
                >
                  <Input.Password autoComplete="new-password" placeholder={connection?.token_configured ? '已配置' : '粘贴一次性 Edge Token'} />
                </Form.Item>

                <Space wrap>
                  <Button type="primary" loading={saving} onClick={saveConnection}>
                    保存并检测
                  </Button>
                  {connection?.enabled ? (
                    <Button loading={saving} onClick={disableConnection}>停用连接</Button>
                  ) : null}
                </Space>
              </Form>

              <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--beacon-border-muted)' }}>
                <Text type="secondary">检测结果</Text>
                <Paragraph style={{ margin: '6px 0 0' }}>
                  {connection?.message || '尚未检测'}
                </Paragraph>
                {connection?.base_url ? (
                  <Text type="secondary" copyable={{ text: connection.base_url }}>
                    {connection.base_url}
                  </Text>
                ) : null}
              </div>
            </Card>
          </Col>
        </Row>
      </Spin>
    </div>
  );
}

export default function CloudEdgeClustersPage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.cloudEdgeClusters);

  const rows = data?.rows || [];
  const summary = data?.summary || {};
  const topUnhealthy = data?.top_unhealthy || [];
  const rolloutRows = data?.rollout_rows || [];
  const accessOk = data?.access_ok !== false;
  const manageAllowed = Boolean(data?.manage_allowed);
  const tenantOptions = data?.tenant_options || [];
  const edgeConnection = data?.edge_connection || {};

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [remoteCluster, setRemoteCluster] = useState(null);
  const [tokenReveal, setTokenReveal] = useState({ title: '', token: '', visible: false });
  const [submitting, setSubmitting] = useState(false);

  const [createForm] = Form.useForm();
  const [remoteForm] = Form.useForm();

  const openCreateModal = useCallback(() => {
    createForm.resetFields();
    createForm.setFieldsValue({
      tenant_id: tenantOptions[0]?.id,
      name: '',
      edge_admin_base_url: '',
      edge_openapi_token: '',
      node_code: '',
      remark: '',
    });
    setCreateModalOpen(true);
  }, [createForm, tenantOptions]);

  const openRemoteModal = useCallback((record) => {
    setRemoteCluster(record);
    remoteForm.setFieldsValue({
      edge_admin_base_url: record.edge_admin_base_url || '',
      edge_openapi_token: '',
      node_code: record.node_code || '',
      remark: record.remark || '',
    });
  }, [remoteForm]);

  const closeTokenReveal = useCallback(() => {
    setTokenReveal({ title: '', token: '', visible: false });
  }, []);

  const submitAction = useCallback(async (formData, okMessage) => {
    setSubmitting(true);
    try {
      const result = await apiPost(API.cloudEdgeClustersAction, formData);
      if (okMessage) {
        message.success(okMessage);
      }
      await run();
      return result || {};
    } catch (e) {
      message.error(e.message || '操作失败');
      throw e;
    } finally {
      setSubmitting(false);
    }
  }, [message, run]);

  const handleToggle = useCallback(async (record) => {
    const form = new FormData();
    form.append('action', 'toggle');
    form.append('cluster_id', String(record.id));
    await submitAction(form, '已更新集群状态');
  }, [submitAction]);

  const handleRotate = useCallback(async (record) => {
    const form = new FormData();
    form.append('action', 'rotate');
    form.append('cluster_id', String(record.id));
    const result = await submitAction(form, '已轮换集群 Token');
    if (result?.rotated_token) {
      setTokenReveal({
        title: `${record.name || '边缘集群'} 新 Token`,
        token: result.rotated_token,
        visible: true,
      });
    }
  }, [submitAction]);

  const handleCreate = useCallback(async () => {
    try {
      const values = await createForm.validateFields();
      const form = new FormData();
      form.append('action', 'create');
      Object.entries(values).forEach(([key, value]) => {
        const normalized = String(value ?? '').trim();
        if (normalized) {
          form.append(key, normalized);
        }
      });
      const result = await submitAction(form, '集群已创建');
      setCreateModalOpen(false);
      if (result?.created_token) {
        setTokenReveal({
          title: `${values.name || '边缘集群'} Edge Token`,
          token: result.created_token,
          visible: true,
        });
      }
    } catch (e) {
      if (!e?.errorFields) {
        throw e;
      }
    }
  }, [createForm, submitAction]);

  const handleSaveRemote = useCallback(async () => {
    if (!remoteCluster) return;
    try {
      const values = await remoteForm.validateFields();
      const form = new FormData();
      form.append('action', 'update_remote');
      form.append('cluster_id', String(remoteCluster.id));
      Object.entries(values).forEach(([key, value]) => {
        const normalized = String(value ?? '').trim();
        form.append(key, normalized);
      });
      await submitAction(form, '远控配置已保存');
      setRemoteCluster(null);
    } catch (e) {
      if (!e?.errorFields) {
        throw e;
      }
    }
  }, [remoteCluster, remoteForm, submitAction]);

  if (data?.mode_enabled === false) {
    return (
      <EdgeCloudConnection
        connection={edgeConnection}
        loading={loading}
        error={error}
        run={run}
      />
    );
  }

  if (!data && loading) {
    return (
      <div>
        <PageHeader title="云边连接" icon={<CloudOutlined />} description="正在读取云端连接状态。" />
        <Card loading />
      </div>
    );
  }

  if (!accessOk) {
    return (
      <div>
        <PageHeader title="云边连接" icon={<CloudOutlined />} description="登记并验证 Beacon Edge 节点。" />
        <Alert type="warning" showIcon message={data?.access_message || '当前账号无权访问云边连接'} />
      </div>
    );
  }

  const columns = [
    { title: '名称', dataIndex: 'name', width: 180, ellipsis: true },
    { title: '节点编号', dataIndex: 'node_code', width: 140, ellipsis: true },
    {
      title: '状态',
      width: 120,
      render: (_, record) => (
        <Space size={[6, 6]} wrap>
          <Tag color={record.enabled ? 'success' : 'default'}>{record.enabled ? '启用' : '禁用'}</Tag>
          <Tag color={record.is_unhealthy ? 'error' : 'success'}>
            {record.is_unhealthy ? '异常' : '正常'}
          </Tag>
        </Space>
      ),
    },
    {
      title: '远控',
      width: 160,
      render: (_, record) => (
        <Space size={[6, 6]} wrap>
          <Tag color={record.remote_configured ? 'processing' : 'default'}>
            {record.remote_configured ? '已配置' : '未配置'}
          </Tag>
          {record.remote_status ? <Text type="secondary">{record.remote_status}</Text> : null}
        </Space>
      ),
    },
    { title: '版本', dataIndex: 'version', width: 110, ellipsis: true },
    { title: '目标版本', dataIndex: 'rollout_target_version', width: 110, ellipsis: true },
    {
      title: '最近心跳',
      dataIndex: 'last_seen_at',
      width: 170,
      render: (v, record) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {record.heartbeat_age_text || formatTime(v)}
        </Text>
      ),
    },
    { title: 'Edge 管理地址', dataIndex: 'edge_admin_base_url', ellipsis: true },
  ];

  return (
    <div>
      <PageHeader
        title="云边连接"
        icon={<CloudOutlined />}
        description="登记 Edge 节点，并查看真实心跳与远程连通状态。"
        extra={(
          <Space>
            {manageAllowed ? (
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
                接入边缘节点
              </Button>
            ) : null}
            <Button icon={<ReloadOutlined />} onClick={() => run()}>
              刷新
            </Button>
          </Space>
        )}
      />

      {error ? <Alert type="error" showIcon message={error.message || '连接状态加载失败'} style={{ marginBottom: 16 }} /> : null}

      {rows.length ? (
        <KpiCardGroup>
          <KpiCard title="已登记节点" value={summary.total_count ?? 0} icon={<CloudOutlined />} />
          <KpiCard title="可远程访问" value={summary.configured_count ?? 0} color="#2563eb" />
          <KpiCard title="需处理" value={summary.unhealthy_count ?? 0} color="#dc2626" />
          <KpiCard title="失联节点" value={summary.stale_heartbeat_count ?? 0} color="#fa8c16" />
        </KpiCardGroup>
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: topUnhealthy.length || rolloutRows.length
            ? 'minmax(0, 1.6fr) minmax(320px, 1fr)'
            : 'minmax(0, 1fr)',
          gap: 16,
          marginBottom: 16,
        }}
      >
        <Card size="small" title="连接状态">
          {rows.length ? (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
                gap: 12,
              }}
            >
              {rows.map((record) => (
                <ClusterCard
                  key={record.id}
                  record={record}
                  manageAllowed={manageAllowed}
                  onToggle={handleToggle}
                  onRotate={handleRotate}
                  onEditRemote={openRemoteModal}
                />
              ))}
            </div>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有边缘节点接入"
            >
              {manageAllowed ? (
                <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
                  创建接入凭证
                </Button>
              ) : null}
              <Paragraph type="secondary" style={{ margin: '12px auto 0', maxWidth: 520 }}>
                创建后复制 Edge Token，再到对应 Edge 的“云平台接入”页填写 Cloud 地址和 Token。
              </Paragraph>
            </Empty>
          )}
        </Card>

        {topUnhealthy.length || rolloutRows.length ? (
          <div style={{ display: 'grid', gap: 16 }}>
            {topUnhealthy.length ? (
              <Card size="small" title="需要处理">
                <div style={{ display: 'grid', gap: 10 }}>
                {topUnhealthy.map((item) => (
                  <div
                    key={item.id || `${item.name}-${item.node_code}`}
                    style={{ paddingBottom: 10, borderBottom: '1px solid var(--beacon-border-muted)' }}
                  >
                    <Space wrap size={[8, 8]}>
                      <Text strong>{item.name || '-'}</Text>
                      <Text type="secondary">{item.node_code || '-'}</Text>
                      {item.heartbeat_age_text ? <Tag color="orange">{item.heartbeat_age_text}</Tag> : null}
                    </Space>
                    <div style={{ marginTop: 8 }}>
                      <Space wrap size={[6, 6]}>
                        {(item.issues || []).map((issue) => (
                          <Tag key={`${item.id}-${issue}`} color="error">
                            {issue}
                          </Tag>
                        ))}
                      </Space>
                    </div>
                  </div>
                ))}
                </div>
              </Card>
            ) : null}

            {rolloutRows.length ? (
              <Card size="small" title="升级推进">
                <div style={{ display: 'grid', gap: 10 }}>
                {rolloutRows.map((item) => (
                  <div
                    key={`rollout-${item.id}`}
                    style={{ paddingBottom: 10, borderBottom: '1px solid var(--beacon-border-muted)' }}
                  >
                    <Space wrap size={[8, 8]}>
                      <Text strong>{item.name || '-'}</Text>
                      {item.rollout_status_label ? (
                        <Tag color={item.rollout_status_tone || 'processing'}>
                          {item.rollout_status_label}
                        </Tag>
                      ) : null}
                      {item.rollout_channel ? <Tag>{item.rollout_channel}</Tag> : null}
                    </Space>
                    <div style={{ marginTop: 8, display: 'grid', gap: 4 }}>
                      <Text type="secondary">
                        目标版本：{item.rollout_target_version || '-'}
                      </Text>
                      {item.rollout_error ? <Text type="danger">{item.rollout_error}</Text> : null}
                    </div>
                  </div>
                ))}
                </div>
              </Card>
            ) : null}
          </div>
        ) : null}
      </div>

      {rows.length ? (
        <Card size="small" title="全部节点">
          <ProTable
            columns={columns}
            dataSource={rows}
            loading={loading}
            rowKey="id"
            pagination={false}
          />
        </Card>
      ) : null}

      <Modal
        open={createModalOpen}
        title="接入边缘节点"
        okText="创建并生成 Token"
        cancelText="取消"
        onOk={handleCreate}
        onCancel={() => setCreateModalOpen(false)}
        confirmLoading={submitting}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          {tenantOptions.length ? (
            <Form.Item name="tenant_id" label="租户">
              <Select
                options={tenantOptions.map((item) => ({
                  value: item.id,
                  label: item.name || item.slug || `Tenant #${item.id}`,
                }))}
              />
            </Form.Item>
          ) : null}
          <Form.Item name="name" label="集群名称" rules={[{ required: true, message: '请输入集群名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="edge_admin_base_url"
            label="Edge 管理地址（可选）"
            extra="仅在需要从 Cloud 远程查看视频、录像和运行状态时填写。"
          >
            <Input placeholder="http://127.0.0.1:9991" />
          </Form.Item>
          <Form.Item name="edge_openapi_token" label="Edge OpenAPI Token（可选）">
            <Input.Password />
          </Form.Item>
          <Form.Item name="node_code" label="节点编号">
            <Input />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={Boolean(remoteCluster)}
        title="远程访问设置"
        okText="保存配置"
        cancelText="取消"
        onOk={handleSaveRemote}
        onCancel={() => setRemoteCluster(null)}
        confirmLoading={submitting}
        destroyOnHidden
      >
        <Form form={remoteForm} layout="vertical" preserve={false}>
          <Form.Item name="edge_admin_base_url" label="Edge 管理地址">
            <Input />
          </Form.Item>
          <Form.Item name="edge_openapi_token" label="Edge OpenAPI Token">
            <Input.Password placeholder="留空表示不更新" />
          </Form.Item>
          <Form.Item name="node_code" label="节点编号">
            <Input />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={tokenReveal.visible}
        title={tokenReveal.title || 'Edge Token'}
        footer={<Button onClick={closeTokenReveal}>关闭</Button>}
        onCancel={closeTokenReveal}
        destroyOnHidden
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="warning"
            showIcon
            message="该 token 只在当前操作后显示一次。"
          />
          <Paragraph copyable={{ text: tokenReveal.token || '' }}>
            {tokenReveal.token || '-'}
          </Paragraph>
          <Text type="secondary">
            请尽快写入对应 edge 节点配置，避免丢失。
          </Text>
        </Space>
      </Modal>
    </div>
  );
}

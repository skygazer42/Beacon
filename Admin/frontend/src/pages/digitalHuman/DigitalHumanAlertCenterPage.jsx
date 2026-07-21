import React, { useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Card, Descriptions, Input, Modal, Space, Switch, Table, Tabs, Tag } from 'antd';
import { AlertOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import DetailDrawer from '../../components/DetailDrawer';
import SkeletonPage from '../../components/Skeleton';
import useDigitalHumanResource from './useDigitalHumanResource';
import {
  createDigitalHumanAlertRoute,
  deleteDigitalHumanAlertRoute,
  getDigitalHumanAlertDetail,
  getDigitalHumanAlertRoutingConfig,
  listDigitalHumanAlerts,
  resolveDigitalHumanAlert,
  saveDigitalHumanAlertRoutingEnabled,
  updateDigitalHumanAlertRoute,
} from './dataAdapter';
import './digitalHumanStyles.css';

function levelTag(level) {
  if (level === 'critical') return <Tag color="error">严重故障</Tag>;
  if (level === 'warning') return <Tag color="warning">系统告警</Tag>;
  return <Tag color="processing">常规提示</Tag>;
}

function statusTag(status) {
  return status === 'pending' ? <Tag color="error">待处理</Tag> : <Tag color="success">已解决</Tag>;
}

function deliveryTag(delivery) {
  if (delivery.statusTone === 'error') return <Tag color="error">{delivery.statusLabel}</Tag>;
  if (delivery.statusTone === 'warning') return <Tag color="warning">{delivery.statusLabel}</Tag>;
  if (delivery.statusTone === 'success') return <Tag color="success">{delivery.statusLabel}</Tag>;
  return <Tag>{delivery.statusLabel}</Tag>;
}

function routePayloadFromDraft(draft) {
  return {
    region: draft.region,
    webhook: draft.webhook,
    secret: draft.secret,
    ownerName: draft.ownerName,
    ownerPhone: draft.ownerPhone,
    active: draft.active,
    defaultRoute: draft.defaultRoute,
  };
}

function emptyRouteDraft() {
  return {
    id: null,
    region: '',
    webhook: '',
    secret: '',
    ownerName: '',
    ownerPhone: '',
    active: true,
    defaultRoute: false,
  };
}

export default function DigitalHumanAlertCenterPage() {
  const { message } = App.useApp();
  const alertsResource = useDigitalHumanResource(listDigitalHumanAlerts, []);
  const routingResource = useDigitalHumanResource(getDigitalHumanAlertRoutingConfig, []);
  const [filters, setFilters] = useState({});
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailData, setDetailData] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [routeModalOpen, setRouteModalOpen] = useState(false);
  const [routeDraft, setRouteDraft] = useState(emptyRouteDraft());
  const [routeSaving, setRouteSaving] = useState(false);
  const [routeEnabled, setRouteEnabled] = useState(false);
  const [routeToggleSaving, setRouteToggleSaving] = useState(false);
  const [inlineResolvingId, setInlineResolvingId] = useState(null);
  const [activeTab, setActiveTab] = useState('alerts');

  const { data: alertsData, loading, error, reload, setData } = alertsResource;
  const { data: routingData, loading: routingLoading, error: routingError, reload: reloadRouting, setData: setRoutingData } = routingResource;

  const alerts = alertsData || [];
  const filteredAlerts = useMemo(() => {
    return alerts.filter((item) => {
      const regionHit = !filters.region || item.region === filters.region;
      const statusHit = !filters.status || item.status === filters.status;
      const levelHit = !filters.level || item.level === filters.level;
      return regionHit && statusHit && levelHit;
    });
  }, [alerts, filters]);
  const regionOptions = useMemo(
    () => Array.from(new Set(alerts.map((item) => item.region))).map((item) => ({ label: item, value: item })),
    [alerts],
  );

  useEffect(() => {
    setRouteEnabled(Boolean(routingData?.enabled));
  }, [routingData]);

  if (loading && !alertsData) {
    return <SkeletonPage kpiCount={4} />;
  }

  if (error && !alertsData) {
    return <Alert type="warning" showIcon message={error.message || '数字人告警中心加载失败'} />;
  }

  const pendingCount = filteredAlerts.filter((item) => item.status === 'pending').length;
  const resolvedCount = filteredAlerts.filter((item) => item.status === 'resolved').length;
  const criticalCount = filteredAlerts.filter((item) => item.level === 'critical').length;
  const routingCount = routingData?.routes?.filter((item) => item.active).length || 0;

  async function openDetail(alertId) {
    setDetailOpen(true);
    setDetailLoading(true);
    try {
      const payload = await getDigitalHumanAlertDetail(alertId);
      setDetailData(payload);
    } catch (detailError) {
      message.error(detailError.message || '告警详情加载失败');
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleResolve() {
    if (!detailData) return;
    setResolving(true);
    try {
      const nextDetail = await resolveAlert(detailData.id);
      setDetailData(nextDetail);
      message.success('告警已完成闭环处置');
    } catch (resolveError) {
      message.error(resolveError.message || '告警处理失败');
    } finally {
      setResolving(false);
    }
  }

  async function resolveAlert(alertId) {
    const nextDetail = await resolveDigitalHumanAlert(alertId);
    const nextAlerts = await listDigitalHumanAlerts();
    setData(nextAlerts);

    if (detailData?.id === alertId) {
      setDetailData(nextDetail);
    }

    return nextDetail;
  }

  async function handleResolveInline(alertId) {
    setInlineResolvingId(alertId);
    try {
      await resolveAlert(alertId);
      message.success('告警已完成闭环处置');
    } catch (resolveError) {
      message.error(resolveError.message || '告警处理失败');
    } finally {
      setInlineResolvingId(null);
    }
  }

  async function handleSaveRoutingEnabled() {
    setRouteToggleSaving(true);
    try {
      const nextConfig = await saveDigitalHumanAlertRoutingEnabled(routeEnabled);
      setRoutingData(nextConfig);
      setRouteEnabled(Boolean(nextConfig.enabled));
      setData(await listDigitalHumanAlerts());
      message.success('告警路由开关已保存');
    } catch (saveError) {
      message.error(saveError.message || '保存失败');
    } finally {
      setRouteToggleSaving(false);
    }
  }

  function startEditRoute(route) {
    setRouteDraft({
      id: route.id,
      region: route.region,
      webhook: '',
      secret: '',
      ownerName: route.ownerName,
      ownerPhone: route.ownerPhone,
      active: route.active,
      defaultRoute: route.defaultRoute,
    });
    setRouteModalOpen(true);
  }

  async function submitRoute() {
    const payload = routePayloadFromDraft(routeDraft);
    if (!payload.region || !payload.webhook || !payload.secret || !payload.ownerName || !payload.ownerPhone) {
      message.warning('请完整填写钉钉路由信息');
      return;
    }

    setRouteSaving(true);
    try {
      if (routeDraft.id == null) {
        await createDigitalHumanAlertRoute(payload);
      } else {
        await updateDigitalHumanAlertRoute(routeDraft.id, payload);
      }
      setRoutingData(await getDigitalHumanAlertRoutingConfig());
      setData(await listDigitalHumanAlerts());
      setRouteModalOpen(false);
      setRouteDraft(emptyRouteDraft());
      message.success('路由规则已保存');
    } catch (routeError) {
      message.error(routeError.message || '保存失败');
    } finally {
      setRouteSaving(false);
    }
  }

  async function removeRoute(routeId) {
    try {
      await deleteDigitalHumanAlertRoute(routeId);
      setRoutingData(await getDigitalHumanAlertRoutingConfig());
      setData(await listDigitalHumanAlerts());
      message.success('路由规则已删除');
    } catch (routeError) {
      message.error(routeError.message || '删除失败');
    }
  }

  const columns = [
    {
      title: '告警内容',
      width: 260,
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{record.title}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.description}</div>
        </div>
      ),
    },
    {
      title: '设备 / 区域',
      width: 180,
      render: (_, record) => (
        <div>
          <div>{record.deviceName}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.deviceCode} · {record.region}</div>
        </div>
      ),
    },
    { title: '模块', dataIndex: 'module', width: 110 },
    { title: '级别', dataIndex: 'level', width: 110, render: (_, record) => levelTag(record.level) },
    { title: '状态', dataIndex: 'status', width: 100, render: (_, record) => statusTag(record.status) },
    {
      title: '推送状态',
      width: 160,
      render: (_, record) => (
        <div>
          {deliveryTag(record.delivery)}
          <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>
            {record.delivery.routeLabel}
          </div>
        </div>
      ),
    },
    { title: '发生时间', dataIndex: 'lastOccurredAt', width: 160 },
    {
      title: '操作',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openDetail(record.id)}>
            查看
          </Button>
          {record.status === 'pending' ? (
            <Button
              type="link"
              size="small"
              loading={inlineResolvingId === record.id}
              onClick={() => handleResolveInline(record.id)}
            >
              闭环
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  const routingColumns = [
    {
      title: '匹配区域',
      dataIndex: 'region',
      render: (_, record) => (
        <span>{record.defaultRoute ? '全局兜底' : record.region}</span>
      ),
    },
    {
      title: 'Webhook',
      dataIndex: 'webhook',
      render: (value) => <span style={{ fontSize: 12, color: '#64748b' }}>{value}</span>,
    },
    {
      title: '负责人',
      render: (_, record) => (
        <div className="beacon-dh-route-owner">
          <span className="beacon-dh-route-owner__name">{record.ownerName}</span>
          <span className="beacon-dh-route-owner__phone">{record.ownerPhone}</span>
        </div>
      ),
    },
    {
      title: '状态',
      render: (_, record) => (
        <Tag color={record.active ? 'success' : 'default'}>
          {record.active ? '启用中' : '已停用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => startEditRoute(record)}>编辑</Button>
          <Button type="link" size="small" danger onClick={() => removeRoute(record.id)}>删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="beacon-dh-page">
      <PageHeader
        title="数字人告警中心"
        icon={<AlertOutlined />}
        description="集中查看数字人链路告警，并直接在 Beacon 本地维护通知路由。"
        extra={(
          <Button icon={<ReloadOutlined />} onClick={() => { reload(); reloadRouting(); }}>
            刷新
          </Button>
        )}
      />

      <KpiCardGroup>
        <KpiCard title="待处理告警" value={pendingCount} suffix="条" color="#ef4444" icon={<AlertOutlined />} />
        <KpiCard title="已解决告警" value={resolvedCount} suffix="条" color="#16a34a" icon={<AlertOutlined />} />
        <KpiCard title="严重故障" value={criticalCount} suffix="条" color="#f97316" icon={<AlertOutlined />} />
        <KpiCard title="生效路由" value={routingCount} suffix="条" color="#2563eb" icon={<SaveOutlined />} />
      </KpiCardGroup>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'alerts',
            label: '实时告警列表',
            children: (
              <>
                <FilterBar
                  filters={[
                    { key: 'region', label: '所属区域', type: 'select', options: regionOptions },
                    {
                      key: 'status',
                      label: '状态',
                      type: 'select',
                      options: [
                        { label: '待处理', value: 'pending' },
                        { label: '已解决', value: 'resolved' },
                      ],
                    },
                    {
                      key: 'level',
                      label: '级别',
                      type: 'select',
                      options: [
                        { label: '严重故障', value: 'critical' },
                        { label: '系统告警', value: 'warning' },
                        { label: '常规提示', value: 'info' },
                      ],
                    },
                  ]}
                  initialValues={filters}
                  onSearch={(values) => setFilters(values)}
                  onReset={() => setFilters({})}
                />

                <Card className="beacon-panel-card beacon-panel-card--tone-slate" size="small" styles={{ body: { padding: 0 } }}>
                  <ProTable
                    columns={columns}
                    dataSource={filteredAlerts}
                    loading={loading}
                    rowKey="id"
                    pagination={false}
                  />
                </Card>
              </>
            ),
          },
          {
            key: 'routing',
            label: '推送与路由配置',
            children: (
              <>
                {routingError ? (
                  <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={routingError.message || '路由配置加载失败'} />
                ) : null}
                <Card
                  className="beacon-panel-card beacon-panel-card--tone-blue"
                  size="small"
                  title="钉钉路由开关"
                  extra={(
                    <Space>
                      <Switch
                        checked={routeEnabled}
                        data-testid="digital-human-routing-toggle"
                        onChange={setRouteEnabled}
                      />
                      <Button type="primary" loading={routeToggleSaving} onClick={handleSaveRoutingEnabled}>保存</Button>
                    </Space>
                  )}
                >
                  <div className="beacon-dh-detail-note">
                    当前配置来自真实数字人后端。路由列表中的 Webhook 和 Secret 为脱敏值，编辑时需要重新输入完整内容。
                  </div>
                </Card>

                <Card
                  className="beacon-panel-card beacon-panel-card--tone-cyan"
                  size="small"
                  style={{ marginTop: 16 }}
                  title="路由列表"
                  extra={(
                    <Button
                      type="primary"
                      data-testid="digital-human-routing-add"
                      onClick={() => {
                        setRouteDraft(emptyRouteDraft());
                        setRouteModalOpen(true);
                      }}
                    >
                      新增路由
                    </Button>
                  )}
                >
                  <Table
                    columns={routingColumns}
                    dataSource={routingData?.routes || []}
                    rowKey="id"
                    loading={routingLoading}
                    pagination={false}
                    size="small"
                  />
                </Card>
              </>
            ),
          },
        ]}
      />

      <DetailDrawer
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          setDetailData(null);
        }}
        title={detailData ? `${detailData.title} · 诊断单` : '告警详情'}
        width={760}
        loading={detailLoading}
        footer={(
          <>
            <Button onClick={() => setDetailOpen(false)}>关闭</Button>
            {detailData?.status === 'pending' ? (
              <Button type="primary" loading={resolving} onClick={handleResolve}>
                标记为已解决
              </Button>
            ) : null}
          </>
        )}
      >
        {detailData ? (
          <>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="设备">{detailData.deviceName}</Descriptions.Item>
              <Descriptions.Item label="区域">{detailData.region}</Descriptions.Item>
              <Descriptions.Item label="告警模块">{detailData.module}</Descriptions.Item>
              <Descriptions.Item label="状态">{statusTag(detailData.status)}</Descriptions.Item>
              <Descriptions.Item label="推送状态">{deliveryTag(detailData.delivery)}</Descriptions.Item>
              <Descriptions.Item label="命中路由">{detailData.delivery.routeLabel}</Descriptions.Item>
              <Descriptions.Item label="发生时间">{detailData.firstOccurredAt}</Descriptions.Item>
              <Descriptions.Item label="最近更新">{detailData.lastOccurredAt}</Descriptions.Item>
              <Descriptions.Item label="告警说明" span={2}>{detailData.description}</Descriptions.Item>
            </Descriptions>

            <Card className="beacon-panel-card beacon-panel-card--tone-orange" size="small" title="AI 智能诊断">
              <div className="beacon-dh-ai-text">{detailData.diagnosisText}</div>
            </Card>

            <Card className="beacon-panel-card beacon-panel-card--tone-slate" size="small" title="处置时间线" style={{ marginTop: 16 }}>
              <div className="beacon-dh-bar-list">
                {detailData.timeline.map((item) => (
                  <div key={`${item.time}-${item.action}`}>
                    <div style={{ fontWeight: 600 }}>{item.action}</div>
                    <div style={{ color: '#64748b', fontSize: 12 }}>{item.time} · {item.detail}</div>
                  </div>
                ))}
              </div>
            </Card>
          </>
        ) : null}
      </DetailDrawer>

      <Modal
        title={routeDraft.id == null ? '新增推送路由' : '编辑推送路由'}
        open={routeModalOpen}
        onCancel={() => setRouteModalOpen(false)}
        onOk={submitRoute}
        okText="保存"
        confirmLoading={routeSaving}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Input placeholder="匹配区域" value={routeDraft.region} onChange={(event) => setRouteDraft((prev) => ({ ...prev, region: event.target.value }))} />
          <Input
            placeholder={routeDraft.id == null ? 'Webhook' : '重新输入完整 Webhook'}
            value={routeDraft.webhook}
            onChange={(event) => setRouteDraft((prev) => ({ ...prev, webhook: event.target.value }))}
          />
          <Input
            placeholder={routeDraft.id == null ? 'Secret' : '重新输入完整 Secret'}
            value={routeDraft.secret}
            onChange={(event) => setRouteDraft((prev) => ({ ...prev, secret: event.target.value }))}
          />
          <Input placeholder="负责人姓名" value={routeDraft.ownerName} onChange={(event) => setRouteDraft((prev) => ({ ...prev, ownerName: event.target.value }))} />
          <Input placeholder="负责人手机号" value={routeDraft.ownerPhone} onChange={(event) => setRouteDraft((prev) => ({ ...prev, ownerPhone: event.target.value }))} />
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>启用</span>
            <Switch checked={routeDraft.active} onChange={(checked) => setRouteDraft((prev) => ({ ...prev, active: checked }))} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>设为全局兜底</span>
            <Switch checked={routeDraft.defaultRoute} onChange={(checked) => setRouteDraft((prev) => ({ ...prev, defaultRoute: checked }))} />
          </div>
        </Space>
      </Modal>
    </div>
  );
}

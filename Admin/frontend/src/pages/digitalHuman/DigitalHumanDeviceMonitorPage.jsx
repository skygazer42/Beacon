import React, { useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Card, Checkbox, Input, Progress, Space, Switch, Tag } from 'antd';
import { DeploymentUnitOutlined, DesktopOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import DetailDrawer, { DetailSection } from '../../components/DetailDrawer';
import SkeletonPage from '../../components/Skeleton';
import useDigitalHumanResource from './useDigitalHumanResource';
import {
  DIGITAL_HUMAN_WEEKDAY_OPTIONS,
  listDigitalHumanDevices,
  updateDigitalHumanDeviceWindow,
} from './dataAdapter';
import './digitalHumanStyles.css';

function statusTag(status) {
  if (status === 'online') return <Tag color="success">在线</Tag>;
  if (status === 'warning') return <Tag color="warning">告警</Tag>;
  if (status === 'error') return <Tag color="error">故障</Tag>;
  return <Tag>离线</Tag>;
}

function serviceTag(label, value) {
  if (value === null) return <Tag>{label}: 待接入</Tag>;
  return <Tag color={value ? 'success' : 'error'}>{label}: {value ? '正常' : '异常'}</Tag>;
}

function matchesFilter(device, filters) {
  const keyword = String(filters.keyword || '').trim().toLowerCase();
  const keywordHit = !keyword
    || device.name.toLowerCase().includes(keyword)
    || device.deviceCode.toLowerCase().includes(keyword);
  const regionHit = !filters.region || device.region === filters.region;
  const statusHit = !filters.status || device.status === filters.status;
  return keywordHit && regionHit && statusHit;
}

export default function DigitalHumanDeviceMonitorPage() {
  const { message } = App.useApp();
  const { data, loading, error, reload, setData } = useDigitalHumanResource(listDigitalHumanDevices, []);
  const [filters, setFilters] = useState({});
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [saving, setSaving] = useState(false);
  const [alertWindow, setAlertWindow] = useState({
    enabled: false,
    weekdays: [],
    startTime: '',
    endTime: '',
  });

  useEffect(() => {
    if (!selectedDevice) return;
    setAlertWindow({
      enabled: Boolean(selectedDevice.alertWindow?.enabled),
      weekdays: selectedDevice.alertWindow?.weekdays || [],
      startTime: selectedDevice.alertWindow?.startTime || '',
      endTime: selectedDevice.alertWindow?.endTime || '',
    });
  }, [selectedDevice]);

  const devices = data || [];
  const filteredDevices = useMemo(
    () => devices.filter((device) => matchesFilter(device, filters)),
    [devices, filters],
  );
  const regionOptions = useMemo(
    () => Array.from(new Set(devices.map((device) => device.region))).map((item) => ({ label: item, value: item })),
    [devices],
  );

  if (loading && !data) {
    return <SkeletonPage kpiCount={4} />;
  }

  if (error && !data) {
    return <Alert type="warning" showIcon message={error.message || '数字人设备监控加载失败'} />;
  }

  const total = filteredDevices.length;
  const online = filteredDevices.filter((item) => item.status === 'online').length;
  const warning = filteredDevices.filter((item) => item.status === 'warning').length;
  const fault = filteredDevices.filter((item) => item.status === 'error').length;
  const offline = filteredDevices.filter((item) => item.status === 'offline').length;

  async function handleSaveAlertWindow() {
    if (!selectedDevice) return;
    if (alertWindow.enabled) {
      if (!alertWindow.weekdays.length) {
        message.warning('请选择至少一个预警生效周');
        return;
      }
      if (!alertWindow.startTime || !alertWindow.endTime || alertWindow.endTime <= alertWindow.startTime) {
        message.warning('请填写有效的预警生效时间');
        return;
      }
    }

    setSaving(true);
    try {
      const nextDevice = await updateDigitalHumanDeviceWindow(selectedDevice.id, alertWindow);
      setData((prev) => prev.map((item) => (item.id === nextDevice.id ? nextDevice : item)));
      setSelectedDevice(nextDevice);
      message.success('设备监管窗口已保存');
    } catch (saveError) {
      message.error(saveError.message || '保存失败');
    } finally {
      setSaving(false);
    }
  }

  const columns = [
    {
      title: '设备信息',
      dataIndex: 'name',
      width: 220,
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{record.name}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.deviceCode} · {record.region}</div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 88,
      render: (value) => statusTag(value),
    },
    {
      title: '网络 / 上报',
      width: 180,
      render: (_, record) => (
        <div>
          <div style={{ fontSize: 12, color: '#475569' }}>延迟 {record.netLatency} ms</div>
          <div style={{ fontSize: 12, color: '#64748b' }}>最近上报 {record.lastReportAt}</div>
        </div>
      ),
    },
    {
      title: '资源负载',
      width: 220,
      render: (_, record) => (
        <div className="beacon-dh-device-bars">
          {[
            { key: 'cpu', label: 'CPU', value: record.cpu },
            { key: 'mem', label: '内存', value: record.mem },
            { key: 'gpu', label: 'GPU', value: record.gpu },
          ].map((item) => (
            <div className="beacon-dh-device-bars__row" key={item.key}>
              <span>{item.label}</span>
              <Progress
                percent={item.value}
                size="small"
                showInfo={false}
                strokeColor={item.value >= 85 ? '#ef4444' : item.value >= 70 ? '#f97316' : '#2563eb'}
              />
              <strong>{item.value}%</strong>
            </div>
          ))}
        </div>
      ),
    },
    {
      title: '服务链路',
      width: 220,
      render: (_, record) => (
        <div className="beacon-dh-chip-list">
          {serviceTag('推流', record.services.stream)}
          {serviceTag('大模型', record.services.llm)}
        </div>
      ),
    },
    {
      title: '操作',
      width: 100,
      fixed: 'right',
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          onClick={() => setSelectedDevice(record)}
        >
          深度监控
        </Button>
      ),
    },
  ];

  return (
    <div className="beacon-dh-page">
      <PageHeader
        title="终端设备监控"
        icon={<DesktopOutlined />}
        description="统一查看数字人终端的运行状态、资源负载与监管时窗。"
        extra={(
          <Button icon={<ReloadOutlined />} onClick={() => reload()}>
            刷新
          </Button>
        )}
      />

      <KpiCardGroup>
        <KpiCard title="已纳管终端" value={total} suffix="台" icon={<DesktopOutlined />} color="#2563eb" />
        <KpiCard title="在线稳定" value={online} suffix="台" icon={<DeploymentUnitOutlined />} color="#16a34a" />
        <KpiCard title="预警 / 故障" value={warning + fault} suffix="台" icon={<DeploymentUnitOutlined />} color="#f97316" />
        <KpiCard title="离线资产" value={offline} suffix="台" icon={<DeploymentUnitOutlined />} color="#64748b" />
      </KpiCardGroup>

      <FilterBar
        filters={[
          { key: 'keyword', label: '设备名称 / ID', type: 'input', placeholder: '请输入设备名称或 ID' },
          { key: 'region', label: '所属区域', type: 'select', options: regionOptions },
          {
            key: 'status',
            label: '运行状态',
            type: 'select',
            options: [
              { label: '在线', value: 'online' },
              { label: '告警', value: 'warning' },
              { label: '故障', value: 'error' },
              { label: '离线', value: 'offline' },
            ],
          },
        ]}
        initialValues={filters}
        onSearch={(values) => setFilters(values)}
        onReset={() => setFilters({})}
      />

      <Card
        className="beacon-panel-card beacon-panel-card--tone-slate"
        size="small"
        styles={{ body: { padding: 0 } }}
      >
        <ProTable
          columns={columns}
          dataSource={filteredDevices}
          loading={loading}
          rowKey="id"
          pagination={false}
        />
      </Card>

      <DetailDrawer
        open={Boolean(selectedDevice)}
        onClose={() => setSelectedDevice(null)}
        title={selectedDevice ? `${selectedDevice.name} · 深度监控` : '深度监控'}
        width={760}
        footer={(
          <>
            <Button onClick={() => setSelectedDevice(null)}>关闭</Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              data-testid="digital-human-device-save"
              onClick={handleSaveAlertWindow}
            >
              保存监管时窗
            </Button>
          </>
        )}
      >
        {selectedDevice && (
          <>
            <DetailSection
              title="基础信息"
              items={[
                { label: '设备编号', value: selectedDevice.deviceCode },
                { label: '所属区域', value: selectedDevice.region },
                { label: '运行状态', value: statusTag(selectedDevice.status) },
                { label: '最近上报', value: selectedDevice.lastReportAt },
                { label: '当前窗口', value: selectedDevice.activeWindowTitle },
                { label: '主进程', value: selectedDevice.activeWindowProcess },
              ]}
            />

            <DetailSection
              title="服务链路"
              items={[
                { label: '推流服务', value: selectedDevice.services.stream === null ? '待接入' : selectedDevice.services.stream ? '正常' : '异常' },
                { label: '大模型服务', value: selectedDevice.services.llm === null ? '待接入' : selectedDevice.services.llm ? '正常' : '异常' },
                { label: '摄像头', value: selectedDevice.peripherals.cam ? '已连接' : '未连接' },
                { label: '麦克风', value: selectedDevice.peripherals.mic ? '已连接' : '未连接' },
              ]}
            />

            <Card
              className="beacon-panel-card beacon-panel-card--tone-blue"
              size="small"
              title="监管时窗"
              style={{ marginTop: 16 }}
            >
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>启用告警时窗</span>
                  <Switch
                    checked={alertWindow.enabled}
                    onChange={(checked) => setAlertWindow((prev) => ({ ...prev, enabled: checked }))}
                  />
                </div>

                <div>
                  <div style={{ marginBottom: 8, color: '#64748b', fontSize: 12 }}>生效周</div>
                  <Checkbox.Group
                    options={DIGITAL_HUMAN_WEEKDAY_OPTIONS}
                    value={alertWindow.weekdays}
                    disabled={!alertWindow.enabled}
                    onChange={(values) => setAlertWindow((prev) => ({ ...prev, weekdays: values }))}
                  />
                </div>

                <Space wrap size={12}>
                  <div>
                    <div style={{ marginBottom: 6, color: '#64748b', fontSize: 12 }}>开始</div>
                    <Input
                      style={{ width: 160 }}
                      placeholder="08:30"
                      value={alertWindow.startTime}
                      disabled={!alertWindow.enabled}
                      onChange={(event) => setAlertWindow((prev) => ({ ...prev, startTime: event.target.value }))}
                    />
                  </div>
                  <div>
                    <div style={{ marginBottom: 6, color: '#64748b', fontSize: 12 }}>结束</div>
                    <Input
                      style={{ width: 160 }}
                      placeholder="21:00"
                      value={alertWindow.endTime}
                      disabled={!alertWindow.enabled}
                      onChange={(event) => setAlertWindow((prev) => ({ ...prev, endTime: event.target.value }))}
                    />
                  </div>
                </Space>

                <div className="beacon-dh-detail-note">
                  当前页直接由 Beacon 本地数字人档案接口保存监管时窗；仅 Beacon 管理员可以执行修改。
                </div>
              </Space>
            </Card>
          </>
        )}
      </DetailDrawer>
    </div>
  );
}

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, Spin, Alert, Button, Space, Typography, Modal, App, Row, Col } from 'antd';
import {
  AreaChartOutlined,
  CloudServerOutlined,
  HddOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  PoweroffOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import MetricTrendCard from '../../components/MetricTrendCard';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiGet, apiPost } from '../../api/client';
import { formatBytes, formatPercent } from '../../utils/format';
import { appendMetricHistory, buildTrendLabel } from '../../utils/trends';
import './PlatformPage.css';

const { Text } = Typography;
const TREND_REFRESH_MS = 8000;
const TREND_WINDOW = 12;

function formatNullablePercent(value) {
  return value == null ? '-' : formatPercent(value);
}

async function runRestartAction(action, messageApi, successText) {
  try {
    await apiPost(action, {});
    messageApi.success(successText);
  } catch (e) {
    messageApi.error(e?.message || '请求失败');
    throw e;
  }
}

function showFinalSystemRestartConfirm(action, messageApi) {
  return new Promise((resolve, reject) => {
    Modal.confirm({
      title: '最后确认：将重启整台机器',
      content: '再次确认执行系统重启。此操作不可撤销。',
      okText: '立即重启',
      okButtonProps: { danger: true },
      onOk: () => runRestartAction(action, messageApi, '系统重启请求已发送').then(resolve).catch(reject),
      onCancel: () => reject(new Error('cancel')),
    });
  });
}

function confirmSoftwareRestart(action, messageApi) {
  Modal.confirm({
    title: '重启软件服务？',
    content: '将请求平台重启 Beacon 相关软件进程，可能导致短暂中断。',
    okText: '确认重启',
    okButtonProps: { danger: true },
    onOk: () => runRestartAction(action, messageApi, '重启请求已发送'),
  });
}

function confirmSystemRestart(action, messageApi) {
  Modal.confirm({
    title: '确认重启操作系统？',
    content: '此操作将重启服务器操作系统，所有会话将中断。',
    okText: '继续',
    okButtonProps: { danger: true },
    onOk: () => showFinalSystemRestartConfirm(action, messageApi),
  });
}

function formatPlatformUptime(uptimeStart) {
  if (!uptimeStart) {
    return '-';
  }
  const started = Number(uptimeStart);
  if (Number.isNaN(started) || started <= 0) {
    return '-';
  }
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - started));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return [d ? `${d} 天` : '', h ? `${h} 小时` : '', m ? `${m} 分` : ''].filter(Boolean).join(' ') || `${sec} 秒`;
}

function buildPlatformOverviewItems({ summary, basic, metrics }) {
  const host = summary.machine_node || basic.machineNode || summary.node_name || basic.nodeName || '-';
  const diskRatio = summary.disk_usage_percent == null
    ? formatNullablePercent(metrics.disk_ratio)
    : `${summary.disk_usage_percent}%`;
  const diskDetail = summary.disk_total_bytes == null
    ? '-'
    : `${formatBytes(summary.disk_used_bytes)} / ${formatBytes(summary.disk_total_bytes)}`;
  const diskDetailSuffix = diskDetail === '-' ? '' : `（${diskDetail}）`;
  return [
    { key: 'version', label: '版本', value: summary.version || basic.version || '-' },
    { key: 'host', label: '主机', value: host },
    { key: 'os', label: '系统', value: basic.osRelease || '-' },
    { key: 'uptime', label: '运行时长', value: formatPlatformUptime(basic.adminStartTimestamp) },
    { key: 'cpu', label: 'CPU', value: `${basic.cpu || '-'}（负载约 ${formatNullablePercent(metrics.cpu_ratio)}）` },
    { key: 'memory', label: '内存', value: `使用率约 ${formatNullablePercent(metrics.mem_ratio)}` },
    { key: 'disk', label: '磁盘', value: `${diskRatio} ${diskDetailSuffix}`.trim() },
    { key: 'node_code', label: '节点编号', value: summary.node_code || basic.nodeCode || '-' },
  ];
}

function buildPlatformStorageItems({ summary, storage, metrics }) {
  const quota = storage.quota || {};
  const usage = storage.usage || {};
  return [
    { key: 'admin_port', label: 'Admin 端口', value: summary.admin_port || '-' },
    { key: 'analyzer_port', label: 'Analyzer 端口', value: summary.analyzer_port || '-' },
    { key: 'storage_root', label: '存储根路径', value: storage.storageRootPath || summary.storage_root_path || '-' },
    { key: 'alarm_root', label: '告警目录', value: storage.alarmStoragePath || '-' },
    { key: 'recording_root', label: '录像目录', value: storage.recordingStoragePath || '-' },
    {
      key: 'alarm_quota',
      label: '告警配额',
      value: quota.alarmMaxStorageMB ? `${quota.alarmMaxStorageMB} MB（已用 ${formatBytes(usage.alarmBytes)})` : `未限制（已用 ${formatBytes(usage.alarmBytes)})`,
    },
    {
      key: 'recording_quota',
      label: '录像配额',
      value: quota.recordingMaxStorageMB
        ? `${quota.recordingMaxStorageMB} MB（已用 ${formatBytes(usage.recordingBytes)})`
        : `未限制（已用 ${formatBytes(usage.recordingBytes)})`,
    },
    { key: 'outbox', label: 'Outbox', value: `pending ${metrics.outbox_pending ?? '-'} / failed ${metrics.outbox_failed ?? '-'}` },
    { key: 'leases', label: '授权租约(指标)', value: String(metrics.license_active_leases ?? '-') },
    { key: 'login_lockout', label: '登录锁定(指标)', value: `${metrics.login_lockout_active ?? '-'} 个` },
  ];
}

export default function PlatformPage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.platform);
  const [details, setDetails] = useState({ basicInfo: null, storageInfo: null });
  const [detailsLoading, setDetailsLoading] = useState(true);
  const [detailsError, setDetailsError] = useState(null);
  const [trendHistory, setTrendHistory] = useState([]);
  const actions = data?.actions || {};
  const basicInfoAction = actions.basic_info || API.platformBasicInfo;
  const storageInfoAction = actions.storage_info || API.platformStorageInfo;
  const restartSoftwareAction = actions.restart_software || API.platformRestartSoftware;
  const restartSystemAction = actions.restart_system || API.platformRestartSystem;

  const loadDetails = useCallback(async () => {
    setDetailsLoading(true);
    setDetailsError(null);
    try {
      const [basicInfo, storageInfo] = await Promise.all([
        apiGet(basicInfoAction),
        apiGet(storageInfoAction),
      ]);
      setDetails({
        basicInfo: basicInfo || null,
        storageInfo: storageInfo || null,
      });
    } catch (e) {
      setDetailsError(e);
    } finally {
      setDetailsLoading(false);
    }
  }, [basicInfoAction, storageInfoAction]);

  const refreshAll = useCallback(() => {
    run();
    loadDetails();
  }, [loadDetails, run]);

  const basicInfo = details.basicInfo || data?.basic_info || {};
  const storageInfo = details.storageInfo || data?.storage_info || {};
  const serviceStatus = data?.service_status || {};

  const { overviewItems, storageItems } = useMemo(() => {
    const summary = data?.summary || {};
    const basic = basicInfo;
    const storage = storageInfo;
    const metrics = data?.metrics_summary || {};

    return {
      overviewItems: buildPlatformOverviewItems({ summary, basic, metrics }),
      storageItems: buildPlatformStorageItems({ summary, storage, metrics }),
    };
  }, [basicInfo, data, storageInfo]);

  const serviceStatusItems = useMemo(() => {
    const health = serviceStatus?.health || {};
    const ready = serviceStatus?.ready || {};
    return [
      { key: 'health', label: 'Health', value: health.status || '-' },
      { key: 'ready', label: 'Ready', value: ready.status || '-' },
      { key: 'mode', label: '模式', value: health.deployment_mode || '-' },
      { key: 'version', label: '版本', value: health.version || data?.summary?.version || '-' },
    ];
  }, [data?.summary?.version, serviceStatus]);

  useEffect(() => {
    if (!data?.metrics_summary) return;
    setTrendHistory(prev => appendMetricHistory(prev, {
      label: buildTrendLabel(),
      cpu: data.metrics_summary?.cpu_ratio,
      memory: data.metrics_summary?.mem_ratio,
      disk: data.summary?.disk_usage_percent == null
        ? data.metrics_summary?.disk_ratio
        : Number(data.summary.disk_usage_percent) / 100,
    }, TREND_WINDOW));
  }, [data]);

  useEffect(() => {
    if (!data && loading) return;
    loadDetails();
  }, [data, loadDetails, loading]);

  useEffect(() => {
    const timer = globalThis.setInterval(() => {
      refreshAll();
    }, TREND_REFRESH_MS);
    return () => globalThis.clearInterval(timer);
  }, [refreshAll]);

  const metrics = data?.metrics_summary || {};
  const hasRenderableContent = Boolean(data || details.basicInfo || details.storageInfo);
  const showBlockingSpinner = !hasRenderableContent && (loading || detailsLoading);
  const cpuTrendValue = formatNullablePercent(metrics.cpu_ratio);
  const memoryTrendValue = formatNullablePercent(metrics.mem_ratio);
  const diskTrendSource = data?.summary?.disk_usage_percent == null
    ? metrics.disk_ratio
    : Number(data.summary.disk_usage_percent) / 100;
  const diskTrendValue = formatNullablePercent(diskTrendSource);

  return (
    <div className="beacon-platform-page beacon-platform-page--compact">
      <PageHeader
        title="平台信息"
        icon={<CloudServerOutlined />}
        description="平台运行信息总览"
        extra={
          <div className="beacon-platform-toolbar">
            <div className="beacon-platform-toolbar__group">
              <Button icon={<ReloadOutlined />} onClick={refreshAll}>
                刷新
              </Button>
            </div>
            <div className="beacon-platform-toolbar__group beacon-platform-toolbar__group--danger">
              <Button
                danger
                icon={<PoweroffOutlined />}
                onClick={() => confirmSoftwareRestart(restartSoftwareAction, message)}
              >
                重启软件
              </Button>
              <Button
                type="primary"
                danger
                icon={<PoweroffOutlined />}
                onClick={() => confirmSystemRestart(restartSystemAction, message)}
              >
                重启系统
              </Button>
            </div>
          </div>
        }
      />

      {error || detailsError ? (
        <Alert
          type="error"
          message={error?.message || detailsError?.message || '加载失败'}
          style={{ marginBottom: 16 }}
          showIcon
        />
      ) : null}

      <Spin spinning={showBlockingSpinner}>
        <Card
          className="beacon-panel-card beacon-panel-card--tone-blue beacon-platform-metrics-shell"
          size="small"
          title={<PanelTitle title="资源指标" meta="CPU / 内存 / 磁盘采样" icon={<AreaChartOutlined />} tone="blue" />}
          extra={(
            <div className="beacon-platform-metrics-shell__meta">
              <span className="beacon-platform-metrics-shell__meta-dot" />
              <Text type="secondary" style={{ fontSize: 12 }}>最近 12 次采样，后台每 8 秒更新</Text>
            </div>
          )}
          style={{ marginBottom: 16 }}
        >
          <Row gutter={[12, 12]} className="beacon-trend-grid beacon-platform-metrics-grid">
            <Col xs={24} md={8} className="beacon-trend-grid__col beacon-platform-metric">
              <MetricTrendCard title="CPU 负载" value={cpuTrendValue} history={trendHistory} dataKey="cpu" color="#2563eb" />
            </Col>
            <Col xs={24} md={8} className="beacon-trend-grid__col beacon-platform-metric">
              <MetricTrendCard title="内存使用" value={memoryTrendValue} history={trendHistory} dataKey="memory" color="#13c2c2" />
            </Col>
            <Col xs={24} md={8} className="beacon-trend-grid__col beacon-platform-metric">
              <MetricTrendCard title="磁盘占用" value={diskTrendValue} history={trendHistory} dataKey="disk" color="#fa8c16" />
            </Col>
          </Row>
        </Card>

        <div
          className="beacon-support-grid beacon-equal-height-grid beacon-platform-workspace"
          data-testid="platform-summary-grid"
        >
          <SummaryCard
            className="beacon-platform-workspace__card beacon-platform-info-card"
            title="平台概览"
            meta="节点 / 版本 / 运行态"
            icon={<CloudServerOutlined />}
            tone="blue"
            items={overviewItems}
            bodyStyle={{ padding: '16px 18px' }}
          />
          <SummaryCard
            className="beacon-platform-workspace__card beacon-platform-storage-card"
            title="存储与指标"
            meta="目录 / 配额 / 指标"
            icon={<HddOutlined />}
            tone="cyan"
            items={storageItems}
            bodyStyle={{ padding: '16px 18px' }}
          />
          {data?.service_status ? (
            <Card
              className="beacon-panel-card beacon-panel-card--tone-slate beacon-json-card beacon-platform-workspace__card beacon-platform-service-card"
              size="small"
              title={<PanelTitle title="服务状态" meta="健康探针 / 原始返回" icon={<RadarChartOutlined />} tone="slate" />}
              styles={{ body: { padding: '16px 18px' } }}
            >
              <Space direction="vertical" style={{ width: '100%' }} size={10}>
                <div className="beacon-platform-service-card__summary">
                  {serviceStatusItems.map((item) => (
                    <div className="beacon-platform-service-card__summary-item" key={item.key}>
                      <span className="beacon-platform-service-card__summary-label">{item.label}</span>
                      <span className="beacon-platform-service-card__summary-value">{item.value}</span>
                    </div>
                  ))}
                </div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  服务状态与健康检查数据来自内部接口，仅供运维参考。
                </Text>
                <div className="beacon-platform-service-card__pre-shell">
                  <pre className="beacon-json-card__pre">
                    {JSON.stringify(data.service_status, null, 2)}
                  </pre>
                </div>
              </Space>
            </Card>
          ) : null}
        </div>
      </Spin>
    </div>
  );
}

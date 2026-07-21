import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Alert, Card, Table } from 'antd';
import {
  AlertOutlined,
  ApiOutlined,
  ApartmentOutlined,
  DeploymentUnitOutlined,
  DesktopOutlined,
  ExperimentOutlined,
  HddOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import { Cell, Pie, PieChart } from 'recharts';
import PageHeader from '../../components/PageHeader';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import SkeletonPage from '../../components/Skeleton';
import { PanelTitle, SummaryList } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import {
  appendMetricHistory,
  buildSparklineGeometry,
  buildTrendLabel,
  getTrendDelta,
} from '../../utils/trends';
import './DashboardPage.css';

const TREND_REFRESH_MS = 8000;
const TREND_WINDOW = 12;

const DONUT_COLORS = ['#22c55e', '#f59e0b', '#ef4444'];
const displayValueProp = PropTypes.oneOfType([PropTypes.string, PropTypes.number, PropTypes.node]);
const numericValueProp = PropTypes.oneOfType([PropTypes.string, PropTypes.number]);
const trendHistoryPointShape = PropTypes.shape({
  label: PropTypes.node,
  cpu: PropTypes.number,
  memory: PropTypes.number,
  disk: PropTypes.number,
});
const networkSnapshotShape = PropTypes.shape({
  upload: numericValueProp,
  upload_mbps: numericValueProp,
  download: numericValueProp,
  download_mbps: numericValueProp,
  series: PropTypes.arrayOf(PropTypes.shape({
    upload: numericValueProp,
    download: numericValueProp,
  })),
});
const legendItemShape = PropTypes.shape({
  label: PropTypes.node.isRequired,
  value: PropTypes.number.isRequired,
  color: PropTypes.string.isRequired,
});
const dashboardTotalsShape = PropTypes.shape({
  online_device_count: PropTypes.number,
  device_count: PropTypes.number,
  stream_count: PropTypes.number,
  offline_device_count: PropTypes.number,
  alarm_device_count: PropTypes.number,
});
const alarmSummaryShape = PropTypes.shape({
  total: PropTypes.number,
  critical: PropTypes.number,
  warning: PropTypes.number,
  info: PropTypes.number,
  history: PropTypes.arrayOf(PropTypes.number),
});

function toLooseNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;
  const matched = /-?\d+(\.\d+)?/.exec(value);
  if (!matched) return null;
  const parsed = Number(matched[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatMetaValue(value, fallback = '0') {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function resolveStatusTone(label) {
  const value = String(label || '').toLowerCase();
  if (value.includes('运行') || value.includes('正常') || value.includes('online')) return 'success';
  if (value.includes('停止') || value.includes('离线') || value.includes('offline')) return 'neutral';
  if (value.includes('异常') || value.includes('告警') || value.includes('error')) return 'danger';
  return 'warning';
}

function StatusChip({ label }) {
  const tone = resolveStatusTone(label);
  return <span className={`beacon-status-chip beacon-status-chip--${tone}`}>{label || '-'}</span>;
}

StatusChip.propTypes = {
  label: PropTypes.node,
};

function formatDisplayValue(value, fallback = '-') {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function MetricTile({ title, value, history, dataKey, color }) {
  const delta = getTrendDelta(history, dataKey);
  const geometry = buildSparklineGeometry(history, dataKey, { width: 220, height: 64, paddingX: 4, paddingY: 8 });
  const deltaPrefix = delta >= 0 ? '+' : '';
  const deltaText = delta === null ? '采样中' : `较首笔 ${deltaPrefix}${(delta * 100).toFixed(1)}%`;

  return (
    <div className="beacon-dashboard-metric-tile">
      <div className="beacon-dashboard-metric-tile__head">
        <span className="beacon-dashboard-metric-tile__label">{title}</span>
        <span className="beacon-dashboard-metric-tile__delta">
          {deltaText}
        </span>
      </div>
      <div className="beacon-dashboard-metric-tile__value">{value || '-'}</div>
      <div className="beacon-dashboard-metric-tile__spark">
        <svg viewBox="0 0 220 64" width="100%" height="64" aria-hidden="true" focusable="false">
          {geometry.areaPoints ? <polygon points={geometry.areaPoints} fill={color} fillOpacity="0.12" /> : null}
          {geometry.linePoints ? (
            <polyline
              points={geometry.linePoints}
              fill="none"
              stroke={color}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : null}
          {geometry.lastPoint ? <circle cx={geometry.lastPoint.x} cy={geometry.lastPoint.y} r="3.5" fill={color} /> : null}
        </svg>
      </div>
    </div>
  );
}

MetricTile.propTypes = {
  title: PropTypes.string.isRequired,
  value: displayValueProp,
  history: PropTypes.arrayOf(trendHistoryPointShape).isRequired,
  dataKey: PropTypes.string.isRequired,
  color: PropTypes.string.isRequired,
};

function buildNetworkBars(history, network) {
  const uploadValue = toLooseNumber(network?.upload) ?? toLooseNumber(network?.upload_mbps);
  const downloadValue = toLooseNumber(network?.download) ?? toLooseNumber(network?.download_mbps);
  const source = Array.isArray(network?.series)
    ? network.series
      .map((item) => ({
        upload: toLooseNumber(item?.upload),
        download: toLooseNumber(item?.download),
      }))
      .filter((item) => item.upload !== null && item.download !== null)
    : [];

  return {
    uploadValue,
    downloadValue,
    source,
    hasSnapshot: uploadValue !== null || downloadValue !== null,
  };
}

function NetworkTile({ history, network }) {
  const { uploadValue, downloadValue, source, hasSnapshot } = buildNetworkBars(history, network);
  const hasSeries = source.length > 0;
  const maxValue = hasSeries ? Math.max(...source.map((item) => Math.max(item.upload, item.download)), 1) : 1;
  const uploadFallback = uploadValue === null ? '-' : `${uploadValue.toFixed(1)} Mbps`;
  const downloadFallback = downloadValue === null ? '-' : `${downloadValue.toFixed(1)} Mbps`;

  return (
    <div className="beacon-dashboard-metric-tile beacon-dashboard-metric-tile--network">
      <div className="beacon-dashboard-metric-tile__head">
        <span className="beacon-dashboard-metric-tile__label">网络流量</span>
        {hasSnapshot ? (
          <div className="beacon-dashboard-network-legend">
            <span className="beacon-dashboard-network-legend__item">
              <i style={{ background: '#8b5cf6' }} />
              上行 {formatDisplayValue(network?.upload ?? uploadFallback)}
            </span>
            <span className="beacon-dashboard-network-legend__item">
              <i style={{ background: '#2563eb' }} />
              下行 {formatDisplayValue(network?.download ?? downloadFallback)}
            </span>
          </div>
        ) : (
          <span className="beacon-dashboard-network-empty">暂无网络数据</span>
        )}
      </div>

      {hasSeries ? (
        <div className="beacon-dashboard-network-bars">
          {source.map((item, index) => (
            <div className="beacon-dashboard-network-bars__item" key={`${item.upload}-${item.download}-${index}`}>
              <span
                className="beacon-dashboard-network-bars__bar beacon-dashboard-network-bars__bar--upload"
                style={{ height: `${(item.upload / maxValue) * 100}%` }}
              />
              <span
                className="beacon-dashboard-network-bars__bar beacon-dashboard-network-bars__bar--download"
                style={{ height: `${(item.download / maxValue) * 100}%` }}
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="beacon-dashboard-network-placeholder">
          <span>{hasSnapshot ? '暂无趋势数据' : '等待网络指标接入'}</span>
        </div>
      )}
    </div>
  );
}

NetworkTile.propTypes = {
  history: PropTypes.arrayOf(trendHistoryPointShape).isRequired,
  network: networkSnapshotShape,
};

function DonutSummaryCard({ title, meta, icon, total, caption, legendItems }) {
  const chartData = legendItems.some((item) => item.value > 0)
    ? legendItems
    : [{ label: '暂无数据', value: 1, color: '#e2e8f0' }];

  return (
    <Card
      className="beacon-panel-card beacon-dashboard-side-card beacon-dashboard-side-card--metric"
      size="small"
      title={<PanelTitle title={title} icon={icon} tone="green" />}
      styles={{ body: { padding: '16px 18px' } }}
    >
      <div className="beacon-dashboard-donut-card">
        <div className="beacon-dashboard-donut-card__chart">
          <PieChart width={148} height={148}>
            <Pie
              data={chartData}
              dataKey="value"
              innerRadius={38}
              outerRadius={58}
              stroke="none"
              paddingAngle={chartData.length > 1 ? 2 : 0}
            >
              {chartData.map((entry) => (
                <Cell key={entry.label} fill={entry.color} />
              ))}
            </Pie>
          </PieChart>
          <div className="beacon-dashboard-donut-card__center">
            <strong>{total}</strong>
            <span>{caption}</span>
          </div>
        </div>

        <div className="beacon-dashboard-donut-card__content">
          <div className="beacon-dashboard-donut-card__summary">{meta}</div>

          <div className="beacon-dashboard-donut-card__legend">
          {legendItems.map((item) => (
            <div className="beacon-dashboard-donut-card__legend-item" key={item.label}>
              <span className="beacon-dashboard-donut-card__legend-dot" style={{ background: item.color }} />
              <span className="beacon-dashboard-donut-card__legend-label">{item.label}</span>
              <strong className="beacon-dashboard-donut-card__legend-value">{item.value}</strong>
            </div>
          ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

DonutSummaryCard.propTypes = {
  title: PropTypes.string.isRequired,
  meta: PropTypes.node.isRequired,
  icon: PropTypes.node,
  total: PropTypes.number.isRequired,
  caption: PropTypes.string.isRequired,
  legendItems: PropTypes.arrayOf(legendItemShape).isRequired,
};

function DeviceStatusCard({ totals }) {
  const items = [
    { label: '在线设备', value: totals.online_device_count ?? totals.device_count ?? totals.stream_count ?? 0, color: '#22c55e' },
    { label: '离线设备', value: totals.offline_device_count ?? 0, color: '#94a3b8' },
    { label: '告警设备', value: totals.alarm_device_count ?? 0, color: '#f97316' },
  ];

  return (
    <Card
      className="beacon-panel-card beacon-dashboard-side-card beacon-dashboard-side-card--metric"
      size="small"
      title={<PanelTitle title="设备状态" icon={<HddOutlined />} tone="blue" />}
      styles={{ body: { padding: '16px 18px' } }}
    >
      <div className="beacon-dashboard-device-status">
        {items.map((item) => (
          <div className="beacon-dashboard-device-status__item" key={item.label}>
            <span className="beacon-dashboard-device-status__icon" style={{ color: item.color, borderColor: `${item.color}33`, background: `${item.color}14` }}>
              <span className="beacon-dashboard-device-status__dot" style={{ background: item.color }} />
            </span>
            <span className="beacon-dashboard-device-status__label">{item.label}</span>
            <strong className="beacon-dashboard-device-status__value">{item.value}</strong>
          </div>
        ))}
      </div>
    </Card>
  );
}

DeviceStatusCard.propTypes = {
  totals: dashboardTotalsShape.isRequired,
};

function buildTaskRows(data, runtime, assets) {
  if (Array.isArray(data.task_rows) && data.task_rows.length) return data.task_rows;

  const rows = Array.isArray(runtime.processes?.rows) ? runtime.processes.rows : [];
  return rows.map((row, index) => ({
    id: `proc-${String(index + 1).padStart(3, '0')}`,
    name: runtime.analyzer?.engine_name || '分析服务',
    status: row.ok ? '运行中' : '异常',
    node: row.analyzer_host || runtime.host || '-',
    model: formatDisplayValue(row.scheduler?.loadedAlgorithms ?? assets.algorithm_count, '-'),
    runtime: runtime.uptime || '-',
  }));
}

function buildNodeRows(data, runtime) {
  if (Array.isArray(data.node_rows) && data.node_rows.length) return data.node_rows;

  const rows = Array.isArray(runtime.processes?.rows) ? runtime.processes.rows : [];
  if (rows.length) {
    return rows.map((row, index) => ({
      id: row.analyzer_host || `node-${String(index + 1).padStart(3, '0')}`,
      address: `http://127.0.0.1:${runtime.analyzer?.port || 9993}`,
      status: row.ok ? '正常' : '异常',
      cpu: row.resource?.cpuUsageText || '0.0%',
      memory: row.resource?.memoryUsageText || '0.0%',
      disk: row.resource?.diskUsageText || '0.0%',
    }));
  }

  return [
    {
      id: runtime.host || 'node-local',
      address: `http://127.0.0.1:${runtime.analyzer?.port || 9993}`,
      status: runtime.analyzer?.ok ? '正常' : '异常',
      cpu: runtime.cpu?.usage || '-',
      memory: runtime.memory?.usage || '-',
      disk: runtime.disk?.usage || '-',
    },
  ];
}

function buildAlarmSummary(data, totals) {
  const total = totals.open_alarm_count ?? 0;
  const summary = data.alarm_summary || {};
  const history = Array.isArray(summary.history) && summary.history.length
    ? summary.history
    : [total, Math.max(total - 1, 0), total, Math.max(total - 1, 0), total, total, Math.max(total - 1, 0), total];

  return {
    total: summary.total ?? total,
    critical: summary.critical ?? 0,
    warning: summary.warning ?? 0,
    info: summary.info ?? total,
    history,
  };
}

function AlarmOverviewCard({ summary }) {
  const series = summary.history.map((value, index) => ({ label: `${index}`, count: value }));
  const geometry = buildSparklineGeometry(series, 'count', { width: 420, height: 82, paddingX: 6, paddingY: 10 });

  return (
    <Card
      className="beacon-panel-card beacon-dashboard-alarm-card"
      size="small"
      title={<PanelTitle title="告警概览" meta="近 7 天告警统计" icon={<AlertOutlined />} tone="blue" />}
      styles={{ body: { padding: '16px 18px' } }}
    >
      <div className="beacon-dashboard-alarm-card__body">
        <div className="beacon-dashboard-alarm-card__stats">
          <div className="beacon-dashboard-alarm-card__stat">
            <span>告警总数</span>
            <strong>{summary.total}</strong>
          </div>
          <div className="beacon-dashboard-alarm-card__stat beacon-dashboard-alarm-card__stat--danger">
            <span>严重</span>
            <strong>{summary.critical}</strong>
          </div>
          <div className="beacon-dashboard-alarm-card__stat beacon-dashboard-alarm-card__stat--warning">
            <span>警告</span>
            <strong>{summary.warning}</strong>
          </div>
          <div className="beacon-dashboard-alarm-card__stat beacon-dashboard-alarm-card__stat--info">
            <span>普通</span>
            <strong>{summary.info}</strong>
          </div>
        </div>

        <div className="beacon-dashboard-alarm-card__chart">
          <svg viewBox="0 0 420 82" width="100%" height="82" aria-hidden="true" focusable="false">
            <line x1="0" y1="62" x2="420" y2="62" stroke="#dbe7f4" strokeDasharray="5 5" />
            {geometry.areaPoints ? <polygon points={geometry.areaPoints} fill="#3b82f6" fillOpacity="0.08" /> : null}
            {geometry.linePoints ? (
              <polyline
                points={geometry.linePoints}
                fill="none"
                stroke="#2563eb"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
            {geometry.lastPoint ? <circle cx={geometry.lastPoint.x} cy={geometry.lastPoint.y} r="3.5" fill="#2563eb" /> : null}
          </svg>
        </div>
      </div>
    </Card>
  );
}

AlarmOverviewCard.propTypes = {
  summary: alarmSummaryShape.isRequired,
};

export default function DashboardPage() {
  const { data, loading, error, run } = useApi(API.dashboard);
  const [trendHistory, setTrendHistory] = useState([]);

  useEffect(() => {
    if (!data?.runtime) return;
    setTrendHistory((prev) => appendMetricHistory(prev, {
      label: buildTrendLabel(),
      cpu: data.runtime?.cpu?.usage_rate,
      memory: data.runtime?.memory?.usage_rate,
      disk: data.runtime?.disk?.usage_rate,
    }, TREND_WINDOW));
  }, [data]);

  useEffect(() => {
    const timer = globalThis.setInterval(() => {
      run();
    }, TREND_REFRESH_MS);
    return () => globalThis.clearInterval(timer);
  }, [run]);

  if (loading && !data) {
    return <SkeletonPage kpiCount={5} />;
  }

  if (error && !data) {
    return <Alert type="warning" message={error.message || '无法加载总览数据'} />;
  }

  if (!data) {
    return <Alert type="warning" message="无法加载总览数据" />;
  }

  const totals = data.dashboard_totals || {};
  const runtime = data.runtime || {};
  const analyzer = runtime.analyzer || {};
  const assets = data.platform?.assets || {};
  const taskRows = buildTaskRows(data, runtime, assets);
  const nodeRows = buildNodeRows(data, runtime);
  const alarmSummary = buildAlarmSummary(data, totals);

  const kpiCards = [
    {
      title: '总设备数',
      value: totals.device_count ?? totals.stream_count ?? totals.site_count ?? 0,
      icon: <DesktopOutlined />,
      color: '#2563eb',
      metaItems: [
        { label: '在线', value: formatMetaValue(totals.online_device_count ?? totals.device_count ?? totals.stream_count ?? 0) },
        { label: '离线', value: formatMetaValue(totals.offline_device_count ?? 0) },
      ],
    },
    {
      title: '在线节点',
      value: totals.online_node_count ?? totals.node_count ?? runtime.processes?.process_num ?? 0,
      icon: <ApartmentOutlined />,
      color: '#14b8a6',
      metaItems: [
        { label: '正常', value: formatMetaValue(totals.online_node_count ?? runtime.processes?.process_num ?? 0) },
        { label: '异常', value: formatMetaValue(totals.abnormal_node_count ?? 0) },
      ],
    },
    {
      title: '推理任务',
      value: totals.active_control_count ?? assets.active_control_count ?? taskRows.length,
      icon: <DeploymentUnitOutlined />,
      color: '#f97316',
      metaItems: [
        { label: '运行中', value: formatMetaValue(totals.active_control_count ?? assets.active_control_count ?? taskRows.length) },
        { label: '已停止', value: formatMetaValue(totals.stopped_task_count ?? 0) },
      ],
    },
    {
      title: '分析服务',
      value: totals.service_count ?? (analyzer.ok ? 1 : 0),
      icon: <ApiOutlined />,
      color: '#22c55e',
      metaItems: [
        { label: '运行中', value: formatMetaValue(totals.service_count ?? (analyzer.ok ? 1 : 0)) },
        { label: '异常', value: formatMetaValue(analyzer.ok ? 0 : 1) },
      ],
    },
    {
      title: '模型数量',
      value: totals.model_count ?? assets.algorithm_count ?? 0,
      icon: <ExperimentOutlined />,
      color: '#a855f7',
      metaItems: [
        { label: '已部署', value: formatMetaValue(totals.model_count ?? assets.algorithm_count ?? 0) },
        { label: '未部署', value: formatMetaValue(totals.pending_model_count ?? 0) },
      ],
    },
  ];

  const systemInfoItems = [
    { label: '主机名', value: runtime.host || '-' },
    { label: '系统', value: runtime.os_release || runtime.system_name || '-' },
    { label: '节点', value: totals.node_count ?? runtime.processes?.process_num ?? '-' },
    { label: '运行时长', value: runtime.uptime || '-' },
    { label: 'CPU', value: runtime.cpu?.usage || '-' },
    { label: '内存', value: runtime.memory?.usage || '-' },
    { label: '磁盘', value: runtime.disk?.usage || '-' },
    { label: '内核', value: runtime.kernel || '-' },
    { label: '容器运行时', value: runtime.container_runtime || '-' },
  ];

  const serviceInfoItems = [
    { label: '服务名称', value: analyzer.engine_name || '分析引擎' },
    { label: '状态', value: <StatusChip label={analyzer.health_label || (analyzer.ok ? '正常' : '异常')} /> },
    { label: '实例数', value: totals.service_count ?? (analyzer.ok ? 1 : 0) },
    { label: '通信协议', value: analyzer.protocol || 'ONNX' },
    { label: '引擎', value: analyzer.backend || analyzer.devices?.openvino_devices?.[0] || '-' },
    { label: '端口', value: analyzer.port || '-' },
    { label: '健康检查', value: <StatusChip label={analyzer.ok ? '正常' : '异常'} /> },
    { label: '更新时间', value: analyzer.updated_at || '-' },
  ];

  const taskLegend = [
    { label: '运行中', value: totals.active_control_count ?? assets.active_control_count ?? taskRows.length, color: DONUT_COLORS[0] },
    { label: '已停止', value: totals.stopped_task_count ?? 0, color: DONUT_COLORS[1] },
    { label: '异常', value: totals.abnormal_task_count ?? 0, color: DONUT_COLORS[2] },
  ];

  const taskColumns = [
    { title: '任务ID', dataIndex: 'id', width: 110 },
    { title: '任务名称', dataIndex: 'name', width: 140 },
    { title: '状态', dataIndex: 'status', width: 120, render: (value) => <StatusChip label={value} /> },
    { title: '节点', dataIndex: 'node', width: 110 },
    { title: '模型', dataIndex: 'model' },
    { title: '运行时长', dataIndex: 'runtime', width: 110 },
  ];

  const nodeColumns = [
    { title: '节点ID', dataIndex: 'id', width: 110 },
    { title: '地址', dataIndex: 'address', width: 220 },
    { title: '状态', dataIndex: 'status', width: 100, render: (value) => <StatusChip label={value} /> },
    { title: 'CPU', dataIndex: 'cpu', width: 90 },
    { title: '内存', dataIndex: 'memory', width: 90 },
    { title: '磁盘', dataIndex: 'disk', width: 90 },
  ];

  return (
    <div className="beacon-dashboard-v2">
      <PageHeader title="系统总览" icon={<DesktopOutlined />} description="欢迎回来，系统运行状态一览" />

      <KpiCardGroup>
        {kpiCards.map((card) => (
          <KpiCard
            key={card.title}
            title={card.title}
            value={card.value}
            icon={card.icon}
            color={card.color}
            metaItems={card.metaItems}
          />
        ))}
      </KpiCardGroup>

      <div className="beacon-dashboard-grid">
        <div className="beacon-dashboard-grid__main">
          <Card
            className="beacon-panel-card beacon-dashboard-overview-card"
            size="small"
            title={<PanelTitle title="系统概览" meta="把控设备、节点、任务与告警全局运行状态" icon={<DesktopOutlined />} tone="blue" />}
            styles={{ body: { padding: '18px' } }}
          >
            <div className="beacon-dashboard-overview-facts">
              <div className="beacon-dashboard-overview-fact">
                <span className="beacon-dashboard-overview-fact__label">主机</span>
                <strong className="beacon-dashboard-overview-fact__value">{runtime.host || '-'}</strong>
                <span className="beacon-dashboard-overview-fact__meta">{runtime.os_release || '系统信息待上报'}</span>
              </div>
              <div className="beacon-dashboard-overview-fact">
                <span className="beacon-dashboard-overview-fact__label">节点类型</span>
                <strong className="beacon-dashboard-overview-fact__value">{runtime.node_type || runtime.system_name || '-'}</strong>
                <span className="beacon-dashboard-overview-fact__meta">{formatMetaValue(totals.online_node_count ?? runtime.processes?.process_num ?? 0)} 台在线</span>
              </div>
              <div className="beacon-dashboard-overview-fact">
                <span className="beacon-dashboard-overview-fact__label">运行时长</span>
                <strong className="beacon-dashboard-overview-fact__value">{runtime.uptime || '-'}</strong>
                <span className="beacon-dashboard-overview-fact__meta">{runtime.started_at ? `自 ${runtime.started_at} 启动` : '持续运行中'}</span>
              </div>
              <div className="beacon-dashboard-overview-fact">
                <span className="beacon-dashboard-overview-fact__label">硬件平台</span>
                <strong className="beacon-dashboard-overview-fact__value">{runtime.hardware_label || '标准算力节点'}</strong>
                <span className="beacon-dashboard-overview-fact__meta">{runtime.cpu?.model || '硬件信息待上报'}</span>
              </div>
            </div>

            <div className="beacon-dashboard-overview-metrics">
              <MetricTile title="CPU 使用率" value={runtime.cpu?.usage || '-'} history={trendHistory} dataKey="cpu" color="#2563eb" />
              <MetricTile title="内存使用率" value={runtime.memory?.usage || '-'} history={trendHistory} dataKey="memory" color="#14b8a6" />
              <MetricTile title="磁盘使用率" value={runtime.disk?.usage || '-'} history={trendHistory} dataKey="disk" color="#f97316" />
              <NetworkTile history={trendHistory} network={runtime.network} />
            </div>
          </Card>

          <div className="beacon-dashboard-table-grid">
            <Card
              className="beacon-panel-card beacon-dashboard-table-card"
              size="small"
              title={<PanelTitle title="任务列表" meta="查看与管理推理任务" icon={<DeploymentUnitOutlined />} tone="orange" />}
              styles={{ body: { padding: 0 } }}
            >
              <Table
                columns={taskColumns}
                dataSource={taskRows}
                rowKey={(record) => record.id}
                pagination={false}
                size="small"
              />
            </Card>

            <Card
              className="beacon-panel-card beacon-dashboard-table-card"
              size="small"
              title={<PanelTitle title="节点信息" meta="在线节点与资源概览" icon={<ApartmentOutlined />} tone="blue" />}
              styles={{ body: { padding: 0 } }}
            >
              <Table
                columns={nodeColumns}
                dataSource={nodeRows}
                rowKey={(record) => record.id}
                pagination={false}
                size="small"
              />
            </Card>
          </div>

          <AlarmOverviewCard summary={alarmSummary} />
        </div>

        <div className="beacon-dashboard-grid__side">
          <div className="beacon-dashboard-side-grid">
            <Card
              className="beacon-panel-card beacon-dashboard-side-card beacon-dashboard-side-card--list"
              size="small"
              title={<PanelTitle title="系统信息" icon={<InfoCircleOutlined />} tone="blue" />}
              styles={{ body: { padding: '12px 16px' } }}
            >
              <SummaryList items={systemInfoItems} />
            </Card>

            <Card
              className="beacon-panel-card beacon-dashboard-side-card beacon-dashboard-side-card--list"
              size="small"
              title={<PanelTitle title="分析服务" icon={<ApiOutlined />} tone="green" />}
              extra={<StatusChip label={analyzer.health_label || (analyzer.ok ? '正常' : '异常')} />}
              styles={{ body: { padding: '12px 16px' } }}
            >
              <SummaryList items={serviceInfoItems} />
            </Card>

            <DonutSummaryCard
              title="推理任务统计"
              meta={`共 ${taskLegend.reduce((sum, item) => sum + item.value, 0)} 个任务`}
              icon={<DeploymentUnitOutlined />}
              total={taskLegend.reduce((sum, item) => sum + item.value, 0)}
              caption="任务"
              legendItems={taskLegend}
            />

            <DeviceStatusCard totals={totals} />
          </div>
        </div>
      </div>
    </div>
  );
}

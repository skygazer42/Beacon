import React, { useState } from 'react';
import { Alert, Button, Card, Progress, Tabs } from 'antd';
import { DeploymentUnitOutlined, FileTextOutlined, ReloadOutlined, ToolOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import SkeletonPage from '../../components/Skeleton';
import useDigitalHumanResource from './useDigitalHumanResource';
import {
  getDigitalHumanOpsAiInsight,
  getDigitalHumanOpsReport,
} from './dataAdapter';
import './digitalHumanStyles.css';

const RANGE_LABELS = {
  today: '今日',
  '7days': '近 7 天',
  '30days': '近 30 天',
};

function toTrendPercent(value, maxValue) {
  if (!maxValue) return 0;
  return Math.max(8, Math.round((value / maxValue) * 100));
}

function insightStatusLabel(insight, loading) {
  if (loading && !insight?.text) return '生成中';
  if (insight?.status === 'success') return '已生成';
  if (insight?.status === 'failed') return '失败';
  return '未启用';
}

function insightDisplayText(insight, loading) {
  if (loading && !insight?.text) {
    return 'AI 正在分析当前运维报表...';
  }
  if (insight?.status === 'failed') {
    return insight?.error
      ? `AI 分析生成失败：${insight.error}`
      : 'AI 分析生成失败，请稍后重试。';
  }
  if (insight?.status === 'skipped') {
    return 'AI 分析未启用或配置不完整，请先检查系统设置中的 AI 配置。';
  }
  return insight?.text || '暂无智能洞察内容';
}

export default function DigitalHumanOpsReportPage() {
  const [rangeKey, setRangeKey] = useState('7days');

  const reportResource = useDigitalHumanResource(() => getDigitalHumanOpsReport(rangeKey), [rangeKey]);
  const insightResource = useDigitalHumanResource(() => getDigitalHumanOpsAiInsight(rangeKey), [rangeKey]);

  const {
    data: reportData,
    loading,
    error,
    reload,
  } = reportResource;
  const {
    data: insightData,
    loading: insightLoading,
    error: insightError,
    reload: reloadInsight,
  } = insightResource;
  if (loading && !reportData) {
    return <SkeletonPage kpiCount={5} />;
  }

  if (error && !reportData) {
    return <Alert type="warning" showIcon message={error.message || '数字人运维报告加载失败'} />;
  }

  const trendRows = reportData?.trendRows || [];
  const moduleDistribution = reportData?.moduleDistribution || [];
  const maxAlertValue = Math.max(1, ...trendRows.map((row) => row.alerts || 0));
  const maxRepairValue = Math.max(1, ...trendRows.map((row) => row.repairs || 0));
  const maxDistributionValue = Math.max(1, ...moduleDistribution.map((item) => item.value || 0));
  const focusDevices = reportData?.focusDevices || [];

  const focusColumns = [
    {
      title: '重点设备',
      width: 220,
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{record.deviceName}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.deviceCode} · {record.region}</div>
        </div>
      ),
    },
    {
      title: '风险模块',
      dataIndex: 'primaryModule',
      width: 140,
    },
    {
      title: '待处理数',
      dataIndex: 'faultCount',
      width: 100,
    },
    {
      title: '当前 SLA',
      width: 180,
      render: (_, record) => (
        <div>
          <Progress percent={Math.round(record.sla)} size="small" showInfo={false} strokeColor={record.sla < 80 ? '#ef4444' : '#2563eb'} />
          <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>{record.sla}%</div>
        </div>
      ),
    },
  ];

  return (
    <div className="beacon-dh-page">
      <PageHeader
        title="数字人运维报告"
        icon={<ToolOutlined />}
        description="按时间窗口复盘数字人终端稳定性、问题模块分布与重点设备处置优先级。"
        extra={(
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              reload();
              reloadInsight();
            }}
          >
            刷新
          </Button>
        )}
      />

      <Tabs
        activeKey={rangeKey}
        onChange={setRangeKey}
        items={[
          { key: 'today', label: '今日' },
          { key: '7days', label: '近 7 天' },
          { key: '30days', label: '近 30 天' },
        ]}
      />

      <KpiCardGroup>
        <KpiCard title="全局 SLA" value={reportData?.kpis?.globalSla} suffix="%" color="#2563eb" icon={<DeploymentUnitOutlined />} />
        <KpiCard title="平均恢复时长" value={reportData?.kpis?.mttrMinutes} suffix="分钟" color="#16a34a" icon={<ToolOutlined />} />
        <KpiCard title="告警总量" value={reportData?.kpis?.alertCount} suffix="条" color="#f97316" icon={<FileTextOutlined />} />
        <KpiCard title="自动闭环率" value={reportData?.kpis?.autoRepairRate} suffix="%" color="#7c3aed" icon={<DeploymentUnitOutlined />} />
        <KpiCard title="平均 LLM 延时" value={reportData?.kpis?.avgLlmLatency} suffix="ms" color="#ef4444" icon={<DeploymentUnitOutlined />} />
      </KpiCardGroup>

      <div className="beacon-dh-grid beacon-dh-grid--two">
        <Card
          className="beacon-panel-card beacon-panel-card--tone-blue"
          size="small"
          title={<PanelTitle title="趋势复盘" meta={RANGE_LABELS[rangeKey]} icon={<DeploymentUnitOutlined />} tone="blue" />}
        >
          <div className="beacon-dh-bar-list">
            {trendRows.map((row) => (
              <div className="beacon-dh-bar-row" key={row.label}>
                <div className="beacon-dh-bar-row__label">{row.label}</div>
                <div className="beacon-dh-bar-row__metric">
                  <div className="beacon-dh-bar-row__metric-head">
                    <span>告警数</span>
                    <strong>{row.alerts}</strong>
                  </div>
                  <Progress percent={toTrendPercent(row.alerts, maxAlertValue)} size="small" showInfo={false} strokeColor="#f97316" />
                </div>
                <div className="beacon-dh-bar-row__metric">
                  <div className="beacon-dh-bar-row__metric-head">
                    <span>修复数</span>
                    <strong>{row.repairs}</strong>
                  </div>
                  <Progress percent={toTrendPercent(row.repairs, maxRepairValue)} size="small" showInfo={false} strokeColor="#16a34a" />
                </div>
                <div className="beacon-dh-bar-row__metric">
                  <div className="beacon-dh-bar-row__metric-head">
                    <span>在线率</span>
                    <strong>{row.onlineRate}%</strong>
                  </div>
                  <Progress percent={Math.round(row.onlineRate)} size="small" showInfo={false} strokeColor="#2563eb" />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <SummaryCard
          title="智能洞察"
          meta={`统计周期 · ${RANGE_LABELS[rangeKey]}`}
          icon={<FileTextOutlined />}
          tone="orange"
          items={[
            { label: '生成时间', value: reportData?.generatedAt || '--' },
            { label: '重点设备', value: `${focusDevices.length} 台` },
            { label: 'AI 状态', value: insightStatusLabel(insightData, insightLoading) },
          ]}
        >
          {insightError ? (
            <Alert type="warning" showIcon style={{ marginTop: 12 }} message={insightError.message || '智能洞察加载失败'} />
          ) : (
            <div className="beacon-dh-ai-text" style={{ marginTop: 12 }}>
              {insightDisplayText(insightData, insightLoading)}
            </div>
          )}
        </SummaryCard>
      </div>

      <div className="beacon-dh-grid beacon-dh-grid--two">
        <Card
          className="beacon-panel-card beacon-panel-card--tone-cyan"
          size="small"
          title={<PanelTitle title="问题模块分布" meta="按告警模块聚合" icon={<ToolOutlined />} tone="cyan" />}
        >
          <div className="beacon-dh-distribution">
            {moduleDistribution.map((item) => (
              <div className="beacon-dh-distribution__row" key={item.name}>
                <span className="beacon-dh-distribution__label">{item.name}</span>
                <Progress percent={toTrendPercent(item.value, maxDistributionValue)} size="small" showInfo={false} strokeColor="#0891b2" />
                <span className="beacon-dh-distribution__value">{item.value}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-slate"
          size="small"
          title={<PanelTitle title="重点关注设备" meta="按告警数量排序" icon={<DeploymentUnitOutlined />} tone="slate" />}
          styles={{ body: { padding: 0 } }}
        >
          <ProTable
            columns={focusColumns}
            dataSource={focusDevices}
            loading={loading}
            rowKey="deviceId"
            pagination={false}
          />
        </Card>
      </div>

    </div>
  );
}

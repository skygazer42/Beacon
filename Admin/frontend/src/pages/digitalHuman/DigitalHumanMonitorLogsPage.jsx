import React, { useMemo, useState } from 'react';
import { Alert, App, Button, Card, Space, Tag } from 'antd';
import { DeploymentUnitOutlined, FileTextOutlined, ReloadOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import DetailDrawer, { DetailSection } from '../../components/DetailDrawer';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import SkeletonPage from '../../components/Skeleton';
import useDigitalHumanResource from './useDigitalHumanResource';
import {
  getDigitalHumanLogNodeStatus,
  listDigitalHumanMonitorLogs,
  reanalyzeDigitalHumanMonitorLog,
} from './dataAdapter';
import './digitalHumanStyles.css';

function levelTag(level) {
  if (level === 'ERROR') return <Tag color="error">ERROR</Tag>;
  if (level === 'WARN') return <Tag color="warning">WARN</Tag>;
  return <Tag color="processing">INFO</Tag>;
}

function diagnosisTag(status) {
  if (status === 'success') return <Tag color="success">诊断完成</Tag>;
  if (status === 'failed') return <Tag color="error">诊断失败</Tag>;
  return <Tag>已跳过</Tag>;
}

function diagnosisSummary(log) {
  if (log?.diagnosisText) {
    return log.diagnosisText;
  }
  if (log?.diagnosisStatus === 'skipped') {
    return 'AI 分析未启用、无需执行，或当前配置不完整。';
  }
  if (log?.diagnosisStatus === 'failed') {
    return log?.diagnosisError || 'AI 分析生成失败，请稍后重试。';
  }
  return '暂无诊断结果';
}

function matchesFilter(log, filters) {
  const keyword = String(filters.keyword || '').trim().toLowerCase();
  const keywordHit = !keyword
    || log.deviceName.toLowerCase().includes(keyword)
    || log.deviceId.toLowerCase().includes(keyword)
    || log.message.toLowerCase().includes(keyword)
    || log.traceId.toLowerCase().includes(keyword);
  const levelHit = !filters.level || log.level === filters.level;
  const moduleHit = !filters.module || log.module === filters.module;
  return keywordHit && levelHit && moduleHit;
}

export default function DigitalHumanMonitorLogsPage() {
  const { message } = App.useApp();
  const logsResource = useDigitalHumanResource(listDigitalHumanMonitorLogs, []);
  const nodeResource = useDigitalHumanResource(getDigitalHumanLogNodeStatus, []);
  const [filters, setFilters] = useState({});
  const [selectedLog, setSelectedLog] = useState(null);
  const [reanalyzingId, setReanalyzingId] = useState(null);

  const {
    data: logsData,
    loading,
    error,
    reload,
    setData,
  } = logsResource;
  const {
    data: nodeData,
    loading: nodeLoading,
    reload: reloadNode,
  } = nodeResource;

  const logs = logsData || [];
  const filteredLogs = useMemo(
    () => logs.filter((item) => matchesFilter(item, filters)),
    [logs, filters],
  );
  const moduleOptions = useMemo(
    () => Array.from(new Set(logs.map((item) => item.module))).map((item) => ({ label: item, value: item })),
    [logs],
  );

  if (loading && !logsData) {
    return <SkeletonPage kpiCount={4} />;
  }

  if (error && !logsData) {
    return <Alert type="warning" showIcon message={error.message || '数字人监管日志加载失败'} />;
  }

  async function handleReanalyze(logId) {
    setReanalyzingId(logId);
    try {
      const nextPatch = await reanalyzeDigitalHumanMonitorLog(logId);
      setData((prev) => prev.map((item) => (item.id === logId ? { ...item, ...nextPatch } : item)));
      if (selectedLog?.id === logId) {
        setSelectedLog((prev) => (prev ? { ...prev, ...nextPatch } : prev));
      }
      message.success('AI 诊断已重新生成');
    } catch (reanalyzeError) {
      message.error(reanalyzeError.message || '重新分析失败');
    } finally {
      setReanalyzingId(null);
    }
  }

  const total = filteredLogs.length;
  const errorCount = filteredLogs.filter((item) => item.level === 'ERROR').length;
  const warnCount = filteredLogs.filter((item) => item.level === 'WARN').length;
  const diagnosedCount = filteredLogs.filter((item) => item.diagnosisStatus === 'success').length;

  const columns = [
    {
      title: '时间 / 设备',
      width: 220,
      render: (_, record) => (
        <div>
          <div style={{ fontWeight: 600 }}>{record.time}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>{record.deviceName} · {record.deviceId}</div>
        </div>
      ),
    },
    {
      title: '模块 / 级别',
      width: 140,
      render: (_, record) => (
        <Space size={8} wrap>
          <span>{record.module}</span>
          {levelTag(record.level)}
        </Space>
      ),
    },
    {
      title: '日志内容',
      dataIndex: 'message',
      width: 360,
      render: (value, record) => (
        <div>
          <div style={{ color: '#0f172a', fontWeight: 600 }}>{value}</div>
          <div style={{ color: '#64748b', fontSize: 12 }}>Trace ID: {record.traceId}</div>
        </div>
      ),
    },
    {
      title: 'AI 诊断',
      width: 260,
        render: (_, record) => (
          <div>
            {diagnosisTag(record.diagnosisStatus)}
            <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>
              {diagnosisSummary(record)}
            </div>
          </div>
        ),
    },
    {
      title: '操作',
      width: 150,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => setSelectedLog(record)}>
            详情
          </Button>
          <Button
            type="link"
            size="small"
            loading={reanalyzingId === record.id}
            onClick={() => handleReanalyze(record.id)}
          >
            重跑分析
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="beacon-dh-page">
      <PageHeader
        title="数字人监管日志"
        icon={<FileTextOutlined />}
        description="聚合查看终端日志、AI 诊断结果与节点收集状态。"
        extra={(
          <Button icon={<ReloadOutlined />} onClick={() => { reload(); reloadNode(); }}>
            刷新
          </Button>
        )}
      />

      <KpiCardGroup>
        <KpiCard title="日志总量" value={total} suffix="条" color="#2563eb" icon={<FileTextOutlined />} />
        <KpiCard title="错误日志" value={errorCount} suffix="条" color="#ef4444" icon={<DeploymentUnitOutlined />} />
        <KpiCard title="预警日志" value={warnCount} suffix="条" color="#f97316" icon={<DeploymentUnitOutlined />} />
        <KpiCard title="AI 完成率" value={total ? Math.round((diagnosedCount / total) * 1000) / 10 : 0} suffix="%" color="#16a34a" icon={<DeploymentUnitOutlined />} />
      </KpiCardGroup>

      <div className="beacon-dh-grid beacon-dh-grid--two">
        <SummaryCard
          title="采集节点状态"
          meta="日志通道健康度"
          icon={<DeploymentUnitOutlined />}
          tone="cyan"
          items={[
            { label: '当前状态', value: nodeLoading && !nodeData ? '加载中' : nodeData?.label || '--' },
            { label: '最近接收', value: nodeData?.lastReceivedAt || '--' },
            { label: '采集策略', value: 'Beacon 本地日志真数据' },
            { label: '节点输出', value: '日志流 + AI 诊断摘要' },
          ]}
        />

        <Card
          className="beacon-panel-card beacon-panel-card--tone-slate"
          size="small"
          title={<PanelTitle title="首期接入说明" meta="日志与诊断边界" icon={<FileTextOutlined />} tone="slate" />}
        >
          <div className="beacon-dh-detail-note">
            当前页已切到真实日志检索与 AI 诊断接口；外部后端暂未返回结构化上下文，Beacon 先展示基础占位说明。
          </div>
        </Card>
      </div>

      <FilterBar
        filters={[
          { key: 'keyword', label: '设备 / 日志 / Trace ID', type: 'input', placeholder: '请输入设备名、日志内容或 Trace ID' },
          {
            key: 'level',
            label: '级别',
            type: 'select',
            options: [
              { label: 'ERROR', value: 'ERROR' },
              { label: 'WARN', value: 'WARN' },
              { label: 'INFO', value: 'INFO' },
            ],
          },
          { key: 'module', label: '模块', type: 'select', options: moduleOptions },
        ]}
        initialValues={filters}
        onSearch={(values) => setFilters(values)}
        onReset={() => setFilters({})}
      />

      <Card className="beacon-panel-card beacon-panel-card--tone-slate" size="small" styles={{ body: { padding: 0 } }}>
        <ProTable
          columns={columns}
          dataSource={filteredLogs}
          loading={loading}
          rowKey="id"
          pagination={false}
        />
      </Card>

      <DetailDrawer
        open={Boolean(selectedLog)}
        onClose={() => setSelectedLog(null)}
        title={selectedLog ? `${selectedLog.deviceName} · 日志详情` : '日志详情'}
        width={780}
        footer={selectedLog ? (
          <>
            <Button onClick={() => setSelectedLog(null)}>关闭</Button>
            <Button
              type="primary"
              loading={reanalyzingId === selectedLog.id}
              onClick={() => handleReanalyze(selectedLog.id)}
            >
              重新分析
            </Button>
          </>
        ) : null}
      >
        {selectedLog ? (
          <>
            <DetailSection
              title="基础信息"
              items={[
                { label: '日志时间', value: selectedLog.time },
                { label: '设备标识', value: selectedLog.deviceId },
                { label: '设备名称', value: selectedLog.deviceName },
                { label: '日志模块', value: selectedLog.module },
                { label: '级别', value: levelTag(selectedLog.level) },
                { label: 'Trace ID', value: selectedLog.traceId },
                { label: 'AI 状态', value: diagnosisTag(selectedLog.diagnosisStatus) },
              ]}
            />

            <Card className="beacon-panel-card beacon-panel-card--tone-blue" size="small" title="日志正文" style={{ marginTop: 16 }}>
              <div className="beacon-dh-ai-text">{selectedLog.message}</div>
            </Card>

            <Card className="beacon-panel-card beacon-panel-card--tone-orange" size="small" title="AI 诊断" style={{ marginTop: 16 }}>
              {selectedLog.diagnosisText ? (
                <div className="beacon-dh-ai-text">{selectedLog.diagnosisText}</div>
              ) : (
                <Alert type="warning" showIcon message={diagnosisSummary(selectedLog)} />
              )}
            </Card>

            <Card className="beacon-panel-card beacon-panel-card--tone-slate" size="small" title="结构化上下文" style={{ marginTop: 16 }}>
              <pre className="beacon-dh-json">{JSON.stringify(selectedLog.structured || {}, null, 2)}</pre>
            </Card>
          </>
        ) : null}
      </DetailDrawer>
    </div>
  );
}

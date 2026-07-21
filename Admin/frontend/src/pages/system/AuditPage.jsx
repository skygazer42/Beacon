import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Progress, Space, Statistic, Tag, Typography } from 'antd';
import { DownloadOutlined, FileSearchOutlined, ReloadOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import { API } from '../../api/endpoints';
import { apiPostRaw } from '../../api/client';
import { formatTime } from '../../utils/format';

const { Text } = Typography;

function buildAuditExportUrl(params, format) {
  const query = new URLSearchParams();
  [
    ['since', params.since],
    ['until', params.until],
    ['keyword', params.keyword],
    ['actor', params.actor],
    ['object', params.object],
    ['action', params.action],
    ['ok', params.ok],
    ['event_type', params.event_type],
    ['format', format],
  ].forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.append(key, value);
    }
  });
  const suffix = query.toString();
  return suffix ? `${API.opsAuditExport}?${suffix}` : API.opsAuditExport;
}

function buildAuditListBody(params) {
  return {
    page: params?.p || 1,
    page_size: params?.ps || 20,
    since: params?.since || '',
    until: params?.until || '',
    keyword: params?.keyword || '',
    actor: params?.actor || '',
    object: params?.object || '',
    action: params?.action || '',
    ok: params?.ok || '',
    event_type: params?.event_type || '',
  };
}

export default function AuditPage() {
  const [params, setParams] = useState({
    p: 1,
    ps: 20,
    since: '',
    until: '',
    keyword: '',
    actor: '',
    object: '',
    action: '',
    ok: '',
    event_type: '',
  });
  const [data, setData] = useState({ rows: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadRows = useCallback(async (nextParams = params) => {
    setLoading(true);
    setError(null);
    try {
      const payload = await apiPostRaw(API.opsAuditList, buildAuditListBody(nextParams));
      const nextData = {
        rows: Array.isArray(payload?.data) ? payload.data : [],
        total: Number(payload?.total) || 0,
      };
      setData(nextData);
      return nextData;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    loadRows(params);
  }, [loadRows, params]);

  const rows = Array.isArray(data?.rows) ? data.rows : [];
  const stats = {
    filtered_total: data?.total || 0,
    success_total: rows.filter(row => row.ok).length,
    failure_total: rows.filter(row => !row.ok).length,
  };
  const successRate = stats.filtered_total ? Math.round((stats.success_total / stats.filtered_total) * 100) : 0;
  const failureRate = stats.filtered_total ? Math.round((stats.failure_total / stats.filtered_total) * 100) : 0;
  const pageData = {
    page: params.p || 1,
    page_size: params.ps || 20,
    count: data?.total || 0,
  };
  const exportUrls = {
    json: buildAuditExportUrl(params, 'json'),
    csv: buildAuditExportUrl(params, 'csv'),
  };
  const okChoices = [
    { code: '', name: '全部结果' },
    { code: '1', name: '成功' },
    { code: '0', name: '失败' },
  ];
  const activeOkChoice = okChoices.find((item) => item.code === params.ok)?.name || '全部结果';
  const summaryItems = useMemo(
    () => [
      {
        key: 'time',
        label: '时间',
        value: params.since && params.until ? `${formatTime(params.since)} ~ ${formatTime(params.until)}` : '全部时间',
      },
      { key: 'actor', label: '操作者', value: params.actor || '全部操作者' },
      { key: 'object', label: '对象', value: params.object || '全部对象' },
      { key: 'action', label: '动作', value: params.action || '全部动作' },
      { key: 'event_type', label: '类型', value: params.event_type || '全部类型' },
      { key: 'result', label: '结果', value: activeOkChoice },
    ],
    [activeOkChoice, params.action, params.actor, params.event_type, params.object, params.since, params.until],
  );

  const filters = useMemo(
    () => [
      { key: 'keyword', label: '关键词', type: 'input', placeholder: '事件/错误/IP/详情' },
      { key: 'actor', label: '操作者', type: 'input', placeholder: 'admin' },
      { key: 'object', label: '对象', type: 'input', placeholder: '布控/算法/节点' },
      { key: 'action', label: '动作', type: 'input', placeholder: '动作' },
      { key: 'event_type', label: '事件类型', type: 'input', placeholder: '事件类型' },
      {
        key: 'ok',
        label: '结果',
        type: 'select',
        options: okChoices.map(item => ({ value: item.code, label: item.name })),
      },
      { key: 'dateRange', label: '时间范围', type: 'dateRange' },
    ],
    [okChoices],
  );

  const handleSearch = useCallback((filterValues) => {
    const range = filterValues.dateRange;
    let since = '';
    let until = '';
    if (range?.[0] && range?.[1]) {
      since = range[0].startOf('day').toISOString();
      until = range[1].endOf('day').toISOString();
    }
    setParams((prev) => ({
      ...prev,
      p: 1,
      since,
      until,
      keyword: filterValues.keyword || '',
      actor: filterValues.actor || '',
      object: filterValues.object || '',
      action: filterValues.action || '',
      ok: filterValues.ok || '',
      event_type: filterValues.event_type || '',
    }));
  }, []);

  const handleReset = useCallback(() => {
    setParams({
      p: 1,
      ps: 20,
      since: '',
      until: '',
      keyword: '',
      actor: '',
      object: '',
      action: '',
      ok: '',
      event_type: '',
    });
  }, []);

  const handleTableChange = useCallback((pagination) => {
    setParams((prev) => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const columns = [
    { title: '事件类型', dataIndex: 'event_type', ellipsis: true, width: 220 },
    { title: '动作', dataIndex: 'action_label', width: 100, render: (v) => v || '-' },
    {
      title: '结果',
      dataIndex: 'ok',
      width: 90,
      render: (v) => (v ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag>),
    },
    {
      title: '对象',
      dataIndex: 'object_label',
      width: 180,
      ellipsis: true,
      render: (v, r) => {
        const label = v || '-';
        return r.record_url ? <a href={r.record_url}>{label}</a> : label;
      },
    },
    { title: '操作者', dataIndex: 'operator', width: 140, ellipsis: true, render: (v, r) => v || r.actor_label || '-' },
    { title: '来源 IP', dataIndex: 'source_ip', width: 130, ellipsis: true },
    { title: '错误信息', dataIndex: 'error_message', ellipsis: true, render: (v) => v || '-' },
    { title: '时间', dataIndex: 'create_time', width: 170, render: (v) => formatTime(v) },
  ];

  return (
    <div>
      <PageHeader
        title="审计日志"
        icon={<FileSearchOutlined />}
        description="操作审计日志查询"
        extra={(
          <Space wrap>
            <a href={exportUrls.json}>
              <Button icon={<DownloadOutlined />}>导出 JSON</Button>
            </a>
            <a href={exportUrls.csv}>
              <Button icon={<DownloadOutlined />}>导出 CSV</Button>
            </a>
            <Button icon={<ReloadOutlined />} onClick={() => loadRows(params)}>
              刷新
            </Button>
          </Space>
        )}
      />

      {error ? <Alert type="error" showIcon style={{ marginBottom: 12 }} message={error.message || '加载失败'} /> : null}

      <div className="beacon-support-grid beacon-equal-height-grid" data-layout="full-width" style={{ marginBottom: 16 }}>
        <SummaryCard title="筛选范围" meta="当前查询与导出条件" icon={<FileSearchOutlined />} tone="blue" items={summaryItems} />

        <Card
          className="beacon-panel-card beacon-panel-card--tone-slate beacon-stat-panel"
          title={<PanelTitle title="筛选结果" meta="当前返回记录数" icon={<FileSearchOutlined />} tone="slate" />}
          size="small"
        >
          <Statistic value={stats.filtered_total ?? pageData.count ?? rows.length} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            导出链接会继承这里的筛选条件
          </Text>
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-green beacon-stat-panel"
          title={<PanelTitle title="成功" meta="执行成功占比" icon={<ReloadOutlined />} tone="green" />}
          size="small"
        >
          <Statistic value={stats.success_total} />
          <Progress percent={successRate} size="small" status={successRate >= 80 ? 'success' : 'active'} />
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-orange beacon-stat-panel"
          title={<PanelTitle title="失败" meta="异常事件占比" icon={<DownloadOutlined />} tone="orange" />}
          size="small"
        >
          <Statistic value={stats.failure_total} />
          <Progress percent={failureRate} size="small" status={stats.failure_total ? 'exception' : 'normal'} />
        </Card>
      </div>

      <FilterBar
        filters={filters}
        onSearch={handleSearch}
        onReset={handleReset}
        expandThreshold={4}
        initialValues={{
          keyword: params.keyword,
          actor: params.actor,
          object: params.object,
          action: params.action,
          event_type: params.event_type,
          ok: params.ok,
        }}
      />

      <Card
        className="beacon-panel-card beacon-panel-card--tone-slate"
        title={<PanelTitle title="审计明细" meta="按当前过滤条件返回" icon={<FileSearchOutlined />} tone="slate" />}
        size="small"
        styles={{ body: { padding: 0 } }}
      >
        <ProTable
          columns={columns}
          dataSource={rows}
          loading={loading}
          rowKey={(r) => r.id ?? `${r.create_time}-${r.event_type}`}
          pagination={{
            current: pageData.page || params.p || 1,
            pageSize: pageData.page_size || params.ps || 20,
            total: pageData.count || 0,
          }}
          onChange={handleTableChange}
        />
      </Card>
    </div>
  );
}

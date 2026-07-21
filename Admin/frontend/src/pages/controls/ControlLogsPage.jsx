import React, { useState, useCallback } from 'react';
import { Tag, Typography } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import KpiCard, { KpiCardGroup } from '../../components/KpiCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { formatTime } from '../../utils/format';

const { Text } = Typography;

export default function ControlLogsPage() {
  const [params, setParams] = useState({ p: 1, ps: 20 });
  const { data, loading } = useApi(API.controlLogs, params);

  const rows = data?.rows || [];
  const pageData = data?.pageData || {};
  const filters = data?.filters || {};
  const stats = data?.stats || {};
  const actions = data?.actions || [];
  const resultChoices = data?.resultChoices || [];

  const handleTableChange = useCallback((pagination) => {
    setParams(prev => ({ ...prev, p: pagination.current, ps: pagination.pageSize }));
  }, []);

  const handleSearch = useCallback((values) => {
    setParams((prev) => ({
      ...prev,
      p: 1,
      control_code: values.control_code || '',
      action: values.action || '',
      result_code: values.result_code || '',
    }));
  }, []);

  const handleReset = useCallback(() => {
    setParams((prev) => ({
      p: 1,
      ps: prev.ps || 20,
    }));
  }, []);

  const filterItems = [
    {
      key: 'control_code',
      label: '布控编号',
      placeholder: '布控编号 / 关键词',
    },
    {
      key: 'action',
      label: '操作',
      type: 'select',
      options: actions.map((item) => ({
        value: item.code,
        label: item.name,
      })),
    },
    {
      key: 'result_code',
      label: '结果',
      type: 'select',
      options: resultChoices.map((item) => ({
        value: item.code,
        label: item.name,
      })),
    },
  ];

  const columns = [
    { title: '布控编号', dataIndex: 'control_code', width: 140, ellipsis: true },
    { title: '操作', dataIndex: 'action', width: 100 },
    {
      title: '结果',
      dataIndex: 'result_code',
      width: 70,
      render: v => v === 0 || v === '0' || v === 1000 ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag>,
    },
    { title: '消息', dataIndex: 'result_msg', ellipsis: true },
    { title: '详情', dataIndex: 'detail', ellipsis: true, render: v => v || '-' },
    { title: '操作人', dataIndex: 'operator', width: 100 },
    {
      title: '时间',
      dataIndex: 'create_time',
      width: 160,
      render: v => <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(v)}</Text>,
    },
  ];

  return (
    <div>
      <PageHeader title="布控日志" description="布控执行日志查询" icon={<FileTextOutlined />} />
      <FilterBar
        filters={filterItems}
        initialValues={filters}
        onSearch={handleSearch}
        onReset={handleReset}
      />
      <KpiCardGroup>
        <KpiCard title="筛选结果" value={stats.filtered_total ?? pageData.count ?? rows.length} />
        <KpiCard title="成功数" value={stats.success_total ?? 0} color="#16a34a" />
        <KpiCard title="失败数" value={stats.failure_total ?? 0} color="#dc2626" />
      </KpiCardGroup>
      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey={(r) => String(r.id || `${r.control_code}-${r.create_time}`)}
        pagination={{
          current: pageData.page || 1,
          pageSize: pageData.page_size || 20,
          total: pageData.count || 0,
        }}
        onChange={handleTableChange}
      />
    </div>
  );
}

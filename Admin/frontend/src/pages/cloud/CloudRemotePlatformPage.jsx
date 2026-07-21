import React, { useMemo, useState } from 'react';
import { Alert, Button, Card, Descriptions, Select, Space, Typography } from 'antd';
import { CloudServerOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import StatusBadge from '../../components/StatusBadge';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { getBootstrapQuery } from '../../bootstrap';

const { Text } = Typography;

function flattenInfo(obj, prefix = '') {
  if (!obj || typeof obj !== 'object') return [];
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      out.push(...flattenInfo(v, key));
    } else {
      out.push({
        key,
        label: key,
        children: Array.isArray(v) ? v.join(', ') : String(v ?? '-'),
      });
    }
  }
  return out;
}

export default function CloudRemotePlatformPage() {
  const query = getBootstrapQuery();
  const [clusterId, setClusterId] = useState(() => query.get('cluster_id') || '');

  const apiParams = useMemo(() => (clusterId ? { cluster_id: clusterId } : {}), [clusterId]);
  const { data, loading, run } = useApi(API.cloudRemotePlatform, apiParams);

  const accessOk = data?.access_ok !== false;
  const clusters = data?.clusters || [];
  const selected = data?.selected_cluster;
  const activeClusterId = clusterId || (selected?.id == null ? '' : String(selected.id));
  const coreProcess = data?.core_process_data || [];
  const algorithmFlows = data?.algorithm_flows || [];
  const info = data?.core_process_info || {};

  const clusterOptions = useMemo(
    () => clusters.map((c) => ({ value: String(c.id), label: c.name || `集群 #${c.id}` })),
    [clusters],
  );

  const infoItems = useMemo(() => flattenInfo(info), [info]);
  const showRemoteSections = Boolean(clusterId && data?.found && !data?.remote_error);

  const clusterSummaryItems = selected
    ? [
        { key: 'id', label: '集群 ID', children: selected.id },
        { key: 'name', label: '名称', children: selected.name || '-' },
      ]
    : [];

  const processColumns = [
    { title: '#', dataIndex: 'process_index', width: 48 },
    { title: '主机', dataIndex: 'analyzer_host', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'ok',
      width: 80,
      render: (ok) => <StatusBadge status={ok ? 'success' : 'error'} text={ok ? '正常' : '异常'} />,
    },
    { title: 'CPU', width: 80, render: (_, r) => r.resource?.cpuUsageText || '-' },
    { title: '内存', width: 80, render: (_, r) => r.resource?.memoryUsageText || '-' },
    { title: '布控', width: 64, render: (_, r) => r.scheduler?.runningControls ?? '-' },
    { title: '算法', width: 64, render: (_, r) => r.scheduler?.loadedAlgorithms ?? '-' },
  ];

  const flowColumns = [
    { title: '编号', dataIndex: 'code', width: 140, ellipsis: true },
    { title: '名称', dataIndex: 'name', ellipsis: true },
  ];

  return (
    <div>
      <PageHeader
        title="远程平台"
        icon={<CloudServerOutlined />}
        description="远程平台信息"
        extra={
          <Space wrap>
            <Button aria-label="刷新" onClick={() => run?.(apiParams)}>
              刷新
            </Button>
            <Button onClick={() => run?.(apiParams)}>
              测试连接
            </Button>
            <Button
              href={activeClusterId ? `/cloud/remote/streams?cluster_id=${encodeURIComponent(activeClusterId)}` : undefined}
              disabled={!activeClusterId}
            >
              远程共享
            </Button>
            <Button href="/cloud/edge-clusters">
              边缘配置
            </Button>
          </Space>
        }
      />

      {!accessOk && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={data?.access_message || '无权访问远程平台'}
        />
      )}

      {data?.remote_error && (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message={data.remote_error} />
      )}

      {data?.message && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={data.message} />
      )}

      <Space style={{ marginBottom: 16 }}>
        <span>边缘集群</span>
        <Select
          allowClear
          placeholder="选择集群"
          style={{ width: 260 }}
          options={clusterOptions}
          value={clusterId || undefined}
          onChange={(v) => setClusterId(v || '')}
        />
      </Space>

      {showRemoteSections && (
        <>
          <Card size="small" title="集群" style={{ marginBottom: 16 }}>
            <Descriptions column={1} size="small" bordered items={clusterSummaryItems} />
          </Card>

          {(infoItems.length > 0) && (
            <Card size="small" title="平台信息" style={{ marginBottom: 16 }}>
              <Descriptions column={1} size="small" bordered items={infoItems} />
            </Card>
          )}

          <Card size="small" title="分析进程" style={{ marginBottom: 16 }}>
            <ProTable
              columns={processColumns}
              dataSource={coreProcess}
              loading={loading}
              rowKey="process_index"
              pagination={false}
            />
          </Card>

          {algorithmFlows.length > 0 && (
            <Card size="small" title="算法流水线">
              <ProTable
                columns={flowColumns}
                dataSource={algorithmFlows}
                loading={loading}
                rowKey="code"
                pagination={false}
              />
            </Card>
          )}
        </>
      )}

      {clusterId && data && !data.found && !data.message && (
        <Text type="secondary">未找到集群或未加载数据。</Text>
      )}

      {!clusterId && (
        <Text type="secondary">请选择边缘集群以查看远程平台信息。</Text>
      )}
    </div>
  );
}

import React, { useMemo, useState } from 'react';
import { Alert, Button, Select, Space, Tag, Typography } from 'antd';
import { ReloadOutlined, VideoCameraOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { getBootstrapQuery } from '../../bootstrap';

const { Text } = Typography;

export default function CloudRemoteStreamsPage() {
  const query = getBootstrapQuery();
  const [clusterId, setClusterId] = useState(() => query.get('cluster_id') || '');

  const apiParams = useMemo(() => {
    const p = {};
    if (clusterId) p.cluster_id = clusterId;
    return p;
  }, [clusterId]);

  const { data, loading, run } = useApi(API.cloudRemoteStreams, apiParams);

  const rows = data?.rows || [];
  const accessOk = data?.access_ok !== false;
  const clusters = data?.clusters || [];
  const selectedId = data?.selected_cluster_id == null ? '' : String(data.selected_cluster_id);
  const activeClusterId = clusterId || selectedId;

  const clusterOptions = useMemo(
    () => clusters.map((c) => ({ value: String(c.id), label: c.name || `集群 #${c.id}` })),
    [clusters],
  );

  const columns = [
    { title: '编号', dataIndex: 'code', width: 140, ellipsis: true },
    { title: '应用', dataIndex: 'app', width: 100, ellipsis: true },
    { title: '名称', dataIndex: 'name', width: 140, ellipsis: true },
    { title: '昵称', dataIndex: 'nickname', width: 120, ellipsis: true },
    { title: '拉流地址', dataIndex: 'pull_stream_url', ellipsis: true },
    { title: '类型', dataIndex: 'pull_stream_type', width: 100, ellipsis: true },
    {
      title: '状态',
      dataIndex: 'state',
      width: 88,
      render: (v) => {
        if (v === 1 || v === true) return <Tag color="success">开</Tag>;
        if (v === 0 || v === false) return <Tag>关</Tag>;
        return <Tag color="processing">{v == null ? '-' : String(v)}</Tag>;
      },
    },
    {
      title: '转发',
      dataIndex: 'forward_state',
      width: 88,
      render: (v) => <Text type="secondary">{v == null ? '-' : String(v)}</Text>,
    },
    { title: '备注', dataIndex: 'remark', ellipsis: true },
    {
      title: '操作',
      width: 220,
      fixed: 'right',
      render: (_, r) => (
        <Space size={0} wrap>
          {r.detail_url ? <Button type="link" size="small" href={r.detail_url}>详情</Button> : null}
          {r.recordings_url ? <Button type="link" size="small" href={r.recordings_url}>录像</Button> : null}
          {activeClusterId ? (
            <Button
              type="link"
              size="small"
              href={`/cloud/remote/platform?cluster_id=${encodeURIComponent(activeClusterId)}`}
            >
              平台
            </Button>
          ) : null}
          {r.code ? (
            <Button
              type="link"
              size="small"
              onClick={() => {
                if (globalThis.navigator?.clipboard?.writeText) {
                  globalThis.navigator.clipboard.writeText(r.code);
                }
              }}
            >
              复制编号
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="远程视频流"
        icon={<VideoCameraOutlined />}
        description="远程视频流管理"
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => run(apiParams)}>
              刷新
            </Button>
            <Button
              href={
                activeClusterId
                  ? `/cloud/remote/platform?cluster_id=${encodeURIComponent(activeClusterId)}`
                  : undefined
              }
              disabled={!activeClusterId}
            >
              上级平台
            </Button>
            <Button
              href={
                activeClusterId
                  ? `/cloud/remote/recordings?cluster_id=${encodeURIComponent(activeClusterId)}`
                  : undefined
              }
              disabled={!activeClusterId}
            >
              远程录像
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
          message={data?.access_message || '无权访问远程视频流'}
        />
      )}

      {data?.message && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={data.message} />
      )}

      {data?.remote_error && (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message={data.remote_error} />
      )}

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="录像按视频流编号查询。"
        description="远程共享读取边缘端视频流，详情页可修改配置，平台页可查看边缘端运行状态。"
      />

      <Space wrap style={{ marginBottom: 16 }}>
        <span>边缘集群</span>
        <Select
          placeholder="选择集群"
          style={{ width: 240 }}
          options={clusterOptions}
          value={clusterId || selectedId || undefined}
          onChange={(v) => setClusterId(v || '')}
        />
      </Space>

      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey={(r) => `${r.code || r.name || ''}-${r.pull_stream_url || ''}`}
        pagination={false}
      />
    </div>
  );
}

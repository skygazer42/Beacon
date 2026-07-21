import React, { useCallback, useMemo, useState } from 'react';
import { Alert, Button, Select, Space, Typography } from 'antd';
import { DatabaseOutlined, ReloadOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import StatusBadge from '../../components/StatusBadge';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { formatTime } from '../../utils/format';
import { getBootstrapQuery } from '../../bootstrap';

const { Text } = Typography;

export default function CloudRemoteRecordingsPage() {
  const bootstrapQ = getBootstrapQuery();
  const [draft, setDraft] = useState({
    cluster_id: bootstrapQ.get('cluster_id') || '',
    stream_code: bootstrapQ.get('stream_code') || '',
  });
  const [queryArgs, setQueryArgs] = useState(() => ({
    cluster_id: bootstrapQ.get('cluster_id') || '',
    stream_code: bootstrapQ.get('stream_code') || '',
    p: Number(bootstrapQ.get('p')) || 1,
    ps: Number(bootstrapQ.get('ps')) || 20,
  }));

  const { data, loading, run } = useApi(API.cloudRemoteRecordings, queryArgs);
  const streamApiParams = useMemo(() => (draft.cluster_id ? { cluster_id: draft.cluster_id } : {}), [draft.cluster_id]);
  const { data: streamData, loading: streamsLoading } = useApi(
    API.cloudRemoteStreams,
    streamApiParams,
    { manual: !draft.cluster_id },
  );

  const rows = data?.rows || [];
  const pageData = data?.pageData || {};
  const total = data?.total ?? pageData.count ?? 0;
  const accessOk = data?.access_ok !== false;
  const clusters = data?.clusters || [];
  const activeClusterId = draft.cluster_id || String(data?.selected_cluster_id || '');

  const clusterOptions = useMemo(
    () => clusters.map((c) => ({ value: String(c.id), label: c.name || `集群 #${c.id}` })),
    [clusters],
  );

  const streamOptions = useMemo(() => {
    const rows = streamData?.rows || [];
    const options = rows
      .map((row) => {
        const code = String(row.code || row.name || '').trim();
        if (!code) return null;
        const name = String(row.nickname || row.name || '').trim();
        return {
          value: code,
          label: name && name !== code ? `${name} (${code})` : code,
        };
      })
      .filter(Boolean);
    if (draft.stream_code && !options.some((item) => item.value === draft.stream_code)) {
      options.unshift({ value: draft.stream_code, label: draft.stream_code });
    }
    return options;
  }, [draft.stream_code, streamData?.rows]);

  const handleTableChange = useCallback((pagination) => {
    setQueryArgs((prev) => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const handleSearch = useCallback(() => {
    setQueryArgs((prev) => ({
      ...draft,
      p: 1,
      ps: prev.ps,
    }));
  }, [draft]);

  const columns = [
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    { title: '相对路径', dataIndex: 'rel_path', ellipsis: true },
    {
      title: '修改时间',
      dataIndex: 'mtime',
      width: 168,
      render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(v)}</Text>,
    },
    {
      title: '播放',
      dataIndex: 'play_url',
      width: 88,
      render: (url, r) => (
        url && !r.play_error
          ? <Button type="link" size="small" href={url} target="_blank" rel="noreferrer">打开</Button>
          : '-'
      ),
    },
    {
      title: '状态',
      dataIndex: 'play_error',
      width: 100,
      ellipsis: true,
      render: (err) => (err ? <StatusBadge status="error" text="错误" /> : <StatusBadge status="success" text="可用" />),
    },
  ];

  return (
    <div>
      <PageHeader
        title="远程录像"
        icon={<DatabaseOutlined />}
        description="远程录像管理"
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => run(queryArgs)}>
              刷新
            </Button>
            <Button
              href={
                activeClusterId
                  ? `/cloud/remote/streams?cluster_id=${encodeURIComponent(activeClusterId)}`
                  : undefined
              }
              disabled={!activeClusterId}
            >
              远程共享
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
          message={data?.access_message || '无权访问远程录像'}
        />
      )}

      {data?.message && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={data.message} />
      )}

      {data?.top_msg && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={data.top_msg} />
      )}

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="从远程共享读取视频流列表，避免手填 stream_code。"
      />

      <Space wrap style={{ marginBottom: 16 }} align="start">
        <span>边缘集群</span>
        <Select
          allowClear
          placeholder="选择集群"
          style={{ width: 220 }}
          options={clusterOptions}
          value={draft.cluster_id || undefined}
          onChange={(v) => setDraft((d) => ({ ...d, cluster_id: v || '', stream_code: '' }))}
        />
        <span>视频流编号</span>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="选择视频流"
          style={{ width: 260 }}
          loading={streamsLoading}
          options={streamOptions}
          value={draft.stream_code || undefined}
          onChange={(v) => setDraft((d) => ({ ...d, stream_code: v || '' }))}
        />
        <Button type="primary" onClick={handleSearch}>
          查询
        </Button>
      </Space>

      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey={(r) => `${r.filename}-${r.rel_path}-${r.mtime}`}
        pagination={{
          current: pageData.page || queryArgs.p,
          pageSize: pageData.page_size || queryArgs.ps,
          total,
        }}
        onChange={handleTableChange}
      />
    </div>
  );
}

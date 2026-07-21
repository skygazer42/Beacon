import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Descriptions, Drawer, Input, Select, Space, Tag, Typography } from 'antd';
import { AlertOutlined, ReloadOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { formatTime } from '../../utils/format';
import { getBootstrapQuery } from '../../bootstrap';

const { Text } = Typography;

function alarmDetailUrl(record) {
  return record?.detail_url || `/cloud/alarm/detail?id=${encodeURIComponent(record?.id || '')}`;
}

function alarmImageUrl(record) {
  if (!record?.id) return '';
  return `${API.cloudAlarmImage}?id=${encodeURIComponent(record.id)}`;
}

function resolveStreamCode(record) {
  return record?.stream_code || record?.streamCode || record?.stream || record?.control_stream_code || '';
}

function remotePlatformUrl(record) {
  if (!record?.cluster_id) return '';
  return `/cloud/remote/platform?cluster_id=${encodeURIComponent(record.cluster_id)}`;
}

function remoteStreamDetailUrl(record) {
  const streamCode = resolveStreamCode(record);
  if (!record?.cluster_id || !streamCode) return '';
  return `/cloud/remote/stream/detail?cluster_id=${encodeURIComponent(record.cluster_id)}&code=${encodeURIComponent(streamCode)}`;
}

function remoteRecordingsUrl(record) {
  const streamCode = resolveStreamCode(record);
  if (!record?.cluster_id || !streamCode) return '';
  return `/cloud/remote/recordings?cluster_id=${encodeURIComponent(record.cluster_id)}&stream_code=${encodeURIComponent(streamCode)}`;
}

export default function CloudAlarmsPage() {
  const query = getBootstrapQuery();
  const [params, setParams] = useState({
    p: Number(query.get('p')) || 1,
    ps: Number(query.get('ps')) || 20,
    cluster_id: query.get('cluster_id') || '',
    event_type: query.get('event_type') || '',
    q: query.get('q') || '',
  });
  const [linkedAlarm, setLinkedAlarm] = useState(null);

  const { data, loading, run } = useApi(API.cloudAlarms, params);

  const rows = data?.rows || [];
  const pageData = data?.pageData || {};
  const total = pageData.count ?? 0;
  const accessOk = data?.access_ok !== false;
  const clusters = data?.clusters || [];
  const activeClusterId = params.cluster_id || String(data?.selected_cluster_id || '');

  useEffect(() => {
    const selectedClusterId = String(data?.selected_cluster_id || '');
    setParams((prev) => {
      if ((prev.cluster_id || '') === selectedClusterId) {
        return prev;
      }
      return {
        ...prev,
        cluster_id: selectedClusterId,
        p: 1,
      };
    });
  }, [data?.selected_cluster_id]);

  const clusterOptions = useMemo(
    () => clusters.map((c) => ({ value: String(c.id), label: c.name || `集群 #${c.id}` })),
    [clusters],
  );

  const eventTypeOptions = useMemo(() => {
    const types = new Set(rows.map((row) => String(row.event_type || '').trim()).filter(Boolean));
    if (params.event_type) types.add(params.event_type);
    return Array.from(types).map((type) => ({ value: type, label: type }));
  }, [params.event_type, rows]);

  const handleTableChange = useCallback((pagination) => {
    setParams((prev) => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const openDetail = useCallback((record) => {
    globalThis.location.href = alarmDetailUrl(record);
  }, []);

  const openLinkage = useCallback((record) => {
    setLinkedAlarm(record);
  }, []);

  const columns = [
    { title: '集群', dataIndex: 'cluster_name', width: 180, ellipsis: true },
    { title: '事件 ID', dataIndex: 'event_id', width: 220, ellipsis: true },
    { title: '事件类型', dataIndex: 'event_type', width: 140, ellipsis: true },
    {
      title: '描述',
      dataIndex: 'desc',
      ellipsis: true,
      render: (v, r) => (
        <a
          href={alarmDetailUrl(r)}
          onClick={(e) => { e.stopPropagation(); }}
          style={{ cursor: 'pointer' }}
        >
          {v || '-'}
        </a>
      ),
    },
    { title: '节点', dataIndex: 'node_code', width: 120, ellipsis: true },
    { title: '布控', dataIndex: 'control_code', width: 120, ellipsis: true },
    {
      title: '截图',
      dataIndex: 'has_image',
      width: 88,
      render: (value) => (
        <Tag color={value ? 'success' : 'default'}>
          {value ? '有' : '无'}
        </Tag>
      ),
    },
    {
      title: '时间',
      dataIndex: 'timestamp',
      width: 168,
      render: (v, r) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {formatTime(v || r.received_at)}
        </Text>
      ),
    },
    {
      title: '操作',
      dataIndex: 'detail_url',
      width: 128,
      render: (value, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              openLinkage(record);
            }}
          >
            联动
          </Button>
          <a
            href={value || alarmDetailUrl(record)}
            onClick={(e) => e.stopPropagation()}
          >
            详情
          </a>
        </Space>
      ),
    },
  ];

  const linkedStreamCode = resolveStreamCode(linkedAlarm);
  const linkedImageUrl = alarmImageUrl(linkedAlarm);
  const linkedRemotePlatformUrl = remotePlatformUrl(linkedAlarm);
  const linkedRemoteStreamUrl = remoteStreamDetailUrl(linkedAlarm);
  const linkedRecordingsUrl = remoteRecordingsUrl(linkedAlarm);

  return (
    <div>
      <PageHeader
        title="云端告警"
        icon={<AlertOutlined />}
        description="云端告警事件"
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => run(params)}>
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
            <Button href="/cloud/edge-clusters">
              边缘集群
            </Button>
          </Space>
        }
      />

      {!accessOk && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={data?.access_message || '无权查看云端告警'}
        />
      )}

      <Space wrap style={{ marginBottom: 16 }}>
        <span>边缘集群</span>
        <Select
          allowClear
          placeholder="全部集群"
          style={{ width: 220 }}
          options={clusterOptions}
          value={params.cluster_id || undefined}
          onChange={(v) => setParams((prev) => ({ ...prev, cluster_id: v || '', p: 1 }))}
        />
        <span>事件类型</span>
        <Select
          allowClear
          placeholder="事件类型"
          style={{ width: 180 }}
          options={eventTypeOptions}
          value={params.event_type || undefined}
          onChange={(v) => setParams((prev) => ({ ...prev, event_type: v || '', p: 1 }))}
        />
        <Input.Search
          allowClear
          placeholder="搜索事件/节点/布控/视频流"
          style={{ width: 260 }}
          value={params.q}
          onChange={(e) => setParams((prev) => ({ ...prev, q: e.target.value, p: 1 }))}
          onSearch={(v) => setParams((prev) => ({ ...prev, q: v, p: 1 }))}
        />
        <Text type="secondary">告警状态：新告警</Text>
      </Space>

      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey="id"
        pagination={{
          current: pageData.page || params.p,
          pageSize: pageData.page_size || params.ps,
          total,
        }}
        onChange={handleTableChange}
        onRow={(record) => ({
          onClick: () => openDetail(record),
          style: { cursor: 'pointer' },
        })}
      />

      <Drawer
        title="告警联动"
        width={560}
        open={!!linkedAlarm}
        onClose={() => setLinkedAlarm(null)}
        destroyOnHidden
      >
        {linkedAlarm && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card size="small">
              <Descriptions
                column={1}
                size="small"
                items={[
                  { key: 'cluster', label: '集群', children: linkedAlarm.cluster_name || '-' },
                  { key: 'event', label: '事件 ID', children: linkedAlarm.event_id || '-' },
                  { key: 'type', label: '事件类型', children: linkedAlarm.event_type || '-' },
                  { key: 'node', label: '节点', children: linkedAlarm.node_code || '-' },
                  { key: 'control', label: '布控', children: linkedAlarm.control_code || '-' },
                  { key: 'stream', label: '视频流', children: linkedStreamCode || '-' },
                  {
                    key: 'time',
                    label: '时间',
                    children: formatTime(linkedAlarm.timestamp || linkedAlarm.received_at),
                  },
                ]}
              />
            </Card>

            {linkedAlarm.has_image && linkedImageUrl && (
              <Card size="small" title="告警截图">
                <img
                  alt="云端告警截图"
                  src={linkedImageUrl}
                  style={{
                    display: 'block',
                    width: '100%',
                    maxHeight: 260,
                    objectFit: 'contain',
                    background: '#f5f7fb',
                    borderRadius: 6,
                  }}
                />
              </Card>
            )}

            <Card size="small" title="远程流">
              <Space wrap>
                <Button href={linkedRemoteStreamUrl || undefined} disabled={!linkedRemoteStreamUrl}>
                  流详情
                </Button>
                <Button href={linkedRemotePlatformUrl || undefined} disabled={!linkedRemotePlatformUrl}>
                  远程平台
                </Button>
              </Space>
              {!linkedRemoteStreamUrl && (
                <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                  当前告警缺少集群或视频流编号，暂不能直接定位远程流。
                </Text>
              )}
            </Card>

            <Card size="small" title="录像回放">
              <Space wrap>
                <Button href={linkedRecordingsUrl || undefined} disabled={!linkedRecordingsUrl}>
                  查询录像
                </Button>
                <Button href={alarmDetailUrl(linkedAlarm)}>
                  告警详情
                </Button>
              </Space>
              {!linkedRecordingsUrl && (
                <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                  需要集群和视频流编号后才能按告警流查询录像。
                </Text>
              )}
            </Card>
          </Space>
        )}
      </Drawer>
    </div>
  );
}

import React from 'react';
import { Alert, Card, Descriptions, Image, Spin, Typography } from 'antd';
import { AlertOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { formatTime } from '../../utils/format';
import { getBootstrapQuery } from '../../bootstrap';

const { Paragraph, Text } = Typography;

export default function CloudAlarmDetailPage() {
  const query = getBootstrapQuery();
  const alarmId = query.get('id');

  const { data, loading, error } = useApi(
    API.cloudAlarmDetail,
    alarmId ? { id: alarmId } : {},
    { manual: !alarmId },
  );

  const accessOk = data?.access_ok !== false;
  const alarm = data?.alarm;
  const fallbackImageUrl = alarm?.id ? `${API.cloudAlarmImage}?id=${encodeURIComponent(alarm.id)}` : '';
  const previewImageUrl = data?.image_url || (data?.image_error ? fallbackImageUrl : '');
  const showPreviewImage = Boolean(previewImageUrl);

  const descItems = alarm
    ? [
        { key: 'id', label: '告警 ID', children: alarm.id },
        { key: 'event_id', label: '事件 ID', children: alarm.event_id || '-' },
        { key: 'event_type', label: '事件类型', children: alarm.event_type || '-' },
        { key: 'event_source', label: '事件来源', children: alarm.event_source || '-' },
        { key: 'desc', label: '描述', children: alarm.desc || '-' },
        { key: 'node_code', label: '节点', children: alarm.node_code || '-' },
        { key: 'control_code', label: '布控', children: alarm.control_code || '-' },
        { key: 'cluster_name', label: '集群', children: alarm.cluster_name || data?.cluster_name || '-' },
        {
          key: 'timestamp',
          label: '事件时间',
          children: formatTime(alarm.timestamp || alarm.received_at),
        },
        {
          key: 'received_at',
          label: '接收时间',
          children: formatTime(alarm.received_at),
        },
      ]
    : [];

  return (
    <div>
      <PageHeader title="云端告警详情" icon={<AlertOutlined />} description="云端告警详情" />

      {!alarmId && (
        <Alert type="error" showIcon message="缺少告警 ID（id 查询参数）" style={{ marginBottom: 16 }} />
      )}

      {error && (
        <Alert type="error" showIcon message={error.message || '加载失败'} style={{ marginBottom: 16 }} />
      )}

      {!accessOk && data && (
        <Alert
          type="warning"
          showIcon
          message={data?.access_message || '无权查看'}
          style={{ marginBottom: 16 }}
        />
      )}

      <Spin spinning={loading && !!alarmId}>
        {data?.message && !data?.found && (
          <Alert type="info" showIcon message={data.message} style={{ marginBottom: 16 }} />
        )}

        {alarm && (
          <>
            <Card size="small" styles={{ body: { paddingBottom: 8 } }}>
              <Descriptions column={1} size="small" bordered items={descItems} />
            </Card>

            {showPreviewImage && (
              <Card size="small" title="截图" style={{ marginTop: 16 }}>
                <Image
                  src={previewImageUrl}
                  alt="告警截图"
                  style={{ maxWidth: '100%' }}
                  fallback="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEyMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEyMCIgZmlsbD0iI2YwZjBmMCIvPjwvc3ZnPg=="
                />
                {data?.image_error && (
                  <Paragraph type="secondary" style={{ marginTop: 8 }}>
                    <Text type="warning">{data.image_error}</Text>
                  </Paragraph>
                )}
              </Card>
            )}

            {data?.payload_pretty && (
              <Card size="small" title="原始载荷" style={{ marginTop: 16 }}>
                <pre style={{ margin: 0, maxHeight: 360, overflow: 'auto', fontSize: 12 }}>
                  {data.payload_pretty}
                </pre>
              </Card>
            )}
          </>
        )}
      </Spin>
    </div>
  );
}

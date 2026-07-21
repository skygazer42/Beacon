import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Card, Descriptions, Form, Input, Spin, Typography } from 'antd';
import { ArrowLeftOutlined, VideoCameraOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import { apiGet, apiPost } from '../../api/client';
import { API } from '../../api/endpoints';
import { getBootstrapQuery } from '../../bootstrap';

const { Text } = Typography;

export default function CloudRemoteStreamDetailPage() {
  const { message } = App.useApp();
  const query = getBootstrapQuery();
  const clusterId = query.get('cluster_id') || '';
  /** Stream identifier: `id` (preferred) or legacy `code` query param. */
  const streamCode = query.get('id') || query.get('code') || '';

  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    if (!clusterId || !streamCode) {
      setLoading(false);
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet(API.cloudRemoteStreamDetail, {
        cluster_id: clusterId,
        code: streamCode,
      });
      setData(res);
      const s = res?.stream || {};
      form.setFieldsValue({
        app: s.app || '',
        nickname: s.nickname || s.name || '',
        remark: s.remark || '',
        pull_stream_url: s.pull_stream_url || '',
        pull_stream_type: s.pull_stream_type == null ? '' : String(s.pull_stream_type),
      });
    } catch (e) {
      setError(e);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [clusterId, streamCode, form]);

  useEffect(() => {
    load();
  }, [load]);

  const onSave = async () => {
    if (!data?.manage_allowed) {
      message.warning('无权修改远程摄像头配置');
      return;
    }
    try {
      const values = await form.validateFields();
      const fd = new FormData();
      fd.append('cluster_id', String(clusterId));
      fd.append('code', streamCode);
      Object.entries(values).forEach(([k, v]) => {
        if (v !== undefined && v !== null) fd.append(k, String(v));
      });
      await apiPost(API.cloudRemoteStreamDetail, fd);
      message.success('保存成功');
      load();
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '保存失败');
    }
  };

  const stream = data?.stream || {};
  const cluster = data?.cluster || {};

  const descItems = useMemo(
    () => [
      { key: 'cluster', label: '集群', children: cluster.name ? `${cluster.name} (#${cluster.id})` : cluster.id || '-' },
      { key: 'code', label: '编码', children: stream.code || streamCode || '-' },
      { key: 'app', label: '应用', children: stream.app || '-' },
      { key: 'name', label: '名称', children: stream.name || '-' },
      { key: 'nickname', label: '昵称', children: stream.nickname || '-' },
      { key: 'state', label: '状态', children: stream.state == null ? '-' : String(stream.state) },
      { key: 'pull_stream_url', label: '拉流地址', children: stream.pull_stream_url || '-' },
      { key: 'remark', label: '备注', children: stream.remark || '-' },
    ],
    [cluster, stream, streamCode],
  );

  if (!clusterId || !streamCode) {
    return (
      <div>
        <PageHeader title="远程视频流详情" icon={<VideoCameraOutlined />} description="远程视频流详情" />
        <Alert type="error" showIcon message="缺少 cluster_id 或 id（或 code）查询参数" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="远程视频流详情"
        icon={<VideoCameraOutlined />}
        description="远程视频流详情"
        extra={
          <Button icon={<ArrowLeftOutlined />} href={`/cloud/remote/streams?cluster_id=${encodeURIComponent(clusterId)}`}>
            返回列表
          </Button>
        }
      />

      {error && <Alert type="error" showIcon message={error.message || '加载失败'} style={{ marginBottom: 16 }} />}

      {data?.message ? <Alert type="info" showIcon message={data.message} style={{ marginBottom: 16 }} /> : null}
      {data?.error_msg ? <Alert type="warning" showIcon message={data.error_msg} style={{ marginBottom: 16 }} /> : null}

      {stream.recordings_url ? (
        <div style={{ marginBottom: 16 }}>
          <Button href={stream.recordings_url}>查看录像</Button>
        </div>
      ) : null}

      <Spin spinning={loading}>
        <Card size="small" title="详情" style={{ marginBottom: 16 }}>
          <Descriptions bordered size="small" column={{ xs: 1, md: 2 }} items={descItems} />
        </Card>

        {data?.manage_allowed ? (
          <Card size="small" title="编辑">
            <Form form={form} layout="vertical" style={{ maxWidth: 720 }}>
              <Form.Item name="app" label="应用">
                <Input />
              </Form.Item>
              <Form.Item name="nickname" label="名称">
                <Input />
              </Form.Item>
              <Form.Item name="pull_stream_type" label="拉流类型">
                <Input />
              </Form.Item>
              <Form.Item name="pull_stream_url" label="拉流地址">
                <Input.TextArea rows={2} />
              </Form.Item>
              <Form.Item name="remark" label="备注">
                <Input.TextArea rows={2} />
              </Form.Item>
              <Button type="primary" onClick={onSave}>
                保存
              </Button>
            </Form>
          </Card>
        ) : (
          <Text type="secondary">当前账号无修改权限。</Text>
        )}
      </Spin>
    </div>
  );
}

import React, { useEffect, useState, useCallback } from 'react';
import { App, Alert, Button, Form, Input, Select } from 'antd';
import { VideoCameraOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import SkeletonPage from '../../components/Skeleton';
import { apiGet, apiPost } from '../../api/client';
import { API } from '../../api/endpoints';
import { getBootstrapPath, getBootstrapQuery } from '../../bootstrap';

const { TextArea } = Input;

/** Select key → backend `pull_stream_type` int (HTTP-FLV / WS-FLV both map to FLV=3) */
const PULL_TYPE_KEYS = [
  { key: 'rtsp', pullType: 1, label: 'RTSP' },
  { key: 'rtmp', pullType: 2, label: 'RTMP' },
  { key: 'http-flv', pullType: 3, label: 'HTTP-FLV' },
  { key: 'ws-flv', pullType: 3, label: 'WS-FLV' },
  { key: 'hls', pullType: 4, label: 'HLS' },
];

function pullTypeKeyFromInt(n) {
  const t = Number(n) || 1;
  const row = PULL_TYPE_KEYS.find((r) => r.pullType === t);
  return row ? row.key : 'rtsp';
}

function suggestStreamCode() {
  const bytes = new Uint8Array(6);
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    const seed = Date.now();
    bytes.forEach((_, index) => {
      bytes[index] = (seed >> (index * 4)) & 0xff;
    });
  }
  const hex = Array.from(bytes.slice(0, 4), (byte) => byte.toString(16).padStart(2, '0')).join('');
  const n = 10000 + ((bytes[4] << 8 | bytes[5]) % 90000);
  return `cam${hex}${n}`;
}

function navigateTo(url) {
  const userAgent = globalThis.window === undefined ? '' : globalThis.navigator?.userAgent || '';
  if (userAgent.includes('jsdom')) {
    try {
      globalThis.history.pushState({}, '', url);
    } catch {
      // Ignore fallback navigation failures in test environments.
    }
    return;
  }

  try {
    globalThis.location.assign(url);
    return;
  } catch {
    // Some non-browser environments do not implement full navigation.
  }

  try {
    globalThis.history.pushState({}, '', url);
  } catch {
    // Ignore fallback navigation failures.
  }
}

export default function StreamAddEditPage() {
  const { message } = App.useApp();
  const path = getBootstrapPath();
  const query = getBootstrapQuery();
  const codeParam = (query.get('code') || '').trim();

  const isEdit = path === '/stream/edit';
  const isAdd = path === '/stream/add';

  const [form] = Form.useForm();
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const loadEdit = useCallback(async () => {
    if (!codeParam) {
      setLoadError('缺少摄像头编号（code）');
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const row = await apiGet(API.streamGet, { code: codeParam });
      form.setFieldsValue({
        code: row.code,
        app: row.app || 'live',
        name: row.name || row.code,
        pull_stream_url: row.pull_stream_url || '',
        pull_stream_type: pullTypeKeyFromInt(row.pull_stream_type),
        nickname: row.nickname || '',
        remark: row.remark || '',
        site_label: row.site_label || '',
        floor_label: row.floor_label || '',
      });
    } catch (e) {
      setLoadError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [codeParam, form]);

  useEffect(() => {
    if (isEdit) {
      loadEdit();
      return;
    }
    if (isAdd) {
      form.setFieldsValue({
        code: suggestStreamCode(),
        app: 'live',
        name: '',
        pull_stream_url: '',
        pull_stream_type: 'rtsp',
        nickname: '',
        remark: '',
        site_label: '',
        floor_label: '',
      });
      const code = form.getFieldValue('code');
      form.setFieldsValue({ name: code });
    }
  }, [isAdd, isEdit, form, loadEdit]);

  const onCodeChange = (e) => {
    if (isEdit) return;
    const v = e.target.value;
    form.setFieldsValue({ name: v || '' });
  };

  const onFinish = async (values) => {
    const fd = new FormData();
    fd.append('code', String(values.code || '').trim());
    fd.append('app', String(values.app || 'live').trim());
    fd.append('pull_stream_url', String(values.pull_stream_url || '').trim());
    const pt = PULL_TYPE_KEYS.find((r) => r.key === values.pull_stream_type);
    fd.append('pull_stream_type', String(pt ? pt.pullType : 1));
    fd.append('nickname', String(values.nickname || '').trim());
    fd.append('remark', String(values.remark || ''));
    fd.append('site_label', String(values.site_label || '').trim());
    fd.append('floor_label', String(values.floor_label || '').trim());
    fd.append('name', String(values.name || values.code || '').trim());

    setSubmitting(true);
    try {
      if (isEdit) {
        await apiPost(API.streamEdit, fd);
        message.success('保存成功');
      } else {
        await apiPost(API.streamAdd, fd);
        message.success('添加成功');
      }
      navigateTo('/stream/index');
    } catch (e) {
      message.error(e.message || '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (!isAdd && !isEdit) {
    return (
      <Alert type="error" message="未知路由，请从视频流列表进入添加/编辑页" showIcon />
    );
  }

  if (loading) {
    return <SkeletonPage />;
  }

  return (
    <div>
      <PageHeader
        title={isEdit ? `编辑视频流 — ${codeParam}` : '添加视频流'}
        icon={<VideoCameraOutlined />}
        description="新增或编辑视频流配置"
        extra={<Button href="/stream/index">返回列表</Button>}
      />

      {loadError ? (
        <Alert type="error" message={loadError} showIcon style={{ marginBottom: 16 }} />
      ) : null}

      <Form
        form={form}
        layout="vertical"
        size="small"
        style={{ maxWidth: 640 }}
        onFinish={onFinish}
        disabled={!!loadError && isEdit}
      >
        <Form.Item
          name="code"
          label="编号"
          rules={[{ required: true, message: '请输入编号' }]}
        >
          <Input
            placeholder="唯一编号"
            disabled={isEdit}
            onChange={onCodeChange}
          />
        </Form.Item>

        <Form.Item
          name="app"
          label="分组 (app)"
          rules={[{ required: true, message: '请输入分组' }]}
        >
          <Input placeholder="例如 live" />
        </Form.Item>

        <Form.Item
          name="name"
          label="名称 (name)"
          tooltip={isEdit ? '与媒体服务流名一致；此接口不单独提交修改' : '添加时通常与编号一致（后端可能仍以编号为准）'}
        >
          <Input placeholder="与编号一致" disabled={isEdit} />
        </Form.Item>

        <Form.Item
          name="pull_stream_url"
          label="视频流地址"
          rules={[{ required: true, message: '请输入拉流地址' }]}
        >
          <Input placeholder="rtsp:// / rtmp:// / http(s):// …" />
        </Form.Item>

        <Form.Item
          name="pull_stream_type"
          label="拉流类型"
          rules={[{ required: true }]}
        >
          <Select
            options={PULL_TYPE_KEYS.map((o) => ({ value: o.key, label: o.label }))}
            popupMatchSelectWidth={false}
          />
        </Form.Item>

        <Form.Item
          name="nickname"
          label="摄像头名称"
          rules={[{ required: true, message: '请输入摄像头名称' }]}
        >
          <Input placeholder="展示名称" />
        </Form.Item>

        <Form.Item name="site_label" label="站点标签">
          <Input placeholder="可选" />
        </Form.Item>

        <Form.Item name="floor_label" label="楼层标签">
          <Input placeholder="可选" />
        </Form.Item>

        <Form.Item name="remark" label="备注">
          <TextArea rows={3} placeholder="可选" />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {isEdit ? '保存' : '添加'}
          </Button>
        </Form.Item>
      </Form>
    </div>
  );
}

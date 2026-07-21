import React, { useState } from 'react';
import { App, Button, Card, Form, Input, InputNumber, Modal, Select, Spin, Switch, Alert, Descriptions, Space, Tag, Table, Typography } from 'antd';
import { ApiOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';
import { formatTime } from '../../utils/format';

const { Paragraph, Text } = Typography;

function parseDeviceEndpoint(xaddrs) {
  const u = Array.isArray(xaddrs) && xaddrs.length ? String(xaddrs[0]) : '';
  try {
    const url = new URL(u);
    return { ip_address: url.hostname, port: Number(url.port) || 80, device_url: u };
  } catch {
    return { ip_address: '', port: 80, device_url: u };
  }
}

export default function OnvifPage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.onvif);
  const [discovering, setDiscovering] = useState(false);
  const [devices, setDevices] = useState([]);
  const [credOpen, setCredOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [infoLoading, setInfoLoading] = useState(false);
  const [infoPayload, setInfoPayload] = useState(null);
  const [rtspOpen, setRtspOpen] = useState(false);
  const [rtspRows, setRtspRows] = useState([]);
  const [importOpen, setImportOpen] = useState(false);
  const [snapshotOpen, setSnapshotOpen] = useState(false);
  const [snapshotPayload, setSnapshotPayload] = useState(null);
  const [credForm] = Form.useForm();
  const [importForm] = Form.useForm();

  const rows = data?.recent_streams || [];
  const summary = data?.summary || {};
  const snapshotImageUrl = snapshotPayload?.image_url
    || (snapshotPayload?.image_path ? `/${snapshotPayload.image_path.replace(/^\/+/, '')}` : '');

  const openCredentials = (device) => {
    const { ip_address, port } = parseDeviceEndpoint(device?.xaddrs);
    credForm.setFieldsValue({
      ip_address: device?.ip_address || ip_address,
      port: device?.port || port,
      username: '',
      password: '',
    });
    setCredOpen(true);
  };

  const discover = async () => {
    setDiscovering(true);
    try {
      const res = await apiPost(API.onvifDiscover, { timeout: 8 });
      const list = Array.isArray(res) ? res : res?.data || [];
      setDevices(list);
      message.success(`发现 ${list.length} 台设备`);
    } catch (e) {
      message.error(e?.message || '发现失败');
    } finally {
      setDiscovering(false);
    }
  };

  const fetchDeviceInfo = async () => {
    const v = await credForm.validateFields();
    setInfoLoading(true);
    try {
      const res = await apiPost(API.onvifDeviceInfo, {
        ip_address: v.ip_address,
        port: v.port,
        username: v.username,
        password: v.password,
      });
      const payload = res?.data === undefined ? res : res.data;
      setInfoPayload(payload);
      setCredOpen(false);
      setInfoOpen(true);
    } catch (e) {
      message.error(e?.message || '获取设备信息失败');
    } finally {
      setInfoLoading(false);
    }
  };

  const fetchRtsp = async () => {
    const v = await credForm.validateFields();
    setInfoLoading(true);
    try {
      const res = await apiPost(API.onvifGetRtsp, {
        ip_address: v.ip_address,
        port: v.port,
        username: v.username,
        password: v.password,
      });
      const list = res?.data === undefined ? res : res.data;
      setRtspRows(
        Array.isArray(list)
          ? list.map((item, index) => ({
            ...item,
            _rowKey: item.profile_token || item.profile_name || item.rtsp_url || `rtsp-${index}`,
          }))
          : [],
      );
      setCredOpen(false);
      setRtspOpen(true);
    } catch (e) {
      message.error(e?.message || '获取 RTSP 失败');
    } finally {
      setInfoLoading(false);
    }
  };

  const captureSnapshot = async () => {
    const v = await credForm.validateFields();
    setInfoLoading(true);
    try {
      const res = await apiPost(API.onvifSnapshot, {
        ip_address: v.ip_address,
        port: v.port,
        username: v.username,
        password: v.password,
        profile_index: 0,
      });
      const payload = res?.data === undefined ? res : res.data;
      setSnapshotPayload(payload || null);
      setCredOpen(false);
      setSnapshotOpen(true);
      message.success('截图完成');
    } catch (e) {
      message.error(e?.message || '抓图失败');
    } finally {
      setInfoLoading(false);
    }
  };

  const openImportFromDevice = (device) => {
    const { ip_address, port } = parseDeviceEndpoint(device?.xaddrs);
    importForm.setFieldsValue({
      ip_address: device?.ip_address || ip_address,
      port: device?.port || port,
      username: '',
      password: '',
      profiles: [0],
      skip_existing: true,
      auto_start: false,
    });
    setImportOpen(true);
  };

  const submitImport = async () => {
    try {
      const v = await importForm.validateFields();
      const profiles = (Array.isArray(v.profiles) ? v.profiles : String(v.profiles || '').split(','))
        .map((x) => Number.parseInt(String(x).trim(), 10))
        .filter((n) => !Number.isNaN(n));
      await apiPost(API.onvifImport, {
        ip_address: v.ip_address,
        port: v.port,
        username: v.username,
        password: v.password,
        profiles,
        skip_existing: Boolean(v.skip_existing),
        auto_start_forward: Boolean(v.auto_start),
      });
      message.success('导入请求已提交');
      setImportOpen(false);
      run();
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '导入失败');
    }
  };

  const deviceColumns = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: 'IP', dataIndex: 'ip_address', width: 140 },
    { title: '端口', dataIndex: 'port', width: 72 },
    { title: '厂商', dataIndex: 'manufacturer', ellipsis: true },
    { title: '型号', dataIndex: 'model', ellipsis: true },
    {
      title: '操作',
      key: 'dops',
      width: 280,
      render: (_, r) => (
        <Space wrap size={0}>
          <Button type="link" size="small" onClick={() => openCredentials(r)}>
            账号
          </Button>
          <Button type="link" size="small" onClick={() => openImportFromDevice(r)}>
            导入流
          </Button>
        </Space>
      ),
    },
  ];

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '编号', dataIndex: 'code', width: 160, ellipsis: true },
    { title: '名称', dataIndex: 'nickname', ellipsis: true, render: (v, r) => v || r.name || '-' },
    { title: '分组', dataIndex: 'app', width: 100, ellipsis: true },
    { title: '站点', dataIndex: 'site_label', width: 100, ellipsis: true },
    {
      title: '在线',
      dataIndex: 'state',
      width: 70,
      render: (v) => (v === 1 ? <Tag color="success">在线</Tag> : <Tag>离线</Tag>),
    },
    {
      title: '转发',
      dataIndex: 'forward_state',
      width: 70,
      render: (v) => (v === 1 ? <Tag color="processing">转发</Tag> : <Tag>否</Tag>),
    },
    { title: '拉流地址', dataIndex: 'pull_stream_url', ellipsis: true },
    { title: '更新时间', dataIndex: 'last_update_time', width: 170, render: (v) => formatTime(v) },
  ];

  return (
    <div>
      <PageHeader
        title="ONVIF 设备发现"
        icon={<ApiOutlined />}
        description="ONVIF 设备发现与管理"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => run()}>
              刷新
            </Button>
            <Button type="primary" icon={<SearchOutlined />} loading={discovering} onClick={discover}>
              发现设备
            </Button>
          </Space>
        }
      />

      {error ? <Alert type="error" message={error.message || '加载失败'} style={{ marginBottom: 16 }} showIcon /> : null}

      <Spin spinning={loading}>
        <Card size="small" style={{ marginBottom: 16 }}>
          <Descriptions
            bordered
            size="small"
            column={{ xs: 1, md: 3 }}
            items={[
              { key: 'imported', label: '已导入 ONVIF 流', children: String(summary.imported_count ?? '-') },
              { key: 'online', label: '在线', children: String(summary.online_count ?? '-') },
              { key: 'forwarding', label: '转发中', children: String(summary.forwarding_count ?? '-') },
            ]}
          />
        </Card>

        <Card title={`发现设备（${devices.length}）`} size="small" style={{ marginBottom: 16 }}>
          <Table
            rowKey={(record) => record.device_url || record.xaddrs?.[0] || `${record.ip_address || 'unknown'}-${record.port || 0}-${record.name || 'device'}`}
            size="small"
            columns={deviceColumns}
            dataSource={devices}
            pagination={false}
          />
        </Card>

        <Card title="最近 ONVIF 相关流" size="small">
          <ProTable rowKey="id" columns={columns} dataSource={rows} loading={loading} pagination={{ pageSize: 20 }} />
        </Card>
      </Spin>

      <Modal
        title="ONVIF 登录"
        open={credOpen}
        onCancel={() => setCredOpen(false)}
        footer={[
          <Button key="c" onClick={() => setCredOpen(false)}>
            取消
          </Button>,
          <Button key="r" loading={infoLoading} onClick={fetchRtsp}>
            获取 RTSP
          </Button>,
          <Button key="s" loading={infoLoading} onClick={captureSnapshot}>
            抓图
          </Button>,
          <Button key="i" type="primary" loading={infoLoading} onClick={fetchDeviceInfo}>
            设备信息
          </Button>,
        ]}
        destroyOnHidden
      >
        <Form form={credForm} layout="vertical">
          <Form.Item name="ip_address" label="IP" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="port" label="端口" initialValue={80}>
            <InputNumber min={1} max={65535} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="username" label="用户名">
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="密码">
            <Input.Password autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="设备信息" open={infoOpen} onCancel={() => setInfoOpen(false)} footer={null} width={720} destroyOnHidden>
        <pre style={{ fontSize: 12, maxHeight: 420, overflow: 'auto' }}>{JSON.stringify(infoPayload, null, 2)}</pre>
      </Modal>

      <Modal title="RTSP 地址" open={rtspOpen} onCancel={() => setRtspOpen(false)} footer={null} width={720} destroyOnHidden>
        <Table
          size="small"
          rowKey="_rowKey"
          dataSource={rtspRows}
          columns={[
            { title: 'Profile', dataIndex: 'profile_name', ellipsis: true },
            { title: 'RTSP', dataIndex: 'rtsp_url', ellipsis: true },
          ]}
          pagination={false}
        />
      </Modal>

      <Modal title="抓图结果" open={snapshotOpen} onCancel={() => setSnapshotOpen(false)} footer={null} width={720} destroyOnHidden>
        {snapshotPayload?.image_path ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Paragraph copyable={{ text: snapshotPayload.image_path }} style={{ marginBottom: 0, wordBreak: 'break-all' }}>
              {snapshotPayload.image_path}
            </Paragraph>
            <img
              alt="onvif snapshot preview"
              src={snapshotImageUrl}
              style={{ width: '100%', maxHeight: 420, objectFit: 'contain', border: '1px solid #f0f0f0', borderRadius: 8 }}
            />
          </Space>
        ) : (
          <Text type="secondary">未返回截图路径</Text>
        )}
      </Modal>

      <Modal title="导入为视频流" open={importOpen} onCancel={() => setImportOpen(false)} onOk={submitImport} destroyOnHidden width={560}>
        <Form form={importForm} layout="vertical">
          <Form.Item name="ip_address" label="IP" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="port" label="端口" rules={[{ required: true }]}>
            <InputNumber min={1} max={65535} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="profiles"
            label="Profile 序号（默认 0，可多选）"
            tooltip="与设备 Profile 列表下标对应，可用「设备信息」查看"
            initialValue={[0]}
          >
            <Select mode="tags" placeholder="0 或 0,1" tokenSeparators={[',']} />
          </Form.Item>
          <Form.Item name="skip_existing" label="跳过已存在" valuePropName="checked" initialValue>
            <Switch />
          </Form.Item>
          <Form.Item name="auto_start" label="导入后自动转发" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

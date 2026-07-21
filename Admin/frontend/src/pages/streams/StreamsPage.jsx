import React, { useState, useCallback, useEffect } from 'react';
import PropTypes from 'prop-types';
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Space, Switch, Tag, Tooltip, Typography } from 'antd';
import {
  CloudUploadOutlined,
  DeleteOutlined,
  DeploymentUnitOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RadarChartOutlined,
  ReloadOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiGet, apiPost, apiPostForm } from '../../api/client';
import { formatTime } from '../../utils/format';
import { getBootstrapQuery } from '../../bootstrap';
import './StreamsPage.css';

const { Text } = Typography;
const TALKBACK_DEFAULTS = {
  enabled: false,
  transport_mode: 'webrtc_to_rtsp',
  onvif_service_url: '',
  onvif_username: '',
  onvif_password: '',
  profile_token: '',
  backchannel_uri: '',
  relay_app: 'talkback',
  relay_stream_prefix: '',
  sample_rate: 16000,
  codec_hint: 'pcma',
  remark: '',
};

function buildTalkbackSessionId(streamCode) {
  return `web_${String(streamCode || '').replace(/[^\w-]/g, '_')}`;
}

function isGb28181Stream(record) {
  return Number(record?.pull_stream_type) === 21 || Boolean(record?.gb28181_device_id) || Boolean(record?.gb28181_channel_id);
}

function StreamOverviewCard({ items }) {
  return (
    <Card
      className="beacon-panel-card beacon-streams-overview-card"
      size="small"
      styles={{ body: { padding: '20px 20px 18px' } }}
    >
      <div className="beacon-streams-card-head">
        <div className="beacon-streams-card-head__eyebrow">
          <span className="beacon-streams-card-head__icon beacon-streams-card-head__icon--blue">
            <VideoCameraOutlined />
          </span>
          <div className="beacon-streams-card-head__copy">
            <div className="beacon-streams-card-head__title">视频流总览</div>
            <div className="beacon-streams-card-head__meta">总览、回放转发与批量动作</div>
          </div>
        </div>
        <div className="beacon-streams-overview-card__glyph" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>

      <div className="beacon-streams-overview-card__rows">
        {items.map((item) => (
          <div className="beacon-streams-overview-card__row" key={item.key || item.label}>
            <span className="beacon-streams-overview-card__label">{item.label}</span>
            <span className="beacon-streams-overview-card__value">{item.value}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function StreamMetricCard({ tone, title, meta, value, footnote, aside, icon }) {
  return (
    <Card
      className={`beacon-panel-card beacon-streams-metric-card beacon-streams-metric-card--${tone}`}
      size="small"
      styles={{ body: { padding: '20px 20px 18px' } }}
    >
      <div className="beacon-streams-card-head">
        <div className="beacon-streams-card-head__eyebrow">
          <span className={`beacon-streams-card-head__icon beacon-streams-card-head__icon--${tone}`}>
            {icon}
          </span>
          <div className="beacon-streams-card-head__copy">
            <div className="beacon-streams-card-head__title">{title}</div>
            <div className="beacon-streams-card-head__meta">{meta}</div>
          </div>
        </div>
      </div>

      <div className="beacon-streams-metric-card__value">{value}</div>
      <div className="beacon-streams-metric-card__foot">
        <span>{footnote}</span>
        <span>{aside}</span>
      </div>
      <div className="beacon-streams-metric-card__signal" aria-hidden="true">
        <span className="beacon-streams-metric-card__signal-line" />
        <span className="beacon-streams-metric-card__signal-dot" />
      </div>
    </Card>
  );
}

StreamOverviewCard.propTypes = {
  items: PropTypes.arrayOf(PropTypes.shape({
    key: PropTypes.string,
    label: PropTypes.node.isRequired,
    value: PropTypes.node.isRequired,
  })).isRequired,
};

StreamMetricCard.propTypes = {
  tone: PropTypes.string.isRequired,
  title: PropTypes.node.isRequired,
  meta: PropTypes.node,
  value: PropTypes.node.isRequired,
  footnote: PropTypes.node,
  aside: PropTypes.node,
  icon: PropTypes.node,
};

function buildStreamsOverviewItems({ params, selectedCount, autoStart }) {
  return [
    { key: 'search', label: '搜索', value: params.q || '全部视频流' },
    { key: 'app', label: '分组', value: params.app || '全部分组' },
    { key: 'site', label: '站点', value: params.site || '全部站点' },
    { key: 'selected', label: '已选择', value: `${selectedCount} 项` },
    { key: 'autostart', label: '自动转发', value: autoStart ? <Tag color="success">已启用</Tag> : <Tag>已关闭</Tag> },
    { key: 'source', label: '来源', value: API.streams },
  ];
}

function buildStreamFilters(appChoices, siteChoices) {
  return [
    { key: 'q', label: '搜索', type: 'input', placeholder: '名称/编号/地址' },
    ...(appChoices.length > 0 ? [{ key: 'app', label: '分组', type: 'select', options: [{ value: '', label: '全部分组' }, ...appChoices] }] : []),
    ...(siteChoices.length > 0 ? [{ key: 'site', label: '站点', type: 'select', options: [{ value: '', label: '全部站点' }, ...siteChoices] }] : []),
  ];
}

function streamStateTag(value) {
  return value === 1 ? <Tag color="success">正常</Tag> : <Tag color="default">停用</Tag>;
}

function streamForwardTag(value) {
  return value === 1 ? <Tag color="processing">转发中</Tag> : <Tag color="default">未转发</Tag>;
}

function buildStreamPlayerHref(record) {
  const app = encodeURIComponent(String(record?.app || '').trim());
  const name = encodeURIComponent(String(record?.name || '').trim());
  if (app && name) {
    return `/stream/player?app=${app}&name=${name}`;
  }
  return `/stream/player?code=${encodeURIComponent(String(record?.code || '').trim())}`;
}

function StreamRowActions({ record, handlers }) {
  return (
    <div className="beacon-streams-row-actions">
      <Button type="link" size="small" href={buildStreamPlayerHref(record)} icon={<PlayCircleOutlined />}>
        播放
      </Button>
      <Button type="link" size="small" onClick={() => handlers.onState(record)}>
        {record.state === 1 ? '停用' : '启用'}
      </Button>
      <Button type="link" size="small" onClick={() => handlers.onProxy(record)}>
        {record.forward_state === 1 ? '停止转发' : '开启转发'}
      </Button>
      <Button type="link" size="small" icon={<RadarChartOutlined />} onClick={() => handlers.onSelfcheck(record)}>
        WebRTC 自检
      </Button>
      <Button type="link" size="small" onClick={() => handlers.onTalkback(record)}>
        回讲
      </Button>
      {isGb28181Stream(record) ? (
        <Button type="link" size="small" onClick={() => handlers.onPtz(record)}>
          云台
        </Button>
      ) : null}
      <Button type="link" size="small" onClick={() => handlers.onPusher(record)}>
        转推代理
      </Button>
      <Button type="link" size="small" href={`/stream/edit?code=${record.code}`}>
        编辑
      </Button>
      <Button type="link" size="small" danger onClick={() => handlers.onDelete(record.code)} icon={<DeleteOutlined />}>
        删除
      </Button>
    </div>
  );
}

StreamRowActions.propTypes = {
  record: PropTypes.shape({
    code: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    state: PropTypes.number,
    forward_state: PropTypes.number,
  }).isRequired,
  handlers: PropTypes.shape({
    onState: PropTypes.func.isRequired,
    onProxy: PropTypes.func.isRequired,
    onSelfcheck: PropTypes.func.isRequired,
    onTalkback: PropTypes.func.isRequired,
    onPtz: PropTypes.func.isRequired,
    onPusher: PropTypes.func.isRequired,
    onDelete: PropTypes.func.isRequired,
  }).isRequired,
};

function buildStreamColumns(handlers) {
  return [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 60,
      fixed: 'left',
    },
    {
      title: '编号',
      dataIndex: 'code',
      width: 140,
      ellipsis: true,
      render: (value) => <Tooltip title={value}><Text copyable={{ text: value }} style={{ fontSize: 12 }}>{value}</Text></Tooltip>,
    },
    {
      title: '名称',
      dataIndex: 'nickname',
      ellipsis: true,
      render: (value, record) => value || record.name || '-',
    },
    {
      title: '分组',
      dataIndex: 'app',
      width: 100,
      render: value => value || '-',
    },
    {
      title: '站点',
      dataIndex: 'site_label',
      width: 100,
      render: value => value || '-',
    },
    {
      title: '状态',
      dataIndex: 'state',
      width: 70,
      render: streamStateTag,
    },
    {
      title: '转发',
      dataIndex: 'forward_state',
      width: 70,
      render: streamForwardTag,
    },
    {
      title: '更新时间',
      dataIndex: 'last_update_time',
      width: 160,
      render: value => <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(value)}</Text>,
    },
    {
      title: '操作',
      width: 500,
      fixed: 'right',
      render: (_, record) => <StreamRowActions record={record} handlers={handlers} />,
    },
  ];
}

function StreamImportModal({ open, file, submitting, onClose, onSubmit, onFileChange }) {
  return (
    <Modal
      title="批量导入视频流"
      open={open}
      onCancel={onClose}
      onOk={onSubmit}
      okButtonProps={{ loading: submitting }}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="支持 CSV。列格式：昵称、视频流地址、备注、摄像头编号(可选)。"
      />
      <input
        aria-label="批量导入文件"
        type="file"
        accept=".csv"
        onChange={(e) => onFileChange(e.target.files?.[0] || null)}
      />
      <div style={{ marginTop: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {file ? `已选择: ${file.name}` : '尚未选择文件'}
        </Text>
      </div>
    </Modal>
  );
}

function TalkbackConfigModal({
  open,
  loading,
  submitting,
  record,
  stateText,
  statusPayload,
  form,
  onClose,
  onRefreshStatus,
  onStop,
  onStart,
  onSave,
}) {
  const title = record ? `回讲配置 - ${record.code}` : '回讲配置';
  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      destroyOnHidden
      width={760}
      footer={[
        <Button key="close" onClick={onClose}>
          关闭
        </Button>,
        <Button key="status" onClick={onRefreshStatus} disabled={!record}>
          刷新状态
        </Button>,
        <Button key="stop" onClick={onStop} loading={submitting} disabled={!record}>
          停止回讲
        </Button>,
        <Button key="start" type="primary" onClick={onStart} loading={submitting} disabled={!record}>
          开启回讲
        </Button>,
        <Button key="save" onClick={onSave} loading={submitting} disabled={!record}>
          保存配置
        </Button>,
      ]}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={stateText || '通过前端适配层调用现有 talkback 配置与控制接口。'}
        description={record ? `Session ID: ${buildTalkbackSessionId(record.code)}` : null}
      />
      <Form form={form} layout="vertical" initialValues={TALKBACK_DEFAULTS}>
        <Form.Item name="enabled" label="启用回讲" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="transport_mode" label="传输模式">
          <Input />
        </Form.Item>
        <Form.Item name="backchannel_uri" label="回讲地址">
          <Input />
        </Form.Item>
        <Form.Item name="relay_app" label="中继应用">
          <Input />
        </Form.Item>
        <Form.Item name="relay_stream_prefix" label="中继流前缀">
          <Input />
        </Form.Item>
        <Form.Item name="sample_rate" label="采样率">
          <InputNumber min={8000} max={48000} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="codec_hint" label="编码提示">
          <Input />
        </Form.Item>
        <Form.Item name="onvif_service_url" label="ONVIF 服务地址">
          <Input />
        </Form.Item>
        <Form.Item name="onvif_username" label="ONVIF 用户名">
          <Input />
        </Form.Item>
        <Form.Item name="onvif_password" label="ONVIF 密码">
          <Input.Password />
        </Form.Item>
        <Form.Item name="profile_token" label="Profile Token">
          <Input />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
      {loading ? (
        <Text type="secondary">正在加载...</Text>
      ) : (
        <pre style={{ maxHeight: 180, overflow: 'auto', fontSize: 12, background: '#f7f8fa', padding: 12 }}>
          {JSON.stringify(statusPayload || {}, null, 2)}
        </pre>
      )}
    </Modal>
  );
}

function PtzControlModal({
  open,
  record,
  submitting,
  speed,
  presetIndex,
  onClose,
  onSpeedChange,
  onPresetIndexChange,
  onAction,
}) {
  const title = record ? `GB28181 云台控制 - ${record.code}` : 'GB28181 云台控制';
  return (
    <Modal
      title={title}
      open={open}
      footer={[
        <Button key="close" onClick={onClose}>
          关闭
        </Button>,
      ]}
      onCancel={onClose}
      destroyOnHidden
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Text type="secondary">速度</Text>
          <InputNumber min={0} max={255} value={speed} onChange={(value) => onSpeedChange(Number(value || 0))} />
          <Text type="secondary">预置位编号</Text>
          <InputNumber
            aria-label="预置位编号"
            min={1}
            max={255}
            value={presetIndex}
            onChange={(value) => onPresetIndexChange(Number(value || 1))}
          />
        </Space>
        <Space wrap>
          <Button loading={submitting} onClick={() => onAction('up')}>上</Button>
          <Button loading={submitting} onClick={() => onAction('down')}>下</Button>
          <Button loading={submitting} onClick={() => onAction('left')}>左</Button>
          <Button loading={submitting} onClick={() => onAction('right')}>右</Button>
          <Button loading={submitting} onClick={() => onAction('zoom_in')}>放大</Button>
          <Button loading={submitting} onClick={() => onAction('zoom_out')}>缩小</Button>
          <Button loading={submitting} onClick={() => onAction('stop')}>停止</Button>
        </Space>
        <Space wrap>
          <Button loading={submitting} onClick={() => onAction('preset_call')}>调用预置位</Button>
          <Button loading={submitting} onClick={() => onAction('preset_set')}>设置预置位</Button>
          <Button loading={submitting} onClick={() => onAction('preset_delete')}>删除预置位</Button>
        </Space>
      </Space>
    </Modal>
  );
}

function PusherProxyModal({ open, record, form, submitting, result, onClose, onSubmit }) {
  const title = record ? `RTSP 转推代理 - ${record.code}` : 'RTSP 转推代理';
  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      onOk={onSubmit}
      okText="开始转推"
      okButtonProps={{ loading: submitting }}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item name="dst_host" label="目标主机" rules={[{ required: true, message: '请输入目标主机' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="dst_stream_app" label="目标应用" rules={[{ required: true, message: '请输入目标应用' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="dst_stream_name" label="目标流名" rules={[{ required: true, message: '请输入目标流名' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="dst_rtsp_port" label="RTSP 端口" rules={[{ required: true, message: '请输入 RTSP 端口' }]}>
          <InputNumber min={1} max={65535} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
      {result ? (
        <Alert
          style={{ marginTop: 8 }}
          type="success"
          showIcon
          message={result.msg || '转推代理已创建'}
          description={result.key ? `代理 Key: ${result.key}` : null}
        />
      ) : null}
    </Modal>
  );
}

function StreamSelfcheckModal({ open, loading, payload, onClose }) {
  return (
    <Modal
      title="WebRTC 自检报告"
      open={open}
      footer={null}
      onCancel={onClose}
    >
      {loading ? (
        <Text type="secondary">正在检查...</Text>
      ) : (
        <pre style={{ maxHeight: 360, overflow: 'auto', fontSize: 12, background: '#f7f8fa', padding: 12 }}>
          {JSON.stringify(payload || {}, null, 2)}
        </pre>
      )}
    </Modal>
  );
}

StreamImportModal.propTypes = {
  open: PropTypes.bool,
  file: PropTypes.object,
  submitting: PropTypes.bool,
  onClose: PropTypes.func,
  onSubmit: PropTypes.func,
  onFileChange: PropTypes.func,
};

TalkbackConfigModal.propTypes = {
  open: PropTypes.bool,
  loading: PropTypes.bool,
  submitting: PropTypes.bool,
  record: PropTypes.object,
  stateText: PropTypes.string,
  statusPayload: PropTypes.object,
  form: PropTypes.object,
  onClose: PropTypes.func,
  onRefreshStatus: PropTypes.func,
  onStop: PropTypes.func,
  onStart: PropTypes.func,
  onSave: PropTypes.func,
};

PtzControlModal.propTypes = {
  open: PropTypes.bool,
  record: PropTypes.object,
  submitting: PropTypes.bool,
  speed: PropTypes.number,
  presetIndex: PropTypes.number,
  onClose: PropTypes.func,
  onSpeedChange: PropTypes.func,
  onPresetIndexChange: PropTypes.func,
  onAction: PropTypes.func,
};

PusherProxyModal.propTypes = {
  open: PropTypes.bool,
  record: PropTypes.object,
  form: PropTypes.object,
  submitting: PropTypes.bool,
  result: PropTypes.object,
  onClose: PropTypes.func,
  onSubmit: PropTypes.func,
};

StreamSelfcheckModal.propTypes = {
  open: PropTypes.bool,
  loading: PropTypes.bool,
  payload: PropTypes.object,
  onClose: PropTypes.func,
};

export default function StreamsPage() {
  const { message } = App.useApp();
  const query = getBootstrapQuery();
  const [params, setParams] = useState({
    p: query.get('p') || 1,
    ps: query.get('ps') || 20,
    app: query.get('app') || '',
    site: query.get('site') || '',
    q: query.get('q') || '',
  });
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [autoStart, setAutoStart] = useState(false);
  const [autoStartLoading, setAutoStartLoading] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importSubmitting, setImportSubmitting] = useState(false);
  const [selfcheckOpen, setSelfcheckOpen] = useState(false);
  const [selfcheckLoading, setSelfcheckLoading] = useState(false);
  const [selfcheckPayload, setSelfcheckPayload] = useState(null);
  const [talkbackOpen, setTalkbackOpen] = useState(false);
  const [talkbackLoading, setTalkbackLoading] = useState(false);
  const [talkbackSubmitting, setTalkbackSubmitting] = useState(false);
  const [talkbackRecord, setTalkbackRecord] = useState(null);
  const [talkbackStateText, setTalkbackStateText] = useState('');
  const [talkbackStatusPayload, setTalkbackStatusPayload] = useState(null);
  const [ptzOpen, setPtzOpen] = useState(false);
  const [ptzSubmitting, setPtzSubmitting] = useState(false);
  const [ptzRecord, setPtzRecord] = useState(null);
  const [ptzSpeed, setPtzSpeed] = useState(32);
  const [ptzPresetIndex, setPtzPresetIndex] = useState(1);
  const [pusherOpen, setPusherOpen] = useState(false);
  const [pusherSubmitting, setPusherSubmitting] = useState(false);
  const [pusherRecord, setPusherRecord] = useState(null);
  const [pusherResult, setPusherResult] = useState(null);
  const [talkbackForm] = Form.useForm();
  const [pusherForm] = Form.useForm();

  const { data, loading, run } = useApi(API.streams, params);

  const rows = data?.rows || [];
  const pageData = data?.pageData || {};
  const stats = data?.stats || {};
  const appChoices = (data?.appChoices || []).map(c => ({ value: c, label: c }));
  const siteChoices = (data?.siteChoices || []).map(c => ({ value: c, label: c }));
  const totalStreams = Number(stats.total ?? pageData.count ?? rows.length ?? 0) || 0;
  const onlineStreams = Number(stats.online ?? 0) || 0;
  const forwardingStreams = Number(stats.forwarding ?? 0) || 0;
  const onlinePercent = totalStreams ? Math.round((onlineStreams / totalStreams) * 100) : 0;
  const forwardingPercent = totalStreams ? Math.round((forwardingStreams / totalStreams) * 100) : 0;
  const overviewItems = buildStreamsOverviewItems({ params, selectedCount: selectedRowKeys.length, autoStart });
  const selectedSummary = selectedRowKeys.length ? `已选择 ${selectedRowKeys.length} 项` : '未选择条目';

  const filters = buildStreamFilters(appChoices, siteChoices);

  const handleSearch = useCallback((filterValues) => {
    setParams(prev => ({ ...prev, ...filterValues, p: 1 }));
  }, []);

  const handleReset = useCallback(() => {
    setParams({ p: 1, ps: 20, app: '', site: '', q: '' });
  }, []);

  const handleTableChange = useCallback((pagination) => {
    setParams(prev => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const handleDelete = useCallback(async (code) => {
    try {
      const form = new FormData();
      form.append('code', code);
      await apiPost(API.streamDel, form);
      message.success('删除成功');
      run(params);
    } catch (e) {
      message.error(e.message || '删除失败');
    }
  }, [params, run, message]);

  useEffect(() => {
    let mounted = true;
    const loadAutoStart = async () => {
      setAutoStartLoading(true);
      try {
        const res = await apiGet(API.streamGetAutoStartConfig);
        if (mounted) {
          setAutoStart(Boolean(res?.auto_start));
        }
      } catch {
        /* ignore */
      } finally {
        if (mounted) {
          setAutoStartLoading(false);
        }
      }
    };
    loadAutoStart();
    return () => {
      mounted = false;
    };
  }, []);

  const postStreamAction = useCallback(async (url, body, okMessage) => {
    try {
      const result = await apiPost(url, body);
      message.success(result?.msg || okMessage || '操作成功');
      run(params);
      return result;
    } catch (e) {
      message.error(e?.message || '操作失败');
      return null;
    }
  }, [message, params, run]);

  const handleProxyAction = useCallback(async (record) => {
    const form = new FormData();
    form.append('code', record.code);
    const url = record.forward_state === 1 ? API.streamDelProxy : API.streamAddProxy;
    const okMessage = record.forward_state === 1 ? '停止转发成功' : '开启转发成功';
    await postStreamAction(url, form, okMessage);
  }, [postStreamAction]);

  const handleStateAction = useCallback(async (record) => {
    const nextState = record.state === 1 ? 0 : 1;
    await postStreamAction(
      API.streamSetState,
      { code: record.code, state: nextState },
      nextState === 1 ? '启用成功' : '停用成功',
    );
  }, [postStreamAction]);

  const handleBatchProxy = useCallback(async (url) => {
    if (!selectedRowKeys.length) return;
    await postStreamAction(url, { codes: selectedRowKeys.join(',') }, '批量转发操作完成');
    setSelectedRowKeys([]);
  }, [postStreamAction, selectedRowKeys]);

  const refreshForwardState = useCallback(async () => {
    try {
      const res = await apiGet(API.streamGetAllUpdateForwardState);
      message.success(res?.msg || '转发状态已刷新');
      run(params);
    } catch (e) {
      message.error(e?.message || '刷新失败');
    }
  }, [message, params, run]);

  const startAllForward = useCallback(async () => {
    try {
      const res = await apiGet(API.streamGetAllStartForward);
      message.success(res?.msg || '已请求全部启动转发');
      run(params);
    } catch (e) {
      message.error(e?.message || '操作失败');
    }
  }, [message, params, run]);

  const toggleAutoStart = useCallback(async (checked) => {
    setAutoStartLoading(true);
    try {
      await apiPost(API.streamSetAutoStartConfig, { auto_start: checked ? '1' : '0' });
      setAutoStart(checked);
      message.success('自动转发配置已更新');
    } catch (e) {
      message.error(e?.message || '保存失败');
    } finally {
      setAutoStartLoading(false);
    }
  }, [message]);

  const submitImport = useCallback(async () => {
    if (!importFile) {
      message.warning('请选择导入文件');
      return;
    }
    setImportSubmitting(true);
    try {
      const form = new FormData();
      form.append('file', importFile);
      const res = await apiPostForm(API.streamBatchImport, form);
      message.success(res?.msg || '批量导入完成');
      setImportOpen(false);
      setImportFile(null);
      run(params);
    } catch (e) {
      message.error(e?.message || '导入失败');
    } finally {
      setImportSubmitting(false);
    }
  }, [importFile, message, params, run]);

  const openSelfcheck = useCallback(async (record) => {
    setSelfcheckOpen(true);
    setSelfcheckLoading(true);
    setSelfcheckPayload(null);
    try {
      const res = await apiGet(API.streamWebrtcSelfCheck, {
        app: record.app,
        name: record.name,
      });
      setSelfcheckPayload(res || {});
    } catch (e) {
      message.error(e?.message || 'WebRTC 自检失败');
    } finally {
      setSelfcheckLoading(false);
    }
  }, [message]);

  const openTalkback = useCallback(async (record) => {
    setTalkbackRecord(record);
    setTalkbackOpen(true);
    setTalkbackLoading(true);
    setTalkbackStatusPayload(null);
    setTalkbackStateText('正在加载回讲配置...');
    try {
      const res = await apiPost(API.talkbackConfigGet, { stream_code: record.code });
      talkbackForm.setFieldsValue({
        ...TALKBACK_DEFAULTS,
        ...res,
        onvif_password: '',
      });
      setTalkbackStateText(res?.enabled ? '配置已启用，待启动。' : '该流 talkback 配置未启用。');
    } catch (e) {
      message.error(e?.message || '加载回讲配置失败');
      setTalkbackStateText('回讲配置加载失败。');
    } finally {
      setTalkbackLoading(false);
    }
  }, [message, talkbackForm]);

  const saveTalkbackConfig = useCallback(async () => {
    if (!talkbackRecord) return;
    setTalkbackSubmitting(true);
    try {
      const values = await talkbackForm.validateFields();
      await apiPost(API.talkbackConfigSave, {
        stream_code: talkbackRecord.code,
        ...values,
      });
      message.success('回讲配置已保存');
      setTalkbackStateText(values.enabled ? '配置已启用，待启动。' : '配置已保存但未启用。');
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '保存回讲配置失败');
    } finally {
      setTalkbackSubmitting(false);
    }
  }, [message, talkbackForm, talkbackRecord]);

  const refreshTalkbackStatus = useCallback(async () => {
    if (!talkbackRecord) return;
    try {
      const res = await apiGet(API.talkbackStatus, { session_id: buildTalkbackSessionId(talkbackRecord.code) });
      setTalkbackStatusPayload(res || {});
      setTalkbackStateText(`Relay 状态：${res?.state || (res?.active ? 'running' : 'unknown')}`);
    } catch (e) {
      message.error(e?.message || '查询回讲状态失败');
      setTalkbackStateText('回讲状态查询失败。');
    }
  }, [message, talkbackRecord]);

  const startTalkback = useCallback(async () => {
    if (!talkbackRecord) return;
    setTalkbackSubmitting(true);
    try {
      const res = await apiPost(API.talkbackStart, {
        stream_code: talkbackRecord.code,
        session_id: buildTalkbackSessionId(talkbackRecord.code),
      });
      setTalkbackStatusPayload(res || {});
      setTalkbackStateText('回讲已启动。');
      message.success('回讲启动请求已发送');
    } catch (e) {
      message.error(e?.message || '开启回讲失败');
      setTalkbackStateText('回讲启动失败。');
    } finally {
      setTalkbackSubmitting(false);
    }
  }, [message, talkbackRecord]);

  const stopTalkback = useCallback(async () => {
    if (!talkbackRecord) return;
    setTalkbackSubmitting(true);
    try {
      const res = await apiPost(API.talkbackStop, {
        session_id: buildTalkbackSessionId(talkbackRecord.code),
      });
      setTalkbackStatusPayload(res || {});
      setTalkbackStateText('回讲已停止。');
      message.success('回讲停止请求已发送');
    } catch (e) {
      message.error(e?.message || '停止回讲失败');
      setTalkbackStateText('停止回讲失败。');
    } finally {
      setTalkbackSubmitting(false);
    }
  }, [message, talkbackRecord]);

  const openPtz = useCallback((record) => {
    setPtzRecord(record);
    setPtzOpen(true);
    setPtzSpeed(32);
    setPtzPresetIndex(1);
  }, []);

  const sendPtzAction = useCallback(async (action) => {
    if (!ptzRecord) return;
    setPtzSubmitting(true);
    try {
      const body = {
        code: ptzRecord.code,
        action,
        speed: ptzSpeed,
      };
      if (action.startsWith('preset_')) {
        body.preset_index = ptzPresetIndex;
      }
      await apiPost(API.streamGb28181Ptz, body);
      message.success(`云台动作已发送: ${action}`);
    } catch (e) {
      message.error(e?.message || '云台控制失败');
    } finally {
      setPtzSubmitting(false);
    }
  }, [message, ptzPresetIndex, ptzRecord, ptzSpeed]);

  const openPusher = useCallback((record) => {
    setPusherRecord(record);
    setPusherOpen(true);
    setPusherResult(null);
    pusherForm.setFieldsValue({
      dst_host: '',
      dst_stream_app: record.app || 'live',
      dst_stream_name: record.name || record.code,
      dst_rtsp_port: 554,
    });
  }, [pusherForm]);

  const submitPusher = useCallback(async () => {
    if (!pusherRecord) return;
    setPusherSubmitting(true);
    try {
      const values = await pusherForm.validateFields();
      const res = await apiPost(API.streamAddPusherProxy, {
        stream_app: pusherRecord.app || 'live',
        stream_name: pusherRecord.name || pusherRecord.code,
        dst_host: values.dst_host,
        dst_stream_app: values.dst_stream_app,
        dst_stream_name: values.dst_stream_name,
        dst_rtsp_port: values.dst_rtsp_port,
      });
      setPusherResult(res || null);
      message.success(res?.msg || '转推代理已创建');
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '创建转推代理失败');
    } finally {
      setPusherSubmitting(false);
    }
  }, [message, pusherForm, pusherRecord]);

  const closeImport = useCallback(() => {
    setImportOpen(false);
    setImportFile(null);
  }, []);

  const columns = buildStreamColumns({
    onState: handleStateAction,
    onProxy: handleProxyAction,
    onSelfcheck: openSelfcheck,
    onTalkback: openTalkback,
    onPtz: openPtz,
    onPusher: openPusher,
    onDelete: handleDelete,
  });

  return (
    <div className="beacon-streams-page">
      <PageHeader
        title="视频流管理"
        icon={<VideoCameraOutlined />}
        description="视频流资源列表与状态概览"
        extra={
          <div className="beacon-streams-toolbar">
            <div className="beacon-streams-toolbar__group">
              <Button
                icon={<DeploymentUnitOutlined />}
                disabled={!selectedRowKeys.length}
                onClick={() => handleBatchProxy(API.streamBatchAddProxy)}
              >
                批量开启转发
              </Button>
              <Button disabled={!selectedRowKeys.length} onClick={() => handleBatchProxy(API.streamBatchDelProxy)}>
                批量停止转发
              </Button>
              <Button icon={<RadarChartOutlined />} onClick={refreshForwardState}>
                刷新转发状态
              </Button>
              <Button icon={<PlayCircleOutlined />} onClick={startAllForward}>
                全部启动转发
              </Button>
              <Button icon={<CloudUploadOutlined />} onClick={() => setImportOpen(true)}>
                批量导入
              </Button>
            </div>

            <div className="beacon-streams-toolbar__group beacon-streams-toolbar__group--tail">
              <div className="beacon-streams-toolbar__switch">
                <Text type="secondary" style={{ fontSize: 12 }}>自动转发</Text>
                <Switch checked={autoStart} loading={autoStartLoading} onChange={toggleAutoStart} />
              </div>
              <Button icon={<ReloadOutlined />} onClick={() => run(params)}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} href="/stream/add">
                添加视频流
              </Button>
            </div>
          </div>
        }
      />

      <div className="beacon-streams-overview">
        <StreamOverviewCard items={overviewItems} />
        <StreamMetricCard
          tone="slate"
          title="总计"
          meta="当前视频流数"
          value={totalStreams}
          footnote={rows.length ? `本页 ${rows.length} 路` : '当前页无返回条目'}
          aside={selectedSummary}
          icon={<VideoCameraOutlined />}
        />
        <StreamMetricCard
          tone="green"
          title="在线"
          meta="在线占比"
          value={onlineStreams}
          footnote={`${onlinePercent}% 在线率`}
          aside={totalStreams ? `共 ${totalStreams} 路` : '暂无在线样本'}
          icon={<PlayCircleOutlined />}
        />
        <StreamMetricCard
          tone="cyan"
          title="转发中"
          meta="代理链路占比"
          value={forwardingStreams}
          footnote={`${forwardingPercent}% 转发率`}
          aside={forwardingStreams ? `${forwardingStreams} 路代理转发` : '暂无代理链路'}
          icon={<DeploymentUnitOutlined />}
        />
      </div>

      <div className="beacon-streams-filter-shell">
        <FilterBar
          filters={filters}
          onSearch={handleSearch}
          onReset={handleReset}
          extra={<span className="beacon-streams-filter-meta">{selectedSummary}</span>}
        />
      </div>

      <Card
        className="beacon-panel-card beacon-panel-card--tone-slate beacon-streams-table-card"
        title={<PanelTitle title="视频流列表" meta="播放、转发、回讲、云台与代理动作" icon={<VideoCameraOutlined />} tone="slate" />}
        extra={(
          <div className="beacon-streams-table-card__meta">
            <span>{selectedSummary}</span>
            <span>当前返回 {totalStreams} 路</span>
          </div>
        )}
        size="small"
        styles={{ body: { padding: 0 } }}
      >
        <ProTable
          columns={columns}
          dataSource={rows}
          loading={loading}
          rowKey="code"
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
          }}
          pagination={{
            current: pageData.page || 1,
            pageSize: pageData.page_size || 20,
            total: pageData.count || 0,
          }}
          onChange={handleTableChange}
        />
      </Card>

      <StreamImportModal
        open={importOpen}
        file={importFile}
        submitting={importSubmitting}
        onClose={closeImport}
        onSubmit={submitImport}
        onFileChange={setImportFile}
      />
      <TalkbackConfigModal
        open={talkbackOpen}
        loading={talkbackLoading}
        submitting={talkbackSubmitting}
        record={talkbackRecord}
        stateText={talkbackStateText}
        statusPayload={talkbackStatusPayload}
        form={talkbackForm}
        onClose={() => setTalkbackOpen(false)}
        onRefreshStatus={refreshTalkbackStatus}
        onStop={stopTalkback}
        onStart={startTalkback}
        onSave={saveTalkbackConfig}
      />
      <PtzControlModal
        open={ptzOpen}
        record={ptzRecord}
        submitting={ptzSubmitting}
        speed={ptzSpeed}
        presetIndex={ptzPresetIndex}
        onClose={() => setPtzOpen(false)}
        onSpeedChange={setPtzSpeed}
        onPresetIndexChange={setPtzPresetIndex}
        onAction={sendPtzAction}
      />
      <PusherProxyModal
        open={pusherOpen}
        record={pusherRecord}
        form={pusherForm}
        submitting={pusherSubmitting}
        result={pusherResult}
        onClose={() => setPusherOpen(false)}
        onSubmit={submitPusher}
      />
      <StreamSelfcheckModal
        open={selfcheckOpen}
        loading={selfcheckLoading}
        payload={selfcheckPayload}
        onClose={() => setSelfcheckOpen(false)}
      />
    </div>
  );
}

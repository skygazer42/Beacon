import React, { useState, useCallback, useEffect } from 'react';
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Progress, Select, Space, Statistic, Switch, Tag, Tooltip, Typography } from 'antd';
import {
  AimOutlined,
  CopyOutlined,
  DeleteOutlined,
  FileTextOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import { API } from '../../api/endpoints';
import { apiGetRaw, apiPost } from '../../api/client';
import { formatTime } from '../../utils/format';
import { getBootstrapQuery } from '../../bootstrap';

const { Text } = Typography;

const STATE_MAP = {
  0: { color: 'default', text: '已停止' },
  1: { color: 'success', text: '运行中' },
  5: { color: 'warning', text: '中断/异常' },
};

function normalizeControlRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map(item => (Array.isArray(item) ? item[0] : item))
    .filter(Boolean)
    .map(row => ({
      ...row,
      state: row.cur_state ?? row.state,
      stream_label: row.stream_nickname || row.stream_name || '-',
      algorithm_label: row.flow_nickname || row.algorithm_code || '-',
      update_time: row.last_update_time || row.update_time,
    }));
}

export default function ControlsPage() {
  const { message } = App.useApp();
  const query = getBootstrapQuery();
  const [params, setParams] = useState({
    p: query.get('p') || 1,
    ps: query.get('ps') || 20,
    q: query.get('q') || '',
  });
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [listData, setListData] = useState({ rows: [], pageData: {}, stats: {}, topMsg: '' });
  const [quicksetOpen, setQuicksetOpen] = useState(false);
  const [quicksetSubmitting, setQuicksetSubmitting] = useState(false);
  const [quicksetTarget, setQuicksetTarget] = useState(null);
  const [batchCopyOpen, setBatchCopyOpen] = useState(false);
  const [batchCopySubmitting, setBatchCopySubmitting] = useState(false);
  const [quicksetForm] = Form.useForm();
  const [batchCopyForm] = Form.useForm();

  const rows = listData.rows || [];
  const pageData = listData.pageData || {};
  const stats = listData.stats || {};
  const topMsg = listData.topMsg || '';
  const totalControls = Number(stats.total ?? pageData.count ?? rows.length ?? 0) || 0;
  const runningControls = Number(stats.running ?? 0) || 0;
  const stoppedControls = Number(stats.stopped ?? 0) || 0;
  const errorControls = Number(stats.error ?? 0) || 0;
  const runningPercent = totalControls ? Math.round((runningControls / totalControls) * 100) : 0;
  const summaryItems = [
    { key: 'keyword', label: '搜索', value: params.q || '全部布控' },
    { key: 'selected', label: '已选择', value: `${selectedRowKeys.length} 项` },
    { key: 'page', label: '分页', value: `${pageData.page || params.p || 1} / ${pageData.page_size || params.ps || 20}` },
    { key: 'total', label: '总量', value: `${totalControls} 项` },
    { key: 'log', label: '日志导出', value: <a href={`${API.controlLogsExport}?format=json`} target="_blank" rel="noreferrer">JSON 导出</a> },
    { key: 'source', label: '来源', value: API.controlIndex },
  ];

  const loadControls = useCallback(async (overrideParams = params) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGetRaw(API.controlIndex, overrideParams);
      setListData({
        rows: normalizeControlRows(res?.data),
        pageData: res?.pageData || {},
        stats: res?.stats || {},
        topMsg: res?.top_msg || '',
      });
      return res;
    } catch (e) {
      setListData({ rows: [], pageData: {}, stats: {}, topMsg: '' });
      setError(e);
      return null;
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    loadControls(params);
  }, [loadControls, params]);

  const handleSearch = useCallback((filterValues) => {
    setParams(prev => ({ ...prev, ...filterValues, p: 1 }));
  }, []);

  const handleReset = useCallback(() => {
    setParams({ p: 1, ps: 20, q: '' });
  }, []);

  const handleTableChange = useCallback((pagination) => {
    setParams(prev => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const controlAction = useCallback(async (url, code) => {
    try {
      const form = new FormData();
      form.append('code', code);
      await apiPost(url, form);
      message.success('操作成功');
      loadControls(params);
    } catch (e) {
      message.error(e.message || '操作失败');
    }
  }, [params, loadControls, message]);

  const handleBatchAction = useCallback(async (url) => {
    try {
      const form = new FormData();
      selectedRowKeys.forEach(code => form.append('codes', code));
      await apiPost(url, form);
      message.success('批量操作成功');
      setSelectedRowKeys([]);
      loadControls(params);
    } catch (e) {
      message.error(e.message || '操作失败');
    }
  }, [selectedRowKeys, params, loadControls, message]);

  const openQuickset = (row) => {
    setQuicksetTarget(row);
    quicksetForm.setFieldsValue({
      decode_stride: row.decode_stride ?? 1,
      alarm_video_type: row.alarm_video_type || 'mp4',
      alarm_image_count: row.alarm_image_count ?? 3,
      alarm_image_draw_mode: row.alarm_image_draw_mode || 'boxed',
      restart: row.state === 1,
    });
    setQuicksetOpen(true);
  };

  const submitQuickset = async () => {
    if (!quicksetTarget) return;
    setQuicksetSubmitting(true);
    try {
      const values = await quicksetForm.validateFields();
      await apiPost(API.controlQuickSet, {
        code: quicksetTarget.code,
        decode_stride: values.decode_stride,
        alarm_video_type: values.alarm_video_type,
        alarm_image_count: values.alarm_image_count,
        alarm_image_draw_mode: values.alarm_image_draw_mode,
        restart: values.restart ? '1' : '0',
      });
      message.success('快捷设置已保存');
      setQuicksetOpen(false);
      loadControls(params);
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '快捷设置失败');
    } finally {
      setQuicksetSubmitting(false);
    }
  };

  const submitBatchCopy = async () => {
    const srcCode = selectedRowKeys[0];
    if (!srcCode) return;
    setBatchCopySubmitting(true);
    try {
      const values = await batchCopyForm.validateFields();
      const streamCodes = String(values.stream_codes || '')
        .split(/[\s,]+/)
        .map(item => item.trim())
        .filter(Boolean);
      await apiPost(API.controlBatchCopy, {
        src_code: srcCode,
        stream_codes: streamCodes.join(','),
        only_offline: values.only_offline ? '1' : '0',
      });
      message.success('批量复制请求已提交');
      setBatchCopyOpen(false);
      batchCopyForm.resetFields();
      loadControls(params);
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '批量复制失败');
    } finally {
      setBatchCopySubmitting(false);
    }
  };

  const filters = [
    { key: 'q', label: '搜索', type: 'input', placeholder: '编号/名称/流地址' },
  ];

  const columns = [
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
      render: (v) => <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip>,
    },
    {
      title: '视频流',
      dataIndex: 'stream_label',
      ellipsis: true,
    },
    {
      title: '算法',
      dataIndex: 'algorithm_label',
      width: 140,
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'state',
      width: 80,
      render: (v) => {
        const s = STATE_MAP[v] || { color: 'default', text: `${v}` };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '更新时间',
      dataIndex: 'update_time',
      width: 160,
      render: v => <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(v)}</Text>,
    },
    {
      title: '操作',
      width: 300,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          {r.state === 1 ? (
            <Button type="link" size="small" icon={<PauseCircleOutlined />} onClick={() => controlAction(API.controlStop, r.code)}>
              停止
            </Button>
          ) : (
            <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={() => controlAction(API.controlStart, r.code)}>
              启动
            </Button>
          )}
          <Button type="link" size="small" href={`/control/edit?code=${r.code}`}>
            编辑
          </Button>
          <Button type="link" size="small" icon={<SettingOutlined />} onClick={() => openQuickset(r)}>
            快捷设置
          </Button>
          <Button type="link" size="small" icon={<CopyOutlined />} onClick={() => controlAction(API.controlCopy, r.code)}>
            复制
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => controlAction(API.controlDel, r.code)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const rowSelection = {
    selectedRowKeys,
    onChange: setSelectedRowKeys,
    getCheckboxProps: () => ({ disabled: false }),
  };

  return (
    <div>
      <PageHeader
        title="布控管理"
        icon={<AimOutlined />}
        description="布控任务管理与状态监控"
        extra={
          <Space>
            <Button
              icon={<CopyOutlined />}
              disabled={selectedRowKeys.length !== 1}
              onClick={() => {
                batchCopyForm.setFieldsValue({ stream_codes: '', only_offline: true });
                setBatchCopyOpen(true);
              }}
            >
              批量复制到流
            </Button>
            <Button icon={<FileTextOutlined />} href="/control/logs">
              布控日志
            </Button>
            {selectedRowKeys.length > 0 && (
              <>
                <Button icon={<PlayCircleOutlined />} onClick={() => handleBatchAction(API.controlBatchStart)}>
                  批量启动 ({selectedRowKeys.length})
                </Button>
                <Button icon={<PauseCircleOutlined />} onClick={() => handleBatchAction(API.controlBatchStop)}>
                  批量停止
                </Button>
              </>
            )}
            <Button icon={<ReloadOutlined />} onClick={() => loadControls(params)}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} href="/control/add">添加布控</Button>
          </Space>
        }
      />

      {topMsg ? (
        <Alert
          showIcon
          type="info"
          style={{ marginBottom: 16 }}
          message={<span dangerouslySetInnerHTML={{ __html: topMsg }} />}
        />
      ) : null}

      <div className="beacon-support-grid beacon-equal-height-grid" data-layout="full-width" style={{ marginBottom: 16 }}>
        <SummaryCard title="布控概览" meta="筛选上下文与批量操作" icon={<AimOutlined />} tone="blue" items={summaryItems} />

        <Card
          className="beacon-panel-card beacon-panel-card--tone-green beacon-stat-panel"
          title={<PanelTitle title="运行中" meta="活跃布控占比" icon={<PlayCircleOutlined />} tone="green" />}
          size="small"
        >
          <Statistic value={runningControls} />
          <Progress percent={runningPercent} size="small" status={runningControls ? 'active' : 'normal'} />
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-cyan beacon-stat-panel"
          title={<PanelTitle title="已停止" meta="待启用布控" icon={<PauseCircleOutlined />} tone="cyan" />}
          size="small"
        >
          <Statistic value={stoppedControls} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            适合批量启动和复制扩容
          </Typography.Text>
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-orange beacon-stat-panel"
          title={<PanelTitle title="异常 / 中断" meta="需人工处理" icon={<SettingOutlined />} tone="orange" />}
          size="small"
        >
          <Statistic value={errorControls} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            快捷设置与日志导出保持原后端动作
          </Typography.Text>
        </Card>
      </div>

      <FilterBar
        filters={filters}
        onSearch={handleSearch}
        onReset={handleReset}
      />

      {error ? <Alert type="error" showIcon style={{ marginBottom: 16 }} message={error.message || '加载失败'} /> : null}

      <Card
        className="beacon-panel-card beacon-panel-card--tone-slate"
        title={<PanelTitle title="布控列表" meta="兼容历史 control index 契约" icon={<AimOutlined />} tone="slate" />}
        size="small"
        styles={{ body: { padding: 0 } }}
      >
        <ProTable
          columns={columns}
          dataSource={rows}
          loading={loading}
          rowKey="code"
          rowSelection={rowSelection}
          pagination={{
            current: pageData.page || 1,
            pageSize: pageData.page_size || 20,
            total: pageData.count || 0,
          }}
          onChange={handleTableChange}
        />
      </Card>

      <Modal
        title={quicksetTarget ? `快捷设置 - ${quicksetTarget.code}` : '快捷设置'}
        open={quicksetOpen}
        onCancel={() => setQuicksetOpen(false)}
        onOk={submitQuickset}
        okButtonProps={{ loading: quicksetSubmitting }}
        destroyOnHidden
      >
        <Form form={quicksetForm} layout="vertical">
          <Form.Item name="decode_stride" label="解码抽帧" rules={[{ required: true }]}>
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="alarm_video_type" label="报警视频类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'mp4', label: 'MP4' },
                { value: 'ts', label: 'TS' },
                { value: 'flv', label: 'FLV' },
                { value: 'none', label: '不生成' },
              ]}
            />
          </Form.Item>
          <Form.Item name="alarm_image_count" label="报警截图数量" rules={[{ required: true }]}>
            <InputNumber min={0} max={50} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="alarm_image_draw_mode" label="截图绘制模式" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'boxed', label: '框选' },
                { value: 'clean', label: '净图' },
                { value: 'both', label: '两者都要' },
              ]}
            />
          </Form.Item>
          <Form.Item name="restart" label="保存后重启布控" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={selectedRowKeys.length === 1 ? `批量复制到流 - ${selectedRowKeys[0]}` : '批量复制到流'}
        open={batchCopyOpen}
        onCancel={() => setBatchCopyOpen(false)}
        onOk={submitBatchCopy}
        okButtonProps={{ loading: batchCopySubmitting, disabled: selectedRowKeys.length !== 1 }}
        destroyOnHidden
      >
        <Form form={batchCopyForm} layout="vertical" initialValues={{ only_offline: true }}>
          <Form.Item
            name="stream_codes"
            label="目标视频流编号"
            rules={[{ required: true, message: '请输入至少一个流编号' }]}
            extra="支持逗号、空格或换行分隔多个流编号。"
          >
            <Input.TextArea rows={5} placeholder="stream-a, stream-b" />
          </Form.Item>
          <Form.Item name="only_offline" label="仅复制到未转发流" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

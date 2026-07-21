import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Card, Descriptions, Form, Input, Modal, Space, Spin, Switch, Typography } from 'antd';
import { CodeOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiGet, apiPost } from '../../api/client';

const { Text, Paragraph } = Typography;

function parseDetections(value) {
  const text = String(value || '').trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) {
      throw new TypeError('检测结果 JSON 必须是数组');
    }
    return parsed;
  } catch (e) {
    throw new Error(e?.message || '检测结果 JSON 不合法');
  }
}

export default function DeveloperPage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.developer);
  const [streamRows, setStreamRows] = useState([]);
  const [algoRows, setAlgoRows] = useState([]);
  const [directLoading, setDirectLoading] = useState(true);
  const [directError, setDirectError] = useState(null);
  const [callbackOpen, setCallbackOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [alarmSending, setAlarmSending] = useState(false);
  const [alarmTestResult, setAlarmTestResult] = useState('');
  const [alarmTestStatus, setAlarmTestStatus] = useState(null);
  const [callbackForm] = Form.useForm();
  const [alarmForm] = Form.useForm();
  const actions = data?.actions || {};
  const openApi = data?.open_api || {};
  const callbackAction = actions.algorithm_callback || API.developerAlgorithmCallback;
  const streamInfoAction = actions.stream_info || API.developerGetStreamInfo;
  const algorithmInfoAction = actions.algorithm_info || API.developerGetAlgorithmInfo;
  const alarmTestAction = actions.alarm_test || API.alarmOpenAdd;
  const alarmUploadAction = openApi.alarm_upload || '';

  const loadDirectInfo = useCallback(async () => {
    setDirectLoading(true);
    setDirectError(null);
    try {
      const [streams, algorithms] = await Promise.all([
        apiGet(streamInfoAction),
        apiGet(algorithmInfoAction),
      ]);
      setStreamRows(Array.isArray(streams) ? streams : []);
      setAlgoRows(Array.isArray(algorithms) ? algorithms : []);
    } catch (e) {
      setDirectError(e);
      setStreamRows([]);
      setAlgoRows([]);
    } finally {
      setDirectLoading(false);
    }
  }, [algorithmInfoAction, streamInfoAction]);

  useEffect(() => {
    loadDirectInfo();
  }, [loadDirectInfo]);

  const reloadAll = useCallback(() => {
    run();
    loadDirectInfo();
  }, [loadDirectInfo, run]);

  const actionItems = useMemo(() => {
    return Object.entries(actions).map(([key, url]) => ({
      key,
      label: key,
      children: (
        <Text copyable={{ text: String(url) }} style={{ fontSize: 12 }}>
          {url}
        </Text>
      ),
    }));
  }, [data?.actions]);

  const algorithms = algoRows.length || !directError ? algoRows : (data?.algorithms || []);
  const activeStreams = streamRows.length || !directError ? streamRows : (data?.active_streams || []);

  const algoColumns = [
    { title: '代码', dataIndex: 'code', width: 140, ellipsis: true },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '类型', dataIndex: 'type_name', width: 100 },
    {
      title: 'API',
      dataIndex: 'api_url',
      ellipsis: true,
      render: (v) =>
        v ? (
          <Text copyable={{ text: v }} style={{ fontSize: 11 }}>
            {v}
          </Text>
        ) : (
          '-'
        ),
    },
    {
      title: '直连',
      dataIndex: 'support_direct_api',
      width: 70,
      render: (v) => (v ? '是' : '否'),
    },
    { title: '行为 API 版本', dataIndex: 'behavior_api_version', width: 110 },
  ];

  const streamColumns = [
    { title: '布控', dataIndex: 'control_code', width: 120, ellipsis: true },
    { title: '流', dataIndex: 'stream_code', width: 140, ellipsis: true },
    { title: '算法', dataIndex: 'algorithm_code', width: 120, ellipsis: true },
    {
      title: 'RTSP',
      dataIndex: 'rtsp_url',
      ellipsis: true,
      render: (v) =>
        v ? (
          <Text copyable={{ text: v }} style={{ fontSize: 11 }}>
            {v}
          </Text>
        ) : (
          '-'
        ),
    },
  ];

  const openCallback = useCallback(() => {
    callbackForm.setFieldsValue({
      control_code: activeStreams[0]?.control_code || '',
      frame_index: 0,
      timestamp: 0,
      trigger_alarm: false,
      detections_json: '[]',
      image_base64: '',
    });
    setCallbackOpen(true);
  }, [activeStreams, callbackForm]);

  const submitCallback = useCallback(async () => {
    try {
      const values = await callbackForm.validateFields();
      const body = {
        control_code: String(values.control_code || '').trim(),
        frame_index: Number(values.frame_index || 0),
        timestamp: Number(values.timestamp || 0),
        trigger_alarm: Boolean(values.trigger_alarm),
        detections: parseDetections(values.detections_json),
      };
      const imageBase64 = String(values.image_base64 || '').trim();
      if (imageBase64) {
        body.image_base64 = imageBase64;
      }
      setSending(true);
      try {
        await apiPost(callbackAction, body);
        message.success('回调已发送');
        setCallbackOpen(false);
      } finally {
        setSending(false);
      }
    } catch (e) {
      if (!e?.errorFields) {
        message.error(e?.message || '发送失败');
      }
    }
  }, [callbackAction, callbackForm, message]);

  const submitAlarmTest = useCallback(async () => {
    try {
      const values = await alarmForm.validateFields();
      const payload = {
        control_code: String(values.control_code || '').trim(),
        desc: String(values.desc || '').trim() || '测试报警',
        video_path: String(values.video_path || '').trim(),
        image_path: String(values.image_path || '').trim(),
      };

      setAlarmSending(true);
      setAlarmTestStatus(null);
      try {
        const result = await apiPost(alarmTestAction, payload);
        setAlarmTestStatus('success');
        setAlarmTestResult(
          `请求数据:\n${JSON.stringify(payload, null, 2)}\n\n响应结果:\n${JSON.stringify(result, null, 2)}`,
        );
        message.success('报警测试请求已发送');
      } catch (e) {
        const errorResult = { message: e?.message || '请求失败' };
        setAlarmTestStatus('error');
        setAlarmTestResult(
          `请求数据:\n${JSON.stringify(payload, null, 2)}\n\n响应结果:\n${JSON.stringify(errorResult, null, 2)}`,
        );
        message.error(errorResult.message);
      } finally {
        setAlarmSending(false);
      }
    } catch (e) {
      if (!e?.errorFields) {
        message.error(e?.message || '提交失败');
      }
    }
  }, [alarmForm, alarmTestAction, message]);

  const clearAlarmTest = useCallback(() => {
    alarmForm.resetFields();
    setAlarmTestResult('');
    setAlarmTestStatus(null);
  }, [alarmForm]);

  return (
    <div>
      <PageHeader
        title="开发者工具"
        icon={<CodeOutlined />}
        description="开发者工具与调试"
        extra={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={reloadAll}>
              刷新
            </Button>
            <Button type="primary" icon={<SendOutlined />} onClick={openCallback}>
              发送回调
            </Button>
          </Space>
        )}
      />

      {error ? <Alert type="error" message={error.message || '加载失败'} style={{ marginBottom: 16 }} showIcon /> : null}
      {directError ? <Alert type="warning" message={directError.message || '直连开发者接口加载失败，当前显示兼容数据'} style={{ marginBottom: 16 }} showIcon /> : null}

      <Spin spinning={loading || directLoading}>
        <Card title="API 基址与版本" size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Paragraph style={{ marginBottom: 0 }}>
              <Text strong>Base URL: </Text>
              <Text copyable={{ text: data?.api_base_url || '' }}>{data?.api_base_url || '-'}</Text>
            </Paragraph>
            <Paragraph style={{ marginBottom: 0 }}>
              <Text strong>版本: </Text>
              {data?.version || '-'}
            </Paragraph>
          </Space>
        </Card>

        <Card title="常用端点" size="small" style={{ marginBottom: 16 }}>
          {actionItems.length ? (
            <Descriptions bordered size="small" column={1} items={actionItems} />
          ) : (
            <Text type="secondary">暂无</Text>
          )}
          {alarmUploadAction ? (
            <div style={{ marginTop: 12 }}>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>开放接口</Text>
              <Text copyable={{ text: alarmUploadAction }} style={{ fontSize: 12 }}>
                {alarmUploadAction}
              </Text>
              <Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 12 }}>
                `alarm_upload` 走 OpenAPI 入口，通常需要额外 token，不在当前 Web 会话内直接执行。
              </Text>
            </div>
          ) : null}
        </Card>

        <Card
          id="alarmApiTestTool"
          title="报警接口测试工具"
          size="small"
          style={{ marginBottom: 16 }}
          extra={<Text type="secondary" style={{ fontSize: 12 }}>{alarmTestAction}</Text>}
        >
          <Form
            form={alarmForm}
            layout="vertical"
            name="alarmApiTestForm"
            initialValues={{
              control_code: '',
              desc: '测试报警',
              video_path: '',
              image_path: '',
            }}
          >
            <Form.Item name="control_code" label="布控编号" rules={[{ required: true, message: '请输入布控编号' }]}>
              <Input placeholder={activeStreams[0]?.control_code || '例如 ctrl-demo-01'} autoComplete="off" />
            </Form.Item>
            <Form.Item name="desc" label="描述信息">
              <Input placeholder="测试报警" autoComplete="off" />
            </Form.Item>
            <Form.Item name="video_path" label="视频路径 (可选)">
              <Input placeholder="alarm/test/video.mp4" autoComplete="off" />
            </Form.Item>
            <Form.Item name="image_path" label="图片路径 (可选)">
              <Input placeholder="alarm/test/main.jpg" autoComplete="off" />
            </Form.Item>
            <Space wrap>
              <Button id="alarmApiTestSubmit" type="primary" loading={alarmSending} onClick={submitAlarmTest}>
                发送测试请求
              </Button>
              <Button id="alarmApiTestClear" onClick={clearAlarmTest}>
                清空
              </Button>
            </Space>
          </Form>
          {alarmTestResult ? (
            <div id="alarmApiTestResult" style={{ marginTop: 16 }}>
              <pre
                id="alarmApiTestResultContent"
                style={{
                  margin: 0,
                  maxHeight: 280,
                  overflow: 'auto',
                  padding: 12,
                  borderRadius: 8,
                  background: alarmTestStatus === 'error' ? '#fff2f0' : '#f6ffed',
                  border: `1px solid ${alarmTestStatus === 'error' ? '#ffccc7' : '#b7eb8f'}`,
                  fontSize: 12,
                  lineHeight: 1.5,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {alarmTestResult}
              </pre>
            </div>
          ) : null}
        </Card>

        <Card title="算法与 API 信息" size="small" style={{ marginBottom: 16 }}>
          <ProTable rowKey="code" columns={algoColumns} dataSource={algorithms} loading={loading || directLoading} pagination={{ pageSize: 10 }} />
        </Card>

        <Card title="运行中布控 / 流（直连）" size="small">
          <ProTable
            rowKey={(r) => `${r.control_code}-${r.stream_code}`}
            columns={streamColumns}
            dataSource={activeStreams}
            loading={loading || directLoading}
            pagination={{ pageSize: 10 }}
          />
        </Card>
      </Spin>

      <Modal
        title="模拟算法回调"
        open={callbackOpen}
        onCancel={() => setCallbackOpen(false)}
        onOk={submitCallback}
        okText="发送"
        confirmLoading={sending}
        destroyOnHidden
      >
        <Form form={callbackForm} layout="vertical" name="developerCallbackForm">
          <Form.Item name="control_code" label="布控编码" rules={[{ required: true, message: '请输入布控编码' }]}>
            <Input placeholder={activeStreams[0]?.control_code || '例如 ctrl-demo-01'} autoComplete="off" />
          </Form.Item>
          <Form.Item name="frame_index" label="帧序号">
            <Input type="number" />
          </Form.Item>
          <Form.Item name="timestamp" label="时间戳">
            <Input type="number" />
          </Form.Item>
          <Form.Item name="trigger_alarm" label="触发报警" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="detections_json" label="检测结果 JSON">
            <Input.TextArea rows={5} />
          </Form.Item>
          <Form.Item name="image_base64" label="截图 Base64">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

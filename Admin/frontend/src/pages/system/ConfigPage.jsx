import React, { useMemo, useState } from 'react';
import { Card, Spin, Alert, Descriptions, Button, Space, Typography, Upload, Select, Modal, Input, App } from 'antd';
import { SettingOutlined, ReloadOutlined, ImportOutlined, ExportOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost, apiPostForm, getCsrfToken } from '../../api/client';
import { getBootstrapPath } from '../../bootstrap';
import { formatTime } from '../../utils/format';

const { Text, Paragraph } = Typography;

async function downloadConfigExport(body) {
  const res = await fetch(API.configExport, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
    },
    body: JSON.stringify(body),
  });
  if (res.status === 401 || res.status === 403) {
    globalThis.location.href = '/login';
    return;
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const cd = res.headers.get('content-disposition') || '';
  const m = /filename="?([^";]+)"?/i.exec(cd);
  const name = m ? m[1] : 'beacon_config.json';
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ConfigPage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.config);
  const path = getBootstrapPath();
  const [mergeMode, setMergeMode] = useState('skip');
  const [previewText, setPreviewText] = useState('');
  const [systemJson, setSystemJson] = useState('');
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [rollbackId, setRollbackId] = useState('');

  const summary = data?.summary || {};
  const mergeOptions = data?.import_merge_modes?.options || [];

  const summaryItems = useMemo(
    () => [
      { key: 'algorithms', label: '启用算法数', children: String(summary.algorithm_count ?? '-') },
      { key: 'streams', label: '视频流数', children: String(summary.stream_count ?? '-') },
      { key: 'controls', label: '布控数', children: String(summary.control_count ?? '-') },
    ],
    [summary],
  );

  const history = data?.history || [];
  const historyColumns = [
    {
      title: '操作',
      key: 'rb',
      width: 100,
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => { setRollbackId(String(r.id)); setRollbackOpen(true); }}>
          回滚
        </Button>
      ),
    },
    { title: '快照 ID', dataIndex: 'id', width: 80 },
    { title: '标签', dataIndex: 'label', ellipsis: true },
    { title: '创建时间', dataIndex: 'create_time', width: 170, render: (v) => formatTime(v) },
    { title: '操作者', dataIndex: 'actor', width: 120, ellipsis: true },
  ];

  const valuesPreview = useMemo(() => {
    const v = data?.values;
    if (!v || typeof v !== 'object') return '{}';
    try {
      const text = JSON.stringify(v, null, 2);
      return text.length > 4000 ? `${text.slice(0, 4000)}\n…` : text;
    } catch {
      return String(v);
    }
  }, [data?.values]);

  React.useEffect(() => {
    if (data?.values && typeof data.values === 'object') {
      try {
        setSystemJson(JSON.stringify(data.values, null, 2));
      } catch {
        setSystemJson('{}');
      }
    }
  }, [data?.values]);

  const handleExport = async () => {
    try {
      await downloadConfigExport({ export_type: 'full', items: [] });
      message.success('导出已开始下载');
    } catch (e) {
      message.error(e?.message || '导出失败');
    }
  };

  const doPreview = async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await apiPostForm(API.configImportPreview, fd);
      setPreviewText(JSON.stringify(res, null, 2));
      message.success('预览完成');
    } catch (e) {
      message.error(e?.message || '预览失败');
    }
    return false;
  };

  const doImport = async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('merge_mode', mergeMode);
    try {
      await apiPostForm(API.configImport, fd);
      message.success('导入完成');
      run();
    } catch (e) {
      message.error(e?.message || '导入失败');
    }
    return false;
  };

  const doRollback = async () => {
    try {
      await apiPost(API.configRollback, { snapshot_id: Number(rollbackId), confirm: 'rollback' });
      message.success('回滚已执行');
      setRollbackOpen(false);
      run();
    } catch (e) {
      message.error(e?.message || '回滚失败');
    }
  };

  const saveSystem = async () => {
    try {
      const parsed = JSON.parse(systemJson || '{}');
      if (!parsed || typeof parsed !== 'object') {
        message.error('JSON 格式无效');
        return;
      }
      await apiPost(API.configSystemSave, parsed);
      message.success('系统配置已保存');
      run();
    } catch (e) {
      if (e instanceof SyntaxError) {
        message.error('JSON 解析失败');
        return;
      }
      message.error(e?.message || '保存失败');
    }
  };

  const showSystemPanel = path === '/config/system';

  return (
    <div>
      <PageHeader
        title="系统配置"
        icon={<SettingOutlined />}
        description="系统配置管理"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => run()}>
              刷新
            </Button>
            <Button icon={<ExportOutlined />} type="primary" onClick={handleExport}>
              导出
            </Button>
          </Space>
        }
      />

      {error ? <Alert type="error" message={error.message || '加载失败'} style={{ marginBottom: 16 }} showIcon /> : null}

      <Spin spinning={loading}>
        <Card title="日志导出" size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Button type="link" href={`${API.configLogExport}?include_stream_logs=0`}>
              导出基础日志包
            </Button>
            <Button type="link" href={`${API.configLogExport}?include_stream_logs=1`}>
              导出含流媒体日志
            </Button>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
            使用后端直连日志导出接口，按管理员权限校验后生成 ZIP 包。
          </Paragraph>
        </Card>

        <Card title="导入 / 预览" size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap>
              <Text type="secondary">合并策略</Text>
              <Select
                style={{ minWidth: 200 }}
                value={mergeMode}
                onChange={setMergeMode}
                options={mergeOptions.map((o) => ({ value: o.value, label: o.label }))}
              />
            </Space>
            <Space wrap>
              <Upload beforeUpload={doPreview} showUploadList={false} accept=".json,application/json">
                <Button icon={<ImportOutlined />}>预览</Button>
              </Upload>
              <Upload beforeUpload={doImport} showUploadList={false} accept=".json,application/json">
                <Button type="primary">导入 JSON</Button>
              </Upload>
            </Space>
            {previewText ? (
              <pre style={{ maxHeight: 240, overflow: 'auto', fontSize: 11, background: '#fafafa', padding: 12, borderRadius: 6 }}>
                {previewText}
              </pre>
            ) : (
              <Text type="secondary">选择文件后在此显示预览结果</Text>
            )}
          </Space>
        </Card>

        {showSystemPanel ? (
          <Card title="系统参数（JSON）" size="small" style={{ marginBottom: 16 }}>
            <Paragraph type="secondary" style={{ fontSize: 12 }}>
              编辑下方 JSON 后保存，将 POST 到系统配置接口（仅包含的键会更新）。
            </Paragraph>
            <Input.TextArea rows={14} value={systemJson} onChange={(e) => setSystemJson(e.target.value)} style={{ fontFamily: 'monospace', fontSize: 12 }} />
            <Button type="primary" style={{ marginTop: 12 }} onClick={saveSystem}>
              保存系统配置
            </Button>
          </Card>
        ) : null}

        <Card title="概要" size="small" style={{ marginBottom: 16 }}>
          <Descriptions bordered size="small" column={{ xs: 1, md: 3 }} items={summaryItems} />
        </Card>

        <Card title="配置值（摘要）" size="small" style={{ marginBottom: 16 }}>
          <Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
            完整上下文较大，此处仅展示 JSON 摘要。
          </Paragraph>
          <pre
            style={{
              maxHeight: 320,
              overflow: 'auto',
              fontSize: 11,
              background: '#fafafa',
              padding: 12,
              borderRadius: 6,
            }}
          >
            {valuesPreview}
          </pre>
        </Card>

        <Card title="历史快照" size="small" style={{ marginBottom: 16 }}>
          <ProTable
            rowKey={(r) => r.id ?? r.create_time}
            columns={historyColumns}
            dataSource={history}
            loading={loading}
            pagination={{ pageSize: 10 }}
          />
        </Card>

        <Card title="差异与合并" size="small">
          <Text type="secondary">
            已选快照与当前配置差异行数：{Array.isArray(data?.diff_rows) ? data.diff_rows.length : 0}。导入/合并模式：
            {data?.import_merge_modes && typeof data.import_merge_modes === 'object'
              ? ` ${Object.keys(data.import_merge_modes).join(', ')}`
              : ' 暂无'}
          </Text>
        </Card>
      </Spin>

      <Modal title="确认回滚" open={rollbackOpen} onOk={doRollback} onCancel={() => setRollbackOpen(false)} okText="回滚">
        <Text>将快照 {rollbackId} 应用到当前系统（需服务端校验 confirm）。</Text>
      </Modal>
    </div>
  );
}

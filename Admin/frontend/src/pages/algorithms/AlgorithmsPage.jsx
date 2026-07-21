import React, { useState, useCallback } from 'react';
import { Button, Space, Tag, Tooltip, Typography, App, Popconfirm, Modal, Select, Input } from 'antd';
import {
  ExperimentOutlined,
  PlusOutlined,
  ReloadOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';

const { Text } = Typography;

const ALGO_TYPE_MAP = {
  1: '检测算法',
  2: '分类算法',
  3: '行为算法',
};

const SOURCE_MAP = {
  builtin: '内置',
  custom: '自定义',
  upload: '上传',
};

export default function AlgorithmsPage() {
  const { message } = App.useApp();
  const [params, setParams] = useState({ p: 1, ps: 20 });
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorTitle, setEditorTitle] = useState('算法表单');
  const [editorUrl, setEditorUrl] = useState('about:blank');
  const [inferOpen, setInferOpen] = useState(false);
  const [inferTarget, setInferTarget] = useState(null);
  const [inferDevice, setInferDevice] = useState('CPU');
  const [inferFile, setInferFile] = useState(null);
  const [inferLoading, setInferLoading] = useState(false);
  const [inferResult, setInferResult] = useState(null);
  const { data, loading, run } = useApi(API.algorithms, params);

  const rows = data?.rows || [];
  const pageData = data?.pageData || {};

  const handleTableChange = useCallback((pagination) => {
    setParams(prev => ({ ...prev, p: pagination.current, ps: pagination.pageSize }));
  }, []);

  const openEditorModal = useCallback((url, title) => {
    setEditorTitle(title);
    setEditorUrl(url);
    setEditorOpen(true);
  }, []);

  const openAddModal = useCallback(() => {
    openEditorModal('/algorithm/add?popup=1', '添加算法');
  }, [openEditorModal]);

  const openEditModal = useCallback((code) => {
    openEditorModal(`/algorithm/edit?code=${encodeURIComponent(code)}&popup=1`, '编辑算法');
  }, [openEditorModal]);

  const handleEditorFrameLoad = useCallback((event) => {
    try {
      const href = event?.currentTarget?.contentWindow?.location?.href || '';
      if (!href) return;

      const url = new URL(href, globalThis.location.origin);
      if (url.pathname === '/algorithm/index') {
        setEditorOpen(false);
        setEditorUrl('about:blank');
        run(params);
      }
    } catch {
      // Ignore same-origin inspection failures while the frame is mid-navigation.
    }
  }, [params, run]);

  const openInferModal = useCallback((record) => {
    setInferTarget(record);
    setInferDevice('CPU');
    setInferFile(null);
    setInferResult(null);
    setInferOpen(true);
  }, []);

  const handleInferSubmit = useCallback(async () => {
    if (!inferTarget?.code) {
      message.warning('缺少算法编号');
      return;
    }
    if (!inferFile) {
      message.warning('请先选择测试图片');
      return;
    }

    const formData = new FormData();
    formData.append('code', inferTarget.code);
    formData.append('device', inferDevice || 'CPU');
    formData.append('image', inferFile);

    setInferLoading(true);
    try {
      const payload = await apiPost(API.algorithmTestInfer, formData);
      setInferResult(payload || null);
      message.success('测试完成');
    } catch (e) {
      message.error(e.message || '测试失败');
      setInferResult(null);
    } finally {
      setInferLoading(false);
    }
  }, [inferDevice, inferFile, inferTarget, message]);

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '编号',
      dataIndex: 'code',
      width: 140,
      ellipsis: true,
      render: v => <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip>,
    },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '类型',
      dataIndex: 'algorithm_type',
      width: 100,
      render: v => ALGO_TYPE_MAP[v] || `类型${v}`,
    },
    {
      title: '来源',
      dataIndex: 'basic_source',
      width: 80,
      render: v => SOURCE_MAP[v] || v || '-',
    },
    {
      title: '状态',
      dataIndex: 'state',
      width: 70,
      render: v => v === 1 ? <Tag color="success">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: '引用数',
      dataIndex: 'analyzer_ref_count',
      width: 70,
      render: v => v ?? 0,
    },
    {
      title: '操作',
      width: 200,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" href={`/algorithm/versions?code=${encodeURIComponent(r.code)}`}>版本</Button>
          <Button type="link" size="small" onClick={() => openEditModal(r.code)}>编辑</Button>
          <Button type="link" size="small" onClick={() => openInferModal(r)}>测试推理</Button>
          <Popconfirm
            title={`确定删除算法 ${r.code}？`}
            onConfirm={async () => {
              try {
                await apiPost(API.algorithmDel, { code: r.code });
                message.success('已删除');
                run(params);
              } catch (e) {
                message.error(e.message || '删除失败');
              }
            }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="算法管理"
        icon={<ExperimentOutlined />}
        description="算法模型管理与部署"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => run(params)}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openAddModal}>添加算法</Button>
          </Space>
        }
      />
      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey="id"
        pagination={{
          current: pageData.page || 1,
          pageSize: pageData.page_size || 20,
          total: pageData.count || 0,
        }}
        onChange={handleTableChange}
      />

      <Modal
        title={editorTitle}
        open={editorOpen}
        onCancel={() => {
          setEditorOpen(false);
          setEditorUrl('about:blank');
        }}
        footer={null}
        destroyOnHidden
        width={980}
      >
        <iframe
          title="算法表单"
          src={editorUrl}
          onLoad={handleEditorFrameLoad}
          style={{
            width: '100%',
            height: '72vh',
            border: 0,
            borderRadius: 8,
            background: '#fff',
          }}
        />
      </Modal>

      <Modal
        title="测试推理"
        open={inferOpen}
        onOk={handleInferSubmit}
        onCancel={() => setInferOpen(false)}
        confirmLoading={inferLoading}
        okText="开始测试"
        okButtonProps={{ 'aria-label': '开始测试' }}
        destroyOnHidden
        width={680}
      >
        <div style={{ display: 'grid', gap: 12 }}>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            当前算法：<strong>{inferTarget?.name || inferTarget?.code || '-'}</strong>
          </div>
          <div>
            <label htmlFor="algorithmInferDevice" style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>
              推理设备
            </label>
            <Select
              id="algorithmInferDevice"
              value={inferDevice}
              onChange={setInferDevice}
              options={[
                { value: 'CPU', label: 'CPU' },
                { value: 'GPU', label: 'GPU' },
                { value: 'TRT', label: 'TRT' },
                { value: 'AUTO', label: 'AUTO' },
                { value: 'NPU', label: 'NPU' },
              ]}
              style={{ width: '100%' }}
            />
          </div>
          <div>
            <label htmlFor="algorithmInferImage" style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>
              测试图片
            </label>
            <Input
              id="algorithmInferImage"
              aria-label="测试图片"
              type="file"
              accept="image/*"
              onChange={(e) => setInferFile(e.target.files?.[0] || null)}
            />
          </div>

          {inferResult ? (
            <div>
              <div style={{ marginBottom: 6, fontSize: 13, fontWeight: 600 }}>推理结果</div>
              <pre
                style={{
                  margin: 0,
                  padding: 12,
                  borderRadius: 8,
                  background: '#0f172a',
                  color: '#e2e8f0',
                  fontSize: 12,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(inferResult, null, 2)}
              </pre>
            </div>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}

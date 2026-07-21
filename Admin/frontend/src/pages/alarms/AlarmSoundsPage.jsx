import React, { useState, useCallback, useEffect, useMemo } from 'react';
import { Alert, App, Button, Card, Checkbox, Form, Input, Popconfirm, Space, Tag, Typography, Upload } from 'antd';
import { DeleteOutlined, InboxOutlined, SoundOutlined, StarOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiGet, apiPost, apiPostForm } from '../../api/client';

const { Text } = Typography;
const { Dragger } = Upload;

function hasValue(value) {
  return value != null;
}

export default function AlarmSoundsPage() {
  const { message } = App.useApp();
  const [params, setParams] = useState({ p: 1, ps: 20 });
  const { data, loading, run } = useApi(API.alarmSounds, params);
  const [directRows, setDirectRows] = useState([]);
  const [directLoading, setDirectLoading] = useState(true);
  const [directError, setDirectError] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadForm] = Form.useForm();

  const fallbackRows = data?.rows || [];
  const pageData = data?.pageData || {};

  const refreshDirectRows = useCallback(async () => {
    setDirectLoading(true);
    setDirectError(null);
    try {
      const rows = await apiGet(API.alarmSoundList);
      setDirectRows(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setDirectError(e);
      setDirectRows([]);
    } finally {
      setDirectLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshDirectRows();
  }, [refreshDirectRows]);

  const rows = useMemo(() => {
    let sourceRows = directRows;
    if (directError) {
      sourceRows = directRows.length ? directRows : fallbackRows;
    }
    const fallbackById = new Map(
      (Array.isArray(fallbackRows) ? fallbackRows : [])
        .filter((row) => hasValue(row?.id))
        .map((row) => [String(row.id), row]),
    );
    return (Array.isArray(sourceRows) ? sourceRows : []).map((row, index) => {
      const fallback = hasValue(row?.id) ? fallbackById.get(String(row.id)) : null;
      return {
        ...fallback,
        ...row,
        _rowKey: row?.id ?? fallback?.id ?? index,
      };
    });
  }, [directError, directRows, fallbackRows]);

  const handleTableChange = useCallback((pagination) => {
    setParams((prev) => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const postSoundAction = useCallback(
    async (url, id) => {
      try {
        const form = new FormData();
        form.append('id', String(id));
        await apiPost(url, form);
        message.success('操作成功');
        refreshDirectRows();
        run(params);
      } catch (e) {
        message.error(e.message || '操作失败');
      }
    },
    [params, refreshDirectRows, run, message],
  );

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 160,
      ellipsis: true,
    },
    {
      title: '文件路径',
      dataIndex: 'file_path',
      ellipsis: true,
      render: (v) => <Text style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    {
      title: '时长(秒)',
      dataIndex: 'duration',
      width: 100,
      render: (v) => (v == null || v === '' ? '-' : Number(v).toFixed(2)),
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      width: 90,
      render: (v) =>
        v ? <Tag color="blue">默认</Tag> : <Tag>否</Tag>,
    },
    {
      title: '备注',
      dataIndex: 'remark',
      ellipsis: true,
      render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      fixed: 'right',
      render: (_, row) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<StarOutlined />}
            disabled={row.is_default}
            aria-label={row.is_default ? '当前默认' : '设为默认'}
            onClick={() => postSoundAction(API.alarmSoundSetDefault, row.id)}
          >
            设为默认
          </Button>
          <Popconfirm
            title="确认删除该告警声音？"
            onConfirm={() => postSoundAction(API.alarmSoundDelete, row.id)}
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
      <PageHeader title="告警声音管理" description="告警提示音管理与配置" icon={<SoundOutlined />} />

      {directError ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={directError.message || '直连接口加载失败，当前显示兼容列表'}
        />
      ) : null}

      <Card size="small" title="上传告警音" style={{ marginBottom: 16 }}>
        <Form form={uploadForm} layout="vertical" style={{ maxWidth: 480 }}>
          <Form.Item name="name" label="名称（可选，默认取文件名）">
            <Input placeholder="显示名称" />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="is_default" valuePropName="checked">
            <Checkbox>设为默认</Checkbox>
          </Form.Item>
        </Form>
        <Dragger
          name="sound_file"
          multiple={false}
          showUploadList={false}
          disabled={uploading}
          customRequest={async ({ file, onError, onSuccess }) => {
            setUploading(true);
            try {
              const v = uploadForm.getFieldsValue();
              const fd = new FormData();
              fd.append('sound_file', file);
              fd.append('name', (v.name || '').trim());
              fd.append('remark', (v.remark || '').trim());
              fd.append('is_default', v.is_default ? '1' : '0');
              await apiPostForm(API.alarmSoundUpload, fd);
              message.success('上传成功');
              onSuccess?.({}, file);
              uploadForm.resetFields();
              refreshDirectRows();
              run(params);
            } catch (e) {
              message.error(e?.message || '上传失败');
              onError?.(e);
            } finally {
              setUploading(false);
            }
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽音频到此处上传</p>
          <p className="ant-upload-hint">支持 MP3 / WAV / OGG / M4A / AAC</p>
        </Dragger>
      </Card>

      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading || directLoading}
        rowKey={(row) => row._rowKey ?? row.id}
        pagination={{
          current: pageData.page || 1,
          pageSize: pageData.page_size || 20,
          total: pageData.count || 0,
        }}
        onChange={handleTableChange}
      />
    </div>
  );
}

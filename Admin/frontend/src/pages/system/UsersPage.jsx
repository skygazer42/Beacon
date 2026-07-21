import React, { useState, useCallback } from 'react';
import { App, Button, Checkbox, Form, Input, Modal, Popconfirm, Space, Switch, Tag, Typography } from 'antd';
import { TeamOutlined, ReloadOutlined, EditOutlined, PoweroffOutlined, UserAddOutlined, DeleteOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost, apiPostForm } from '../../api/client';
import { formatTime } from '../../utils/format';

const { Text } = Typography;

export default function UsersPage() {
  const { message } = App.useApp();
  const [params, setParams] = useState({ p: 1, ps: 20, keyword: '', status: '', user_type: '' });
  const { data, loading, error, run } = useApi(API.users, params);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [permissionOpen, setPermissionOpen] = useState(false);
  const [permissionLoading, setPermissionLoading] = useState(false);
  const [permissionSaving, setPermissionSaving] = useState(false);
  const [permissionUser, setPermissionUser] = useState(null);
  const [permissionValues, setPermissionValues] = useState({});
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const rows = data?.rows || [];
  const pageData = data?.pageData || {};
  const permissionMeta = data?.permission_meta || [];

  const handleTableChange = useCallback((pagination) => {
    setParams((prev) => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const handleToggle = useCallback(
    async (userId) => {
      try {
        const form = new FormData();
        form.append('user_id', String(userId));
        await apiPostForm(API.userToggleStatus, form);
        message.success('状态已切换');
        run(params);
      } catch (e) {
        message.error(e.message || '操作失败');
      }
    },
    [message, params, run],
  );

  const submitCreate = async () => {
    try {
      const v = await createForm.validateFields();
      await apiPost(API.userCreate, {
        username: v.username,
        password: v.password,
        email: v.email || '',
        first_name: v.first_name || '',
        last_name: v.last_name || '',
        is_staff: Boolean(v.is_staff),
        is_superuser: Boolean(v.is_superuser),
        is_active: v.is_active !== false,
      });
      message.success('用户已创建');
      setCreateOpen(false);
      createForm.resetFields();
      run(params);
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '创建失败');
    }
  };

  const openEdit = (r) => {
    setEditing(r);
    editForm.setFieldsValue({
      email: r.email || '',
      first_name: r.first_name || '',
      last_name: r.last_name || '',
      is_staff: Boolean(r.is_staff),
      is_superuser: Boolean(r.is_superuser),
      is_active: Boolean(r.is_active),
      password: '',
    });
    setEditOpen(true);
  };

  const submitEdit = async () => {
    try {
      const v = await editForm.validateFields();
      const body = {
        user_id: editing.id,
        email: v.email || '',
        first_name: v.first_name || '',
        last_name: v.last_name || '',
        is_staff: Boolean(v.is_staff),
        is_superuser: Boolean(v.is_superuser),
        is_active: v.is_active !== false,
      };
      if (v.password && String(v.password).trim()) {
        body.password = String(v.password).trim();
      }
      await apiPost(API.userEdit, body);
      message.success('已保存');
      setEditOpen(false);
      setEditing(null);
      run(params);
    } catch (e) {
      if (e?.errorFields) return;
      message.error(e?.message || '保存失败');
    }
  };

  const deleteOne = async (id) => {
    try {
      await apiPost(API.userDelete, { user_id: id });
      message.success('已删除');
      run(params);
    } catch (e) {
      message.error(e?.message || '删除失败');
    }
  };

  const batchDelete = async () => {
    const ids = selectedRowKeys.map(Number).filter((n) => n > 0);
    if (!ids.length) return;
    try {
      await apiPost(API.userBatchDelete, { user_ids: ids });
      message.success('批量删除完成');
      setSelectedRowKeys([]);
      run(params);
    } catch (e) {
      message.error(e?.message || '批量删除失败');
    }
  };

  const openPermissions = async (row) => {
    setPermissionUser(row);
    setPermissionOpen(true);
    setPermissionLoading(true);
    try {
      const res = await apiPost(API.userPermissions, { user_id: row.id });
      const incoming = res?.permissions || {};
      const keys = new Set([
        ...permissionMeta.map(item => item.key),
        ...(res?.permission_keys || []),
        ...Object.keys(incoming),
      ]);
      const next = {};
      keys.forEach((key) => {
        next[key] = Boolean(incoming[key]);
      });
      setPermissionValues(next);
    } catch (e) {
      message.error(e?.message || '权限加载失败');
    } finally {
      setPermissionLoading(false);
    }
  };

  const submitPermissions = async () => {
    if (!permissionUser) return;
    setPermissionSaving(true);
    try {
      await apiPost(API.userSetPermissions, {
        user_id: permissionUser.id,
        permissions_json: JSON.stringify(permissionValues),
      });
      message.success('权限已保存');
      setPermissionOpen(false);
    } catch (e) {
      message.error(e?.message || '权限保存失败');
    } finally {
      setPermissionSaving(false);
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '用户名', dataIndex: 'username', ellipsis: true },
    {
      title: '启用',
      dataIndex: 'is_active',
      width: 90,
      render: (v) => (v ? <Tag color="success">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '管理员',
      dataIndex: 'is_staff',
      width: 90,
      render: (v) => (v ? <Tag color="blue">是</Tag> : <Tag>否</Tag>),
    },
    { title: '最后登录', dataIndex: 'last_login', width: 170, render: (v) => (v === 'never' ? '从未' : formatTime(v)) },
    { title: '注册时间', dataIndex: 'date_joined', width: 170, render: (v) => formatTime(v) },
    {
      title: '操作',
      key: 'actions',
      width: 320,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Button type="link" size="small" onClick={() => openPermissions(r)}>
            权限
          </Button>
          <Popconfirm title={`确定删除用户 ${r.username}？`} onConfirm={() => deleteOne(r.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} disabled={data?.current_user_id === r.id}>
              删除
            </Button>
          </Popconfirm>
          <Button
            type="link"
            size="small"
            icon={<PoweroffOutlined />}
            onClick={() => handleToggle(r.id)}
            disabled={data?.current_user_id === r.id}
          >
            切换状态
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="用户管理"
        icon={<TeamOutlined />}
        description="用户账号管理"
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => run(params)}>
              刷新
            </Button>
            <Button type="primary" icon={<UserAddOutlined />} onClick={() => setCreateOpen(true)}>
              新建用户
            </Button>
            <Popconfirm title={`确定删除选中的 ${selectedRowKeys.length} 个用户？`} disabled={!selectedRowKeys.length} onConfirm={batchDelete}>
              <Button danger disabled={!selectedRowKeys.length}>
                批量删除
              </Button>
            </Popconfirm>
          </Space>
        }
      />

      {error ? <div style={{ color: '#dc2626', marginBottom: 12 }}>{error.message}</div> : null}

      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey="id"
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
          getCheckboxProps: (r) => ({ disabled: data?.current_user_id === r.id }),
        }}
        pagination={{
          current: pageData.page || 1,
          pageSize: pageData.page_size || 20,
          total: pageData.count || 0,
        }}
        onChange={handleTableChange}
      />

      <Modal title="新建用户" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={submitCreate} destroyOnHidden>
        <Form form={createForm} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="email" label="邮箱">
            <Input />
          </Form.Item>
          <Form.Item name="first_name" label="名">
            <Input />
          </Form.Item>
          <Form.Item name="last_name" label="姓">
            <Input />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked" initialValue>
            <Switch />
          </Form.Item>
          <Form.Item name="is_staff" label="管理员" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_superuser" label="超级用户" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`编辑用户 — ${editing?.username || ''}`} open={editOpen} onCancel={() => setEditOpen(false)} onOk={submitEdit} destroyOnHidden>
        <Form form={editForm} layout="vertical">
          <Form.Item name="email" label="邮箱">
            <Input />
          </Form.Item>
          <Form.Item name="first_name" label="名">
            <Input />
          </Form.Item>
          <Form.Item name="last_name" label="姓">
            <Input />
          </Form.Item>
          <Form.Item name="password" label="新密码（留空不修改）">
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_staff" label="管理员" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_superuser" label="超级用户" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={permissionUser ? `权限配置 - ${permissionUser.username}` : '权限配置'}
        open={permissionOpen}
        onCancel={() => setPermissionOpen(false)}
        onOk={submitPermissions}
        okButtonProps={{ loading: permissionSaving }}
        destroyOnHidden
      >
        {permissionLoading ? (
          <Text type="secondary">正在加载权限...</Text>
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {permissionMeta.map((item) => (
              <div key={item.key} style={{ paddingBottom: 8, borderBottom: '1px solid #f0f0f0' }}>
                <Checkbox
                  checked={Boolean(permissionValues[item.key])}
                  onChange={(e) => setPermissionValues(prev => ({ ...prev, [item.key]: e.target.checked }))}
                >
                  {item.name}
                </Checkbox>
                {item.desc ? (
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {item.desc}
                    </Text>
                  </div>
                ) : null}
              </div>
            ))}
            {permissionMeta.length ? null : <Text type="secondary">当前后端未返回权限元数据。</Text>}
          </Space>
        )}
      </Modal>
    </div>
  );
}

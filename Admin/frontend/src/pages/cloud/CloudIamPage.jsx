import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Card, Form, Input, Modal, Select, Space, Switch, Typography } from 'antd';
import { PlusOutlined, TeamOutlined } from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import StatusBadge from '../../components/StatusBadge';
import useApi from '../../hooks/useApi';
import { apiPostForm } from '../../api/client';
import { API } from '../../api/endpoints';

const { Text } = Typography;

function permissionFieldName(meta) {
  const explicit = String(meta?.field || '').trim();
  if (explicit) return explicit;
  return `perm_${String(meta?.key || '').replaceAll('.', '_')}`;
}

function appendBooleanField(formData, key, value) {
  if (value) {
    formData.append(key, '1');
  }
}

function buildBrandingValues(tenant) {
  const branding = tenant?.branding || {};
  return {
    tenant_id: tenant?.id,
    site_name: branding.siteName || '',
    site_title: branding.siteTitle || '',
    site_logo: branding.siteLogo || '',
    login_bg: branding.loginBg || '',
    theme_color: branding.themeColor || '',
  };
}

function formatScope(resourceScope, clusterNameById) {
  const ids = Array.isArray(resourceScope?.edge_cluster_ids)
    ? resourceScope.edge_cluster_ids
        .map(Number)
        .filter((item) => Number.isFinite(item) && item > 0)
    : [];

  if (!ids.length) return '租户内全可见';

  return ids
    .map((id) => {
      const name = clusterNameById.get(id);
      return name ? `${name} (#${id})` : `#${id}`;
    })
    .join('，');
}

export default function CloudIamPage() {
  const { message } = App.useApp();
  const { data, loading, run } = useApi(API.cloudIam);

  const [tenantModalOpen, setTenantModalOpen] = useState(false);
  const [roleModalOpen, setRoleModalOpen] = useState(false);
  const [roleEditing, setRoleEditing] = useState(null);
  const [membershipModalOpen, setMembershipModalOpen] = useState(false);
  const [membershipEditing, setMembershipEditing] = useState(null);
  const [brandingTenantId, setBrandingTenantId] = useState(null);

  const [tenantForm] = Form.useForm();
  const [roleForm] = Form.useForm();
  const [membershipForm] = Form.useForm();
  const [brandingForm] = Form.useForm();

  const accessOk = data?.access_ok !== false;
  const tenants = data?.tenants || [];
  const roles = data?.roles || [];
  const memberships = data?.memberships || [];
  const users = data?.users || [];
  const clusters = data?.clusters || [];
  const permissionMeta = data?.permission_meta || [];

  const reload = useCallback(() => run(), [run]);

  const submitAction = useCallback(
    async (formData, okMsg) => {
      try {
        await apiPostForm(API.cloudIamAction, formData);
        message.success(okMsg || '操作成功');
        await reload();
        return true;
      } catch (e) {
        message.error(e?.message || '操作失败');
        return false;
      }
    },
    [message, reload],
  );

  const tenantOptions = useMemo(
    () => tenants.map((tenant) => ({ value: tenant.id, label: `${tenant.name || tenant.slug} (${tenant.slug})` })),
    [tenants],
  );

  const userOptions = useMemo(
    () => users.map((user) => ({ value: user.id, label: user.username })),
    [users],
  );

  const clusterNameById = useMemo(() => {
    const mapping = new Map();
    clusters.forEach((cluster) => {
      mapping.set(Number(cluster.id), cluster.name || `集群 #${cluster.id}`);
    });
    return mapping;
  }, [clusters]);

  const clusterScopeOptions = useMemo(
    () =>
      clusters.map((cluster) => ({
        value: Number(cluster.id),
        label: `${cluster.name || `集群 #${cluster.id}`} (#${cluster.id})`,
      })),
    [clusters],
  );

  const roleOptions = useMemo(
    () =>
      roles.map((role) => ({
        value: role.id,
        label: `${role.tenant_slug || '-'} / ${role.key} (${role.name})`,
        tenantId: role.tenant_id,
      })),
    [roles],
  );

  const membershipTenantId = Form.useWatch('tenant_id', membershipForm);
  const filteredRoleOptions = useMemo(() => {
    const tenantId = Number(membershipTenantId || membershipEditing?.tenant_id || 0);
    if (!tenantId) return roleOptions;
    return roleOptions.filter((item) => Number(item.tenantId) === tenantId);
  }, [membershipEditing?.tenant_id, membershipTenantId, roleOptions]);

  useEffect(() => {
    if (brandingTenantId || !tenantOptions.length) return;
    setBrandingTenantId(tenantOptions[0].value);
  }, [brandingTenantId, tenantOptions]);

  const selectedBrandingTenant = useMemo(
    () => tenants.find((tenant) => Number(tenant.id) === Number(brandingTenantId)) || null,
    [brandingTenantId, tenants],
  );

  useEffect(() => {
    if (!selectedBrandingTenant) {
      brandingForm.resetFields();
      return;
    }
    brandingForm.setFieldsValue(buildBrandingValues(selectedBrandingTenant));
  }, [brandingForm, selectedBrandingTenant]);

  const openCreateTenant = useCallback(() => {
    tenantForm.resetFields();
    setTenantModalOpen(true);
  }, [tenantForm]);

  const submitTenant = useCallback(async () => {
    try {
      const values = await tenantForm.validateFields();
      const formData = new FormData();
      formData.append('action', 'create_tenant');
      formData.append('slug', String(values.slug || '').trim());
      formData.append('name', String(values.name || '').trim());
      const ok = await submitAction(formData, '租户已保存');
      if (ok) setTenantModalOpen(false);
    } catch (e) {
      if (!e?.errorFields) throw e;
    }
  }, [submitAction, tenantForm]);

  const handleToggleTenant = useCallback(
    async (tenantId) => {
      const formData = new FormData();
      formData.append('action', 'toggle_tenant');
      formData.append('tenant_id', String(tenantId));
      await submitAction(formData, '租户状态已更新');
    },
    [submitAction],
  );

  const submitBranding = useCallback(async () => {
    try {
      const values = await brandingForm.validateFields();
      const formData = new FormData();
      formData.append('action', 'set_tenant_branding');
      formData.append('tenant_id', String(values.tenant_id));
      [
        ['site_name', values.site_name],
        ['site_title', values.site_title],
        ['site_logo', values.site_logo],
        ['login_bg', values.login_bg],
        ['theme_color', values.theme_color],
      ].forEach(([key, value]) => {
        const normalized = String(value || '').trim();
        if (normalized) {
          formData.append(key, normalized);
        }
      });
      await submitAction(formData, '租户白标已保存');
    } catch (e) {
      if (!e?.errorFields) throw e;
    }
  }, [brandingForm, submitAction]);

  const openCreateRole = useCallback(() => {
    setRoleEditing(null);
    const permissions = {};
    permissionMeta.forEach((meta) => {
      permissions[meta.key] = false;
    });
    roleForm.resetFields();
    roleForm.setFieldsValue({
      tenant_id: tenantOptions[0]?.value,
      key: '',
      name: '',
      enabled: true,
      permissions,
    });
    setRoleModalOpen(true);
  }, [permissionMeta, roleForm, tenantOptions]);

  const openEditRole = useCallback(
    (role) => {
      setRoleEditing(role);
      const permissions = {};
      permissionMeta.forEach((meta) => {
        permissions[meta.key] = Boolean(role?.permissions?.[meta.key]);
      });
      roleForm.setFieldsValue({
        tenant_id: role.tenant_id,
        key: role.key,
        name: role.name,
        enabled: role.enabled,
        permissions,
      });
      setRoleModalOpen(true);
    },
    [permissionMeta, roleForm],
  );

  const submitRole = useCallback(async () => {
    try {
      const values = await roleForm.validateFields();
      const formData = new FormData();
      formData.append('action', 'upsert_role');
      formData.append('tenant_id', String(values.tenant_id));
      formData.append('key', String(values.key || '').trim());
      formData.append('name', String(values.name || '').trim());
      appendBooleanField(formData, 'enabled', Boolean(values.enabled));
      permissionMeta.forEach((meta) => {
        appendBooleanField(formData, permissionFieldName(meta), Boolean(values.permissions?.[meta.key]));
      });
      const ok = await submitAction(formData, roleEditing ? '角色已更新' : '角色已创建');
      if (ok) setRoleModalOpen(false);
    } catch (e) {
      if (!e?.errorFields) throw e;
    }
  }, [permissionMeta, roleEditing, roleForm, submitAction]);

  const openAddMembership = useCallback(() => {
    setMembershipEditing(null);
    membershipForm.resetFields();
    membershipForm.setFieldsValue({
      user_id: undefined,
      tenant_id: tenantOptions[0]?.value,
      role_id: undefined,
      enabled: true,
      is_default: false,
      edge_cluster_ids: [],
    });
    setMembershipModalOpen(true);
  }, [membershipForm, tenantOptions]);

  const openEditMembership = useCallback(
    (membership) => {
      setMembershipEditing(membership);
      const ids = Array.isArray(membership?.resource_scope?.edge_cluster_ids)
        ? membership.resource_scope.edge_cluster_ids.map(Number).filter((item) => Number.isFinite(item) && item > 0)
        : [];
      membershipForm.setFieldsValue({
        user_id: membership.user_id,
        tenant_id: membership.tenant_id,
        role_id: membership.role_id || undefined,
        enabled: membership.enabled,
        is_default: membership.is_default,
        edge_cluster_ids: ids,
      });
      setMembershipModalOpen(true);
    },
    [membershipForm],
  );

  const submitMembership = useCallback(async () => {
    try {
      const values = await membershipForm.validateFields();
      const rawClusterIds = Array.isArray(values.edge_cluster_ids)
        ? values.edge_cluster_ids
        : String(values.edge_cluster_ids || '').split(',');
      const edgeClusterCsv = rawClusterIds
        .map((item) => String(item).trim())
        .filter(Boolean)
        .join(',');

      const formData = new FormData();
      formData.append('action', 'upsert_membership');
      formData.append('user_id', String(values.user_id));
      formData.append('tenant_id', String(values.tenant_id));
      if (values.role_id) {
        formData.append('role_id', String(values.role_id));
      }
      appendBooleanField(formData, 'enabled', Boolean(values.enabled));
      appendBooleanField(formData, 'is_default', Boolean(values.is_default));
      if (edgeClusterCsv) {
        formData.append('edge_cluster_ids', edgeClusterCsv);
      }
      const ok = await submitAction(formData, membershipEditing ? '成员绑定已更新' : '成员绑定已创建');
      if (ok) setMembershipModalOpen(false);
    } catch (e) {
      if (!e?.errorFields) throw e;
    }
  }, [membershipEditing, membershipForm, submitAction]);

  const tenantColumns = [
    { title: 'ID', dataIndex: 'id', width: 72 },
    { title: 'Slug', dataIndex: 'slug', width: 180, ellipsis: true },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 88,
      render: (value) => <StatusBadge status={value ? 'enabled' : 'disabled'} />,
    },
    {
      title: '白标',
      key: 'branding',
      width: 200,
      ellipsis: true,
      render: (_, record) => record.branding?.siteName || record.branding?.siteTitle || '-',
    },
    {
      title: '操作',
      key: 'ops',
      width: 210,
      fixed: 'right',
      render: (_, record) => (
        <Space size={0} wrap>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setBrandingTenantId(record.id);
            }}
          >
            编辑白标
          </Button>
          <Button type="link" size="small" onClick={() => handleToggleTenant(record.id)}>
            {record.enabled ? '禁用' : '启用'}
          </Button>
        </Space>
      ),
    },
  ];

  const roleColumns = [
    { title: 'ID', dataIndex: 'id', width: 72 },
    { title: '租户', dataIndex: 'tenant_slug', width: 140, ellipsis: true },
    { title: 'Key', dataIndex: 'key', width: 180, ellipsis: true },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 88,
      render: (value) => <StatusBadge status={value ? 'enabled' : 'disabled'} />,
    },
    {
      title: '权限 JSON',
      dataIndex: 'permissions_json',
      ellipsis: true,
      render: (_, record) => record.permissions_json || JSON.stringify(record.permissions || {}),
    },
    {
      title: '操作',
      key: 'ops',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEditRole(record)}>
          编辑角色
        </Button>
      ),
    },
  ];

  const membershipColumns = [
    { title: 'ID', dataIndex: 'id', width: 72 },
    { title: '用户', dataIndex: 'username', width: 140, ellipsis: true },
    { title: '租户', dataIndex: 'tenant_slug', width: 140, ellipsis: true },
    { title: '角色', dataIndex: 'role_name', width: 140, ellipsis: true, render: (value) => value || '-' },
    { title: '角色 Key', dataIndex: 'role_key', width: 140, ellipsis: true, render: (value) => value || '-' },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 88,
      render: (value) => <StatusBadge status={value ? 'enabled' : 'disabled'} />,
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      width: 88,
      render: (value) => (value ? <StatusBadge status="success" text="是" /> : <Text type="secondary">否</Text>),
    },
    {
      title: '资源范围',
      key: 'scope',
      ellipsis: true,
      render: (_, record) => formatScope(record.resource_scope, clusterNameById),
    },
    {
      title: '操作',
      key: 'ops',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEditMembership(record)}>
          编辑绑定
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="云端权限管理"
        icon={<TeamOutlined />}
        description="身份与访问管理"
        extra={
          <Space wrap>
            <Button type="primary" icon={<PlusOutlined />} disabled={!accessOk} onClick={openCreateTenant}>
              新建租户
            </Button>
            <Button disabled={!accessOk} onClick={openCreateRole}>
              新建角色
            </Button>
            <Button disabled={!accessOk} onClick={openAddMembership}>
              添加绑定
            </Button>
          </Space>
        }
      />

      {!accessOk && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={data?.access_message || '需要管理员权限查看 IAM 数据'}
        />
      )}

      <Card
        size="small"
        title="租户"
        style={{ marginBottom: 16 }}
      >
        <ProTable
          columns={tenantColumns}
          dataSource={tenants}
          loading={loading}
          rowKey="id"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Card
        size="small"
        title="租户白标"
        style={{ marginBottom: 16 }}
        extra={selectedBrandingTenant ? <Text type="secondary">{selectedBrandingTenant.slug}</Text> : null}
      >
        <Form form={brandingForm} layout="vertical">
          <Form.Item name="tenant_id" label="租户" rules={[{ required: true, message: '请选择租户' }]}>
            <Select
              options={tenantOptions}
              showSearch
              optionFilterProp="label"
              disabled={!accessOk}
              onChange={(value) => setBrandingTenantId(value)}
            />
          </Form.Item>
          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <Form.Item name="site_name" label="site_name">
              <Input disabled={!accessOk} placeholder="Tenant A" />
            </Form.Item>
            <Form.Item name="site_title" label="site_title">
              <Input disabled={!accessOk} placeholder="Tenant A Console" />
            </Form.Item>
            <Form.Item name="site_logo" label="site_logo">
              <Input disabled={!accessOk} placeholder="/static/images/logo.png" />
            </Form.Item>
            <Form.Item name="login_bg" label="login_bg">
              <Input disabled={!accessOk} placeholder="/static/images/bg.png" />
            </Form.Item>
            <Form.Item name="theme_color" label="theme_color">
              <Input disabled={!accessOk} placeholder="#1677ff" />
            </Form.Item>
          </div>
          <Space>
            <Button type="primary" onClick={submitBranding} disabled={!accessOk}>
              保存白标
            </Button>
            <Text type="secondary">留空字段会回退到全局配置。</Text>
          </Space>
        </Form>
      </Card>

      <Card
        size="small"
        title="角色"
        style={{ marginBottom: 16 }}
      >
        <ProTable
          columns={roleColumns}
          dataSource={roles}
          loading={loading}
          rowKey="id"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Card
        size="small"
        title="成员绑定"
      >
        <ProTable
          columns={membershipColumns}
          dataSource={memberships}
          loading={loading}
          rowKey="id"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Modal
        title="新建租户"
        open={tenantModalOpen}
        onCancel={() => setTenantModalOpen(false)}
        onOk={submitTenant}
        destroyOnHidden
        okText="保存"
      >
        <Form form={tenantForm} layout="vertical">
          <Form.Item name="slug" label="Slug" rules={[{ required: true, message: '填写 tenant slug' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '填写 tenant 名称' }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={roleEditing ? '编辑角色' : '新建角色'}
        open={roleModalOpen}
        onCancel={() => setRoleModalOpen(false)}
        onOk={submitRole}
        destroyOnHidden
        width={680}
        okText="保存"
      >
        <Form form={roleForm} layout="vertical">
          <Form.Item name="tenant_id" label="租户" rules={[{ required: true, message: '请选择租户' }]}>
            <Select options={tenantOptions} disabled={!!roleEditing} showSearch optionFilterProp="label" />
          </Form.Item>
          <Form.Item name="key" label="Key" rules={[{ required: true, message: '填写 role key' }]}>
            <Input disabled={!!roleEditing} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '填写名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
            权限
          </Text>
          {permissionMeta.map((meta) => (
            <Form.Item
              key={meta.key}
              name={['permissions', meta.key]}
              label={meta.name || meta.key}
              extra={meta.desc || undefined}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          ))}
        </Form>
      </Modal>

      <Modal
        title={membershipEditing ? '编辑成员绑定' : '添加成员绑定'}
        open={membershipModalOpen}
        onCancel={() => setMembershipModalOpen(false)}
        onOk={submitMembership}
        destroyOnHidden
        width={560}
        okText="保存"
      >
        <Form form={membershipForm} layout="vertical">
          <Form.Item name="user_id" label="用户" rules={[{ required: true, message: '选择用户' }]}>
            <Select options={userOptions} showSearch optionFilterProp="label" disabled={!!membershipEditing} />
          </Form.Item>
          <Form.Item name="tenant_id" label="租户" rules={[{ required: true, message: '选择租户' }]}>
            <Select options={tenantOptions} showSearch optionFilterProp="label" disabled={!!membershipEditing} />
          </Form.Item>
          <Form.Item name="role_id" label="角色">
            <Select options={filteredRoleOptions} allowClear showSearch optionFilterProp="label" placeholder="可选" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_default" label="默认租户" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="edge_cluster_ids" label="边缘集群范围">
            <Select
              mode="multiple"
              allowClear
              options={clusterScopeOptions}
              placeholder="不选表示租户内全部集群"
              optionFilterProp="label"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

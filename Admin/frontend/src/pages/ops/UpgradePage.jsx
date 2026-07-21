import React, { useMemo, useState, useCallback, useEffect } from 'react';
import { Card, Spin, Alert, Button, Space, Tag, Typography, Upload, Modal, App, Switch } from 'antd';
import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  DeploymentUnitOutlined,
  InboxOutlined,
  ReloadOutlined,
  RocketOutlined,
  RollbackOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiGet, apiPost, apiPostForm } from '../../api/client';
import { formatBytes, formatTime } from '../../utils/format';

const { Text } = Typography;
const { Dragger } = Upload;

async function applyUpgradePackage(action, packageId, messageApi, refreshAll) {
  try {
    await apiPost(action, { package_id: packageId });
    messageApi.success('已应用');
    refreshAll();
  } catch (e) {
    messageApi.error(e?.message || '应用失败');
    throw e;
  }
}

function confirmApplyPackage(action, packageId, messageApi, refreshAll) {
  Modal.confirm({
    title: '确认应用升级包？',
    content: `将应用 ${packageId}，可能影响运行中的服务。`,
    onOk: () => applyUpgradePackage(action, packageId, messageApi, refreshAll),
  });
}

export default function UpgradePage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.upgrade);
  const [uploading, setUploading] = useState(false);
  const [onlyCompatible, setOnlyCompatible] = useState(false);
  const [packageRows, setPackageRows] = useState(null);
  const [packageLoading, setPackageLoading] = useState(true);
  const [packageError, setPackageError] = useState(null);

  const state = data?.state || {};
  const summary = data?.summary || {};
  const actions = data?.actions || {};
  const uploadConfig = data?.upload || {};
  const uploadAction = actions.upload || API.opsUpgradeUpload;
  const validateAction = actions.validate || API.opsUpgradeValidate;
  const applyAction = actions.apply || API.opsUpgradeApply;
  const rollbackAction = actions.rollback || API.opsUpgradeRollback;
  const uploadFieldName = uploadConfig.field_name || 'file';
  const uploadAccept = uploadConfig.accept || '.zip,application/zip';

  const loadPackages = useCallback(
    async (compatOnly = onlyCompatible) => {
      setPackageLoading(true);
      setPackageError(null);
      try {
        const rows = await apiGet(API.opsUpgradeList, compatOnly ? { only_compatible: 1 } : undefined);
        setPackageRows(Array.isArray(rows) ? rows : []);
      } catch (e) {
        setPackageError(e);
      } finally {
        setPackageLoading(false);
      }
    },
    [onlyCompatible],
  );

  const refreshAll = useCallback(() => {
    run();
    loadPackages();
  }, [loadPackages, run]);

  useEffect(() => {
    loadPackages(onlyCompatible);
  }, [loadPackages, onlyCompatible]);

  const stateItems = useMemo(
    () => [
      { key: 'current_version', label: '当前版本', value: state.current_version || summary.current_version || '-' },
      { key: 'target_version', label: '目标版本', value: state.target_version || summary.target_version || '-' },
      { key: 'applied_package_id', label: '已应用包', value: state.applied_package_id || summary.applied_package_id || '-' },
      { key: 'previous_package_id', label: '上一包', value: state.previous_package_id || summary.previous_package_id || '-' },
      { key: 'applied_at', label: '应用时间', value: formatTime(state.applied_at) },
      { key: 'latest_uploaded_at', label: '最近上传', value: formatTime(summary.latest_uploaded_at) },
      { key: 'rolled_back_from', label: '回滚来源', value: state.rolled_back_from || '-' },
      { key: 'rolled_back_at', label: '回滚时间', value: formatTime(state.rolled_back_at) },
      { key: 'rollback', label: '可回滚', value: summary.rollback_ready ? <Tag color="blue">是</Tag> : <Tag>否</Tag> },
      {
        key: 'packages',
        label: '包统计',
        value: `共 ${summary.package_total ?? 0}，兼容 ${summary.compatible_total ?? 0} / 不兼容 ${summary.incompatible_total ?? 0}`,
      },
    ],
    [state, summary],
  );

  const validatePackage = useCallback(
    async (packageId) => {
      try {
        const res = await apiGet(validateAction, { package_id: packageId });
        message.success(res?.ok ? '校验通过' : `校验完成: ${(res?.errors || []).join('; ') || '见结果'}`);
      } catch (e) {
        message.error(e?.message || '校验失败');
      }
    },
    [message, validateAction],
  );

  const columns = useMemo(
    () => [
      { title: '包 ID', dataIndex: 'package_id', width: 200, ellipsis: true },
      { title: '目标版本', dataIndex: 'target_version', width: 140, ellipsis: true },
      {
        title: '兼容',
        dataIndex: 'compatible_ok',
        width: 90,
        render: (v) => (v ? <Tag color="success">是</Tag> : <Tag color="error">否</Tag>),
      },
      {
        title: '兼容说明',
        dataIndex: 'compatible_errors',
        ellipsis: true,
        render: (errs) => (Array.isArray(errs) && errs.length ? errs.join('; ') : '-'),
      },
      { title: '上传时间', dataIndex: 'uploaded_at', width: 170, render: (v) => formatTime(v) },
      { title: '大小', dataIndex: 'size_bytes', width: 100, render: (v) => formatBytes(v) },
      { title: 'SHA256', dataIndex: 'sha256', ellipsis: true, render: (v) => v || '-' },
      {
        title: '操作',
        key: 'ops',
        width: 220,
        fixed: 'right',
        render: (_, r) => (
          <Space size={0} wrap>
            <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => validatePackage(r.package_id)}>
              校验
            </Button>
            <Button
              type="link"
              size="small"
              icon={<RocketOutlined />}
              onClick={() => confirmApplyPackage(applyAction, r.package_id, message, refreshAll)}
            >
              应用
            </Button>
          </Space>
        ),
      },
    ],
    [applyAction, message, refreshAll, validatePackage],
  );

  const packages = Array.isArray(packageRows) ? packageRows : (data?.packages || []);

  return (
    <div>
      <PageHeader title="升级管理" icon={<CloudUploadOutlined />} description="系统版本升级管理" extra={<Button icon={<ReloadOutlined />} onClick={refreshAll}>刷新</Button>} />

      {error || packageError ? (
        <Alert
          type="error"
          message={error?.message || packageError?.message || '加载失败'}
          style={{ marginBottom: 16 }}
          showIcon
        />
      ) : null}

      <Spin spinning={loading || packageLoading}>
        <div
          className="beacon-support-grid beacon-equal-height-grid"
          data-testid="upgrade-summary-grid"
          data-layout="full-width"
          style={{ marginBottom: 16 }}
        >
          <Card
            className="beacon-panel-card beacon-panel-card--tone-orange beacon-upload-panel"
            title={<PanelTitle title="上传升级包" meta="离线包导入" icon={<CloudUploadOutlined />} tone="orange" />}
            size="small"
          >
            <Dragger
              name={uploadFieldName}
              multiple={false}
              showUploadList={false}
              disabled={uploading}
              accept={uploadAccept}
              customRequest={async ({ file, onError, onSuccess }) => {
                setUploading(true);
                const fd = new FormData();
                fd.append(uploadFieldName, file);
                try {
                  await apiPostForm(uploadAction, fd);
                  message.success('上传成功');
                  onSuccess?.({}, file);
                  refreshAll();
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
              <p className="ant-upload-text">拖拽 zip 升级包到此处或点击上传</p>
            </Dragger>

            {data?.upload?.note ? (
              <Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12 }}>
                {data.upload.note}
              </Text>
            ) : null}
          </Card>

          <SummaryCard title="当前版本与状态" meta="版本 / 回滚 / 包状态" icon={<CheckCircleOutlined />} tone="green" items={stateItems}>
            <div className="beacon-summary-card__extra">
              <Space wrap>
                <Button
                  icon={<RollbackOutlined />}
                  danger
                  onClick={() => {
                    Modal.confirm({
                      title: '确认回滚升级状态？',
                      content: '将切换回上一升级包记录（最佳努力）。',
                      onOk: async () => {
                        try {
                          await apiPost(rollbackAction, {});
                          message.success('已回滚');
                          refreshAll();
                        } catch (e) {
                          message.error(e?.message || '回滚失败');
                          throw e;
                        }
                      },
                    });
                  }}
                >
                  回滚升级
                </Button>
              </Space>
            </div>
          </SummaryCard>
        </div>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-blue"
          title={<PanelTitle title="升级包列表" meta="校验与应用" icon={<DeploymentUnitOutlined />} tone="blue" />}
          size="small"
          extra={
            <Space size={8}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                直连离线升级包清单
              </Text>
              <Switch checked={onlyCompatible} onChange={setOnlyCompatible} checkedChildren="仅兼容" unCheckedChildren="全部" />
            </Space>
          }
        >
          <ProTable rowKey="package_id" columns={columns} dataSource={packages} loading={loading} pagination={{ pageSize: 10 }} scroll={{ x: 1100 }} />
        </Card>
      </Spin>
    </div>
  );
}

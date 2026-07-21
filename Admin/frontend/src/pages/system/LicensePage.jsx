import React, { useMemo, useState } from 'react';
import { Card, Spin, Alert, Button, Tag, Upload, App, Progress, Statistic, Typography, Space } from 'antd';
import {
  ApartmentOutlined,
  AppstoreOutlined,
  ClusterOutlined,
  InboxOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPostFormRaw } from '../../api/client';
import { formatTime } from '../../utils/format';

const { Dragger } = Upload;
const { Text } = Typography;

function joinValues(values) {
  if (!Array.isArray(values) || !values.length) return '-';
  return values.filter(Boolean).join(', ') || '-';
}

function formatThreadPolicy(policy) {
  if (!policy || typeof policy !== 'object') return '-';
  const entries = Object.entries(policy).filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (!entries.length) return '-';
  return entries.map(([key, value]) => `${key}: ${value}`).join(' | ');
}

export default function LicensePage() {
  const { message } = App.useApp();
  const { data, loading, error, run, setData } = useApi(API.license);
  const [uploading, setUploading] = useState(false);

  const state = data?.state || {};
  const usage = data?.usage || {};
  const info = data?.info || {};
  const fallbackInfo = data?.fallback_info || {};
  const licenseError = data?.license_error || null;
  const packageCount = Array.from(new Set([
    ...(Array.isArray(state.packages) ? state.packages : []),
    ...Object.keys(usage.package_usage || {}),
    ...Object.keys(usage.package_limits || {}),
    ...Object.keys(state.package_limits || {}),
  ])).filter(Boolean).length;
  const activeControls = Number(usage.active_controls ?? 0) || 0;
  const maxActiveControls = Number(usage.limits?.max_active_controls ?? state.max_active_controls ?? 0) || 0;
  const controlUsagePercent = maxActiveControls > 0
    ? Math.max(0, Math.min(100, Math.round((activeControls / maxActiveControls) * 100)))
    : 0;
  const statusTone = usage.valid ? 'green' : 'orange';

  const stateItems = useMemo(
    () => [
      { key: 'valid', label: '有效', value: usage.valid ? <Tag color="success">是</Tag> : <Tag color="warning">否</Tag> },
      { key: 'license_id', label: '授权 ID', value: state.license_id || usage.license_id || '-' },
      { key: 'customer', label: '客户', value: state.customer || usage.customer || '-' },
      { key: 'cluster_id', label: '集群', value: state.cluster_id || usage.cluster_id || '-' },
      { key: 'type', label: '类型', value: data?.license_type || state.type || '-' },
      { key: 'not_before', label: '生效时间', value: formatTime(state.not_before) },
      { key: 'not_after', label: '到期时间', value: formatTime(state.not_after || usage.not_after) },
      { key: 'packages', label: '授权包', value: joinValues(state.packages) },
      {
        key: 'limits',
        label: '限额',
        value: `布控 ${usage.limits?.max_active_controls ?? state.max_active_controls ?? '-'} / 节点 ${usage.limits?.max_nodes ?? state.max_nodes ?? '-'}`,
      },
      {
        key: 'usage_counts',
        label: '当前用量',
        value: `布控 ${usage.active_controls ?? '-'} / 流 ${usage.active_streams ?? '-'} / 节点 ${usage.active_nodes ?? '-'}`,
      },
      { key: 'edition', label: '版本特性', value: usage.edition || '-' },
      { key: 'thread_priority_policy', label: '线程策略', value: formatThreadPolicy(usage.thread_priority_policy) },
      { key: 'last_error', label: '最近错误', value: state.last_error_message || data?.license_error?.message || '-' },
    ],
    [data, state, usage],
  );

  const diagnosticsItems = useMemo(
    () => [
      { key: 'top_msg', label: '最近导入结果', value: data?.top_msg || '-' },
      { key: 'info_source', label: '信息来源', value: data?.info_source || '-' },
      { key: 'api_base_url', label: 'API Base URL', value: data?.api_base_url || '-' },
      { key: 'error_code', label: '错误代码', value: licenseError?.code || state.last_error_code || '-' },
      { key: 'error_message', label: '错误信息', value: licenseError?.message || state.last_error_message || '-' },
      { key: 'transport_message', label: '传输信息', value: data?.transport_message || '-' },
    ],
    [data, licenseError, state],
  );

  const upstreamItems = useMemo(
    () => [
      { key: 'upstream_type', label: '上游类型', value: info.type || '-' },
      { key: 'upstream_machine', label: 'Analyzer 机器码', value: info.machine_code || '-' },
      { key: 'upstream_license', label: 'Analyzer 授权 ID', value: info.extra?.license_id || info.license_id || '-' },
      { key: 'upstream_cluster', label: 'Analyzer 集群', value: info.extra?.cluster_id || info.cluster_id || '-' },
      { key: 'fallback_machine', label: '本地机器码', value: fallbackInfo.machine_code || '-' },
    ],
    [fallbackInfo, info],
  );

  const packageRows = useMemo(() => {
    const packageNames = Array.from(new Set([
      ...(Array.isArray(state.packages) ? state.packages : []),
      ...Object.keys(usage.package_usage || {}),
      ...Object.keys(usage.package_limits || {}),
      ...Object.keys(state.package_limits || {}),
    ])).filter(Boolean);

    return packageNames.map((name) => {
      const limit = usage.package_limits?.[name] || state.package_limits?.[name] || {};
      const activeUsage = usage.package_usage?.[name] ?? 0;
      const maxActiveControls = limit.max_active_controls ?? '-';
      const maxNodes = limit.max_nodes ?? '-';
      return {
        key: name,
        package_name: name,
        active_usage: activeUsage,
        max_active_controls: maxActiveControls,
        max_nodes: maxNodes,
        usage_summary: `${activeUsage} / ${maxActiveControls}`,
      };
    });
  }, [state.package_limits, state.packages, usage.package_limits, usage.package_usage]);

  const packageColumns = [
    { title: '授权包', dataIndex: 'package_name', width: 120 },
    { title: '占用 / 上限', dataIndex: 'usage_summary', width: 140 },
    { title: '节点上限', dataIndex: 'max_nodes', width: 120, render: (value) => value ?? '-' },
  ];

  const leaseColumns = [
    { title: '租约 ID', dataIndex: 'lease_id', ellipsis: true, width: 160 },
    { title: '节点', dataIndex: 'node_id', width: 120, ellipsis: true },
    { title: '流', dataIndex: 'stream_code', ellipsis: true, render: (v) => v || '-' },
    { title: '布控', dataIndex: 'control_code', width: 120, ellipsis: true, render: (v) => v || '-' },
    { title: '算法', dataIndex: 'algorithm_code', width: 120, ellipsis: true },
    { title: '套餐', dataIndex: 'package', width: 90 },
    { title: '过期', dataIndex: 'expires_at', width: 170, render: (v) => formatTime(v) },
      { title: '更新时间', dataIndex: 'update_time', width: 170, render: (v) => formatTime(v) },
  ];

  const leases = data?.leases || [];

  return (
    <div>
      <PageHeader
        title="授权管理"
        icon={<SafetyCertificateOutlined />}
        description="授权许可管理"
        extra={<Button icon={<ReloadOutlined />} onClick={() => run()}>刷新</Button>}
      />

      {error ? <Alert type="error" message={error.message || '加载失败'} style={{ marginBottom: 16 }} showIcon /> : null}
      {data?.top_msg ? (
        <Alert
          type={licenseError ? 'error' : 'success'}
          message={data.top_msg}
          style={{ marginBottom: 16 }}
          showIcon
        />
      ) : null}
      {licenseError ? (
        <Alert
          type="error"
          message={`授权错误: ${licenseError.code || 'unknown'}`}
          description={licenseError.message || '授权校验失败'}
          style={{ marginBottom: 16 }}
          showIcon
        />
      ) : null}
      {data?.transport_message && !data?.transport_ok ? (
        <Alert type="warning" message={data.transport_message} style={{ marginBottom: 16 }} showIcon />
      ) : null}

      <Spin spinning={loading}>
        <Card
          className="beacon-panel-card beacon-panel-card--tone-orange beacon-upload-panel"
          title={<PanelTitle title="上传授权文件" meta="license 导入与校验" icon={<InboxOutlined />} tone="orange" />}
          size="small"
          style={{ marginBottom: 16 }}
        >
          <Dragger
            name="file"
            multiple={false}
            showUploadList={false}
            disabled={uploading}
            customRequest={async ({ file, onError, onSuccess }) => {
              setUploading(true);
              const fd = new FormData();
              fd.append('file', file);
              try {
                const result = await apiPostFormRaw(API.licenseUpload, fd);
                if (result?.data) {
                  setData(result.data);
                } else {
                  run();
                }

                if ((result?.code ?? 0) === 1000) {
                  message.success(result?.msg || '导入成功');
                  onSuccess?.(result, file);
                } else {
                  const uploadError = new Error(result?.msg || '导入失败');
                  message.error(result?.msg || '导入失败');
                  onError?.(uploadError);
                }
              } catch (e) {
                message.error(e.message || '导入失败');
                onError?.(e);
              } finally {
                setUploading(false);
              }
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽 license 文件到此上传</p>
            <p className="ant-upload-hint">将 POST 到服务端校验并保存，上传后会自动刷新下方授权信息。</p>
          </Dragger>
        </Card>

        <div
          className="beacon-support-grid beacon-equal-height-grid"
          data-testid="license-overview-grid"
          data-layout="full-width"
          style={{ marginBottom: 16 }}
        >
          <Card
            className="beacon-panel-card beacon-panel-card--tone-blue beacon-stat-panel"
            title={<PanelTitle title="活跃布控" meta="当前授权消耗" icon={<ApartmentOutlined />} tone="blue" />}
            size="small"
          >
            <Statistic value={usage.active_controls ?? 0} />
            <Progress percent={controlUsagePercent} size="small" status={controlUsagePercent >= 90 ? 'exception' : 'active'} />
          </Card>
          <Card
            className="beacon-panel-card beacon-panel-card--tone-cyan beacon-stat-panel"
            title={<PanelTitle title="活跃流" meta="授权覆盖视频流" icon={<VideoCameraOutlined />} tone="cyan" />}
            size="small"
          >
            <Statistic value={usage.active_streams ?? 0} />
          </Card>
          <Card
            className="beacon-panel-card beacon-panel-card--tone-green beacon-stat-panel"
            title={<PanelTitle title="活跃节点" meta="在线授权节点" icon={<ClusterOutlined />} tone="green" />}
            size="small"
          >
            <Statistic value={usage.active_nodes ?? 0} />
          </Card>
          <Card
            className="beacon-panel-card beacon-panel-card--tone-slate beacon-stat-panel"
            title={<PanelTitle title="授权包数" meta="当前套餐数量" icon={<AppstoreOutlined />} tone="slate" />}
            size="small"
          >
            <Statistic value={packageCount} suffix="个" />
          </Card>
        </div>

        <div className="beacon-support-grid beacon-equal-height-grid" data-layout="full-width" style={{ marginBottom: 16 }}>
          <SummaryCard title="授权状态" meta="证书 / 限额 / 用量" icon={<SafetyCertificateOutlined />} tone={statusTone} items={stateItems}>
            <div className="beacon-summary-card__extra">
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>布控占用率</Text>
                <Progress percent={controlUsagePercent} size="small" status={usage.valid ? 'active' : 'exception'} />
              </Space>
            </div>
          </SummaryCard>

          <SummaryCard title="授权诊断" meta="导入 / 传输 / 错误" icon={<InboxOutlined />} tone="orange" items={diagnosticsItems} />

          <SummaryCard title="上游 / 回退信息" meta="Analyzer 与本地回退" icon={<ClusterOutlined />} tone="blue" items={upstreamItems} />
        </div>

        {packageRows.length ? (
          <Card
            className="beacon-panel-card beacon-panel-card--tone-cyan"
            title={<PanelTitle title="授权包用量" meta="套餐占用与节点上限" icon={<AppstoreOutlined />} tone="cyan" />}
            size="small"
            style={{ marginBottom: 16 }}
          >
            <ProTable
              rowKey="package_name"
              columns={packageColumns}
              dataSource={packageRows}
              pagination={false}
            />
          </Card>
        ) : null}

        {leases.length ? (
          <Card
            className="beacon-panel-card beacon-panel-card--tone-slate"
            title={<PanelTitle title="活跃租约" meta="租约明细与过期时间" icon={<ClusterOutlined />} tone="slate" />}
            size="small"
          >
            <ProTable rowKey={(r) => r.lease_id || r.node_id} columns={leaseColumns} dataSource={leases} pagination={{ pageSize: 10 }} />
          </Card>
        ) : null}
      </Spin>
    </div>
  );
}

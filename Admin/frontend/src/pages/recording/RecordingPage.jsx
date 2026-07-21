import React, { useState, useCallback, useEffect } from 'react';
import { Alert, App, Button, Card, Checkbox, Input, Modal, Popconfirm, Space, Tabs, Tag, Typography } from 'antd';
import {
  CalendarOutlined,
  CameraOutlined,
  CaretRightOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  StopOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost, apiPostRaw } from '../../api/client';
import { formatBytes, formatTime } from '../../utils/format';

const { Text } = Typography;
const { TextArea } = Input;
const PLAN_DAY_OPTIONS = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 7 },
];

function normalizePlanTime(value, fallback) {
  const raw = String(value || '').trim();
  if (!raw) {
    return fallback;
  }

  const matched = /^(\d{2}):(\d{2})/.exec(raw);
  if (!matched) {
    return fallback;
  }

  return `${matched[1]}:${matched[2]}`;
}

function daysMaskToDaysOfWeek(mask) {
  const normalizedMask = Number(mask || 0);
  const days = [];

  for (let bit = 0; bit < 7; bit += 1) {
    if ((normalizedMask & (1 << bit)) !== 0) {
      days.push(bit + 1);
    }
  }

  return days.length ? days : PLAN_DAY_OPTIONS.map((item) => item.value);
}

function buildDefaultPlanForm(streams, recordFormats, defaultFormat) {
  const firstStreamCode = String(streams?.[0]?.code || streams?.[0]?.stream_code || '').trim();
  const firstFormat = String(recordFormats?.[0]?.code || defaultFormat || 'mp4').trim() || 'mp4';

  return {
    code: '',
    name: '',
    enabled: true,
    streamCode: firstStreamCode,
    startTime: '00:00',
    endTime: '23:59',
    daysOfWeek: PLAN_DAY_OPTIONS.map((item) => item.value),
    recordAudio: false,
    format: firstFormat,
    remark: '',
  };
}

function buildEditPlanForm(row, recordFormats, defaultFormat) {
  const firstFormat = String(recordFormats?.[0]?.code || defaultFormat || 'mp4').trim() || 'mp4';

  return {
    code: String(row?.code || '').trim(),
    name: String(row?.name || '').trim(),
    enabled: Boolean(row?.enabled),
    streamCode: String(row?.stream_code || row?.streamCode || '').trim(),
    startTime: normalizePlanTime(row?.start_time || row?.startTime, '00:00'),
    endTime: normalizePlanTime(row?.end_time || row?.endTime, '23:59'),
    daysOfWeek: Array.isArray(row?.daysOfWeek) && row.daysOfWeek.length
      ? row.daysOfWeek.map(Number).filter((value) => Number.isInteger(value) && value >= 1 && value <= 7)
      : daysMaskToDaysOfWeek(row?.days_mask),
    recordAudio: Boolean(row?.record_audio ?? row?.recordAudio),
    format: String(row?.format || firstFormat).trim() || firstFormat,
    remark: String(row?.remark || '').trim(),
  };
}

export default function RecordingPage() {
  const { message } = App.useApp();
  const [params, setParams] = useState({ p: 1, ps: 20, q: '' });
  const { data, loading, error, run } = useApi(API.recording, params);
  const [activeRows, setActiveRows] = useState(null);
  const [activeLoading, setActiveLoading] = useState(true);
  const [activeError, setActiveError] = useState(null);
  const [statusOpen, setStatusOpen] = useState(false);
  const [statusPayload, setStatusPayload] = useState(null);
  const [batchSnapshotResult, setBatchSnapshotResult] = useState(null);
  const [filesOpen, setFilesOpen] = useState(false);
  const [fileRows, setFileRows] = useState([]);
  const [fileTotal, setFileTotal] = useState(0);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState(null);
  const [fileStreamCode, setFileStreamCode] = useState('');
  const [openingRelPath, setOpeningRelPath] = useState('');
  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [planModalMode, setPlanModalMode] = useState('add');
  const [planForm, setPlanForm] = useState(() => buildDefaultPlanForm([], [], 'mp4'));
  const [planSubmitting, setPlanSubmitting] = useState(false);
  const [planActionCode, setPlanActionCode] = useState('');
  const [deleteConfirmCode, setDeleteConfirmCode] = useState('');

  const plans = data?.plans || [];
  const streams = data?.streams || [];
  const activeRecordings = Array.isArray(activeRows) ? activeRows : (data?.active_recordings || []);
  const defaults = data?.defaults || {};
  const recordFormatChoices = Array.isArray(data?.record_format_choices) ? data.record_format_choices : [];
  const availableFormats = recordFormatChoices.length
    ? recordFormatChoices
    : [{ code: defaults.format || 'mp4', name: String(defaults.format || 'mp4').toUpperCase() }];
  const summary = data?.summary || {};
  const storage = data?.storage || {};
  const storagePaths = storage.paths || {};
  const storageDisk = storage.disk || {};
  const storageUsage = storage.usage || {};
  const storageQuota = storage.quota || {};
  const recordingQuotaLabel = storageQuota.recording_max_storage_mb
    ? `${formatBytes(storageUsage.recording_bytes)} / ${storageQuota.recording_max_storage_mb} MB`
    : `${formatBytes(storageUsage.recording_bytes)} / 未限制`;
  const overviewItems = [
    { key: 'stream_count', label: '总流数', value: String(summary.stream_count ?? streams.length ?? 0) },
    { key: 'online_streams', label: '在线流', value: String(summary.online_streams ?? '-') },
    { key: 'forwarding_streams', label: '转发中', value: String(summary.forwarding_streams ?? '-') },
    { key: 'active_recordings', label: '活跃录像', value: String(summary.active_recordings ?? activeRecordings.length ?? 0) },
    { key: 'plans', label: '启用计划', value: `${summary.enabled_plan_count ?? 0} / ${summary.plan_count ?? plans.length ?? 0}` },
  ];
  const storageItems = [
    { key: 'storage_root', label: '存储根目录', value: storagePaths.storage_root || '-' },
    { key: 'recording_root', label: '录像目录', value: storagePaths.recording_root || '-' },
    {
      key: 'disk_usage',
      label: '磁盘占用',
      value: storageDisk.total ? `${formatBytes(storageDisk.used)} / ${formatBytes(storageDisk.total)}` : '-',
    },
    { key: 'recording_usage', label: '录像占用', value: recordingQuotaLabel },
  ];

  const loadActiveRecordings = useCallback(async () => {
    setActiveLoading(true);
    setActiveError(null);
    try {
      const rows = await apiPost(API.recordingListActive, {});
      setActiveRows(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setActiveError(e);
    } finally {
      setActiveLoading(false);
    }
  }, []);

  useEffect(() => {
    loadActiveRecordings();
  }, [loadActiveRecordings]);

  const filters = [{ key: 'q', label: '搜索', type: 'input', placeholder: '计划/流/备注' }];

  const handleSearch = useCallback((filterValues) => {
    setParams((prev) => ({ ...prev, p: 1, q: filterValues.q || '' }));
  }, []);

  const handleReset = useCallback(() => {
    setParams({ p: 1, ps: 20, q: '' });
  }, []);

  const postRec = useCallback(
    async (url, body, ok) => {
      try {
        await apiPost(url, body);
        message.success(ok || '操作成功');
        run(params);
        loadActiveRecordings();
      } catch (e) {
        message.error(e?.message || '操作失败');
      }
    },
    [loadActiveRecordings, message, params, run],
  );

  const handleStatus = useCallback(
    async (streamCode) => {
      try {
        const payload = await apiPost(API.recordingStatus, { stream_code: streamCode });
        setStatusPayload(payload);
        setStatusOpen(true);
      } catch (e) {
        message.error(e?.message || '查询状态失败');
      }
    },
    [message],
  );

  const handleBatchSnapshot = useCallback(async () => {
    const snapshotStreams = streams
      .map((row) => ({ stream_code: row.stream_code || row.code }))
      .filter((row) => row.stream_code);

    if (!snapshotStreams.length) {
      message.warning('当前页没有可截图的视频流');
      return;
    }

    try {
      const payload = await apiPost(API.recordingBatchSnapshot, {
        method: defaults.snapshot_method || 'ffmpeg',
        streams: snapshotStreams,
      });
      setBatchSnapshotResult(payload || null);
      message.success('批量截图请求已完成');
    } catch (e) {
      message.error(e?.message || '批量截图失败');
    }
  }, [defaults.snapshot_method, message, streams]);

  const loadRecordingFiles = useCallback(async (streamCode) => {
    setFileLoading(true);
    setFileError(null);
    try {
      const payload = await apiPostRaw(API.recordingFileList, {
        streamCode,
        page: 1,
        pageSize: 20,
      });
      setFileRows(Array.isArray(payload?.data) ? payload.data : []);
      setFileTotal(Number(payload?.total || 0));
    } catch (e) {
      setFileRows([]);
      setFileTotal(0);
      setFileError(e);
    } finally {
      setFileLoading(false);
    }
  }, []);

  const openFilesModal = useCallback(async (streamCode) => {
    setFileStreamCode(streamCode);
    setFilesOpen(true);
    await loadRecordingFiles(streamCode);
  }, [loadRecordingFiles]);

  const openRecordingFile = useCallback(async (relPath) => {
    setOpeningRelPath(relPath);
    try {
      const payload = await apiPost(API.recordingFilePlayUrl, { relPath });
      const playUrl = String(payload?.play_url || '').trim();
      if (!playUrl) {
        throw new Error('后端未返回播放地址');
      }
      window.open(playUrl, '_blank', 'noopener,noreferrer');
    } catch (e) {
      message.error(e?.message || '打开录像失败');
    } finally {
      setOpeningRelPath('');
    }
  }, [message]);

  const openAddPlanModal = useCallback(() => {
    setPlanModalMode('add');
    setPlanForm(buildDefaultPlanForm(streams, availableFormats, defaults.format));
    setPlanModalOpen(true);
  }, [availableFormats, defaults.format, streams]);

  const openEditPlanModal = useCallback((row) => {
    setPlanModalMode('edit');
    setPlanForm(buildEditPlanForm(row, availableFormats, defaults.format));
    setPlanModalOpen(true);
  }, [availableFormats, defaults.format]);

  const updatePlanForm = useCallback((key, value) => {
    setPlanForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handlePlanSubmit = useCallback(async () => {
    const payload = {
      code: String(planForm.code || '').trim(),
      name: String(planForm.name || '').trim(),
      enabled: Boolean(planForm.enabled),
      streamCode: String(planForm.streamCode || '').trim(),
      startTime: normalizePlanTime(planForm.startTime, '00:00'),
      endTime: normalizePlanTime(planForm.endTime, '23:59'),
      daysOfWeek: Array.isArray(planForm.daysOfWeek) && planForm.daysOfWeek.length
        ? planForm.daysOfWeek.map(Number).filter((value) => Number.isInteger(value) && value >= 1 && value <= 7)
        : PLAN_DAY_OPTIONS.map((item) => item.value),
      recordAudio: Boolean(planForm.recordAudio),
      format: String(planForm.format || defaults.format || 'mp4').trim() || 'mp4',
      remark: String(planForm.remark || '').trim(),
    };

    if (!payload.code) {
      message.warning('请填写计划编码');
      return;
    }
    if (!payload.name) {
      message.warning('请填写计划名称');
      return;
    }
    if (!payload.streamCode) {
      message.warning('请填写视频流编号');
      return;
    }

    setPlanSubmitting(true);
    try {
      await apiPost(planModalMode === 'add' ? API.recordingPlanAdd : API.recordingPlanEdit, payload);
      message.success(planModalMode === 'add' ? '录像计划已新增' : '录像计划已更新');
      setPlanModalOpen(false);
      run(params);
    } catch (e) {
      message.error(e?.message || '保存录像计划失败');
    } finally {
      setPlanSubmitting(false);
    }
  }, [defaults.format, message, params, planForm, planModalMode, run]);

  const handlePlanToggle = useCallback(async (row) => {
    setPlanActionCode(row.code);
    try {
      await apiPost(API.recordingPlanEdit, {
        code: row.code,
        enabled: !row.enabled,
      });
      message.success(row.enabled ? '录像计划已停用' : '录像计划已启用');
      run(params);
    } catch (e) {
      message.error(e?.message || '切换计划状态失败');
    } finally {
      setPlanActionCode('');
    }
  }, [message, params, run]);

  const handlePlanDelete = useCallback(async (row) => {
    setPlanActionCode(row.code);
    try {
      await apiPost(API.recordingPlanDelete, { code: row.code });
      message.success('录像计划已删除');
      run(params);
      setDeleteConfirmCode('');
    } catch (e) {
      message.error(e?.message || '删除录像计划失败');
    } finally {
      setPlanActionCode('');
    }
  }, [message, params, run]);

  const planColumns = [
    { title: '计划名称', dataIndex: 'name', ellipsis: true, render: (v, r) => v || r.code || '-' },
    {
      title: '关联流',
      dataIndex: 'stream_code',
      ellipsis: true,
      render: (v, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{v || '-'}</Text>
          {r.stream_nickname ? (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {r.stream_nickname}
            </Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v) => (v ? <Tag color="success">是</Tag> : <Tag>否</Tag>),
    },
    { title: '格式', dataIndex: 'format', width: 80 },
    {
      title: '计划',
      key: 'schedule',
      ellipsis: true,
      render: (_, r) => {
        const days = r.days_label || '-';
        const span = [r.start_time, r.end_time].filter(Boolean).join(' ~ ');
        return [days, span].filter(Boolean).join(' · ') || '-';
      },
    },
    { title: '备注', dataIndex: 'remark', ellipsis: true },
    { title: '更新时间', dataIndex: 'update_time', width: 170, render: (v) => formatTime(v) },
    {
      title: '操作',
      key: 'ops',
      width: 180,
      fixed: 'right',
      render: (_, row) => (
        <Space size={0} wrap>
          <Button type="link" size="small" onClick={() => openEditPlanModal(row)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            loading={planActionCode === row.code}
            onClick={() => handlePlanToggle(row)}
          >
            {row.enabled ? '停用' : '启用'}
          </Button>
          <Popconfirm
            open={deleteConfirmCode === row.code}
            title="删除录像计划"
            description={`确认删除 ${row.name || row.code || '当前计划'}？`}
            okText="确定"
            cancelText="取消"
            onOpenChange={(open) => setDeleteConfirmCode(open ? row.code : '')}
            onConfirm={() => handlePlanDelete(row)}
          >
            <Button type="link" size="small" danger autoInsertSpace={false}>
              {deleteConfirmCode === row.code ? '待确认' : '删除'}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const streamColumns = [
    { title: '编号', dataIndex: 'code', width: 140, ellipsis: true },
    { title: '名称', dataIndex: 'nickname', ellipsis: true, render: (v, r) => v || r.name || '-' },
    {
      title: '状态',
      key: 'st',
      width: 120,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{r.online_state_label || '-'}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {r.is_recording ? '录像中' : '未录像'}
          </Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'ops',
      width: 260,
      fixed: 'right',
      render: (_, r) => {
        const url = r.stream_url || r.pull_stream_url || '';
        const disabled = !url;
        const code = r.stream_code || r.code;
        return (
          <Space size={0} wrap>
            <Button
              type="link"
              size="small"
              icon={<CaretRightOutlined />}
              disabled={disabled}
              onClick={() =>
                postRec(
                  API.recordingStart,
                  {
                    stream_code: code,
                    stream_url: url,
                    duration: defaults.duration ?? 60,
                    format: defaults.format || 'mp4',
                  },
                  '已开始录像',
                )
              }
            >
              开始
            </Button>
            <Button
              type="link"
              size="small"
              icon={<StopOutlined />}
              disabled={!r.is_recording}
              onClick={() => postRec(API.recordingStop, { stream_code: code }, '已停止录像')}
            >
              停止
            </Button>
            <Button type="link" size="small" onClick={() => handleStatus(code)}>
              状态
            </Button>
            <Button type="link" size="small" onClick={() => openFilesModal(code)}>
              文件
            </Button>
            <Button
              type="link"
              size="small"
              icon={<CameraOutlined />}
              disabled={disabled}
              onClick={() =>
                postRec(
                  API.recordingSnapshot,
                  { stream_code: code, method: defaults.snapshot_method || 'ffmpeg' },
                  '截图完成',
                )
              }
            >
              截图
            </Button>
          </Space>
        );
      },
    },
  ];

  const activeColumns = [
    { title: '流编号', dataIndex: 'stream_code', ellipsis: true },
    { title: '昵称', dataIndex: 'stream_nickname', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 100 },
    { title: '记录 ID', dataIndex: 'record_id', width: 140, ellipsis: true, render: (v) => v || '-' },
    { title: '时长', dataIndex: 'elapsed_time', width: 90 },
    { title: '保存路径', dataIndex: 'save_path', ellipsis: true, render: (v) => v || '-' },
  ];

  const fileColumns = [
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    { title: '相对路径', dataIndex: 'rel_path', ellipsis: true },
    { title: '修改时间', dataIndex: 'mtime', width: 170, render: (v) => formatTime(v) },
    { title: '大小', dataIndex: 'size_bytes', width: 100, render: (v) => formatBytes(v) },
    {
      title: '操作',
      key: 'ops',
      width: 90,
      render: (_, row) => (
        <Button
          type="link"
          size="small"
          loading={openingRelPath === row.rel_path}
          onClick={() => openRecordingFile(row.rel_path)}
        >
          打开
        </Button>
      ),
    },
  ];
  const filesModalTitle = fileStreamCode ? `录像文件 · ${fileStreamCode}` : '录像文件';

  return (
    <div>
      <PageHeader
        title="录像管理"
        icon={<DatabaseOutlined />}
        description="录像计划管理"
        extra={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => { run(params); loadActiveRecordings(); }}>
              刷新
            </Button>
            <Button icon={<CameraOutlined />} onClick={handleBatchSnapshot}>
              批量截图当前页
            </Button>
            <Button onClick={openAddPlanModal}>新增计划</Button>
          </Space>
        }
      />

      {error || activeError ? (
        <div style={{ color: '#dc2626', marginBottom: 12 }}>{error?.message || activeError?.message}</div>
      ) : null}

      <FilterBar filters={filters} onSearch={handleSearch} onReset={handleReset} />

      {batchSnapshotResult ? (
        <Alert
          style={{ marginBottom: 12 }}
          type="success"
          showIcon
          message={`批量截图完成：成功 ${batchSnapshotResult.success_count ?? 0}，失败 ${batchSnapshotResult.fail_count ?? 0}`}
        />
      ) : null}

      <div
        className="beacon-support-grid beacon-equal-height-grid"
        data-testid="recording-summary-grid"
        data-layout="full-width"
        style={{ marginBottom: 16 }}
      >
        <SummaryCard title="录像概览" meta="流 / 计划 / 活跃录像" icon={<DatabaseOutlined />} tone="blue" items={overviewItems} />
        <SummaryCard title="存储概览" meta="目录 / 磁盘 / 配额" icon={<FolderOpenOutlined />} tone="cyan" items={storageItems} />
      </div>

      <Card
        className="beacon-panel-card beacon-panel-card--tone-slate beacon-tabs-card"
        size="small"
        title={<PanelTitle title="录像工作台" meta="按流、活跃状态与计划协同操作" icon={<VideoCameraOutlined />} tone="slate" />}
      >
        <Tabs
          items={[
            {
              key: 'streams',
              label: (
                <span className="beacon-tab-label">
                  <VideoCameraOutlined />
                  <span>{`视频流 (${streams.length})`}</span>
                </span>
              ),
              children: (
                <ProTable
                  rowKey={(r) => r.code || r.stream_code}
                  columns={streamColumns}
                  dataSource={streams}
                  loading={loading || activeLoading}
                  pagination={false}
                  scroll={{ x: 900 }}
                />
              ),
            },
            {
              key: 'active',
              label: (
                <span className="beacon-tab-label">
                  <PlayCircleOutlined />
                  <span>{`活跃录像 (${activeRecordings.length})`}</span>
                </span>
              ),
              children: (
                <ProTable rowKey="stream_code" columns={activeColumns} dataSource={activeRecordings} loading={loading || activeLoading} pagination={false} />
              ),
            },
            {
              key: 'plans',
              label: (
                <span className="beacon-tab-label">
                  <CalendarOutlined />
                  <span>{`录像计划 (${plans.length})`}</span>
                </span>
              ),
              children: (
                <ProTable rowKey={(r) => r.id ?? r.code} columns={planColumns} dataSource={plans} loading={loading} pagination={{ pageSize: 12 }} />
              ),
            },
          ]}
        />
      </Card>

      <Modal title="录像状态" open={statusOpen} onCancel={() => setStatusOpen(false)} footer={null} destroyOnHidden>
        <pre style={{ fontSize: 12, maxHeight: 360, overflow: 'auto', marginBottom: 0 }}>{JSON.stringify(statusPayload, null, 2)}</pre>
      </Modal>

      <Modal
        title={filesModalTitle}
        open={filesOpen}
        onCancel={() => setFilesOpen(false)}
        footer={null}
        width={960}
        destroyOnHidden
      >
        {fileError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message={fileError.message || '加载录像文件失败'}
          />
        ) : null}
        <Space style={{ marginBottom: 12 }} wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>
            最近文件 {fileTotal || fileRows.length} 条
          </Text>
          {fileStreamCode ? (
            <Button size="small" onClick={() => loadRecordingFiles(fileStreamCode)}>
              刷新文件
            </Button>
          ) : null}
        </Space>
        <ProTable
          rowKey={(row) => `${row.rel_path}-${row.mtime}-${row.filename}`}
          columns={fileColumns}
          dataSource={fileRows}
          loading={fileLoading}
          pagination={false}
          scroll={{ x: 900 }}
        />
      </Modal>

      <Modal
        title={planModalMode === 'add' ? '新增录像计划' : '编辑录像计划'}
        open={planModalOpen}
        onCancel={() => {
          if (!planSubmitting) {
            setPlanModalOpen(false);
          }
        }}
        footer={[
          <Button
            key="cancel"
            autoInsertSpace={false}
            disabled={planSubmitting}
            onClick={() => setPlanModalOpen(false)}
          >
            取消
          </Button>,
          <Button
            key="save"
            type="primary"
            autoInsertSpace={false}
            loading={planSubmitting}
            onClick={handlePlanSubmit}
          >
            保存
          </Button>,
        ]}
        destroyOnHidden
      >
        <div style={{ display: 'grid', gap: 12 }}>
          <div>
            <label htmlFor="recording-plan-code" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
              计划编码
            </label>
            <Input
              id="recording-plan-code"
              aria-label="计划编码"
              value={planForm.code}
              disabled={planModalMode === 'edit'}
              onChange={(event) => updatePlanForm('code', event.target.value)}
            />
          </div>

          <div>
            <label htmlFor="recording-plan-name" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
              计划名称
            </label>
            <Input
              id="recording-plan-name"
              aria-label="计划名称"
              value={planForm.name}
              onChange={(event) => updatePlanForm('name', event.target.value)}
            />
          </div>

          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <div>
              <label htmlFor="recording-plan-stream-code" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                视频流编号
              </label>
              <Input
                id="recording-plan-stream-code"
                aria-label="视频流编号"
                value={planForm.streamCode}
                onChange={(event) => updatePlanForm('streamCode', event.target.value)}
              />
            </div>

            <div>
              <label htmlFor="recording-plan-format" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                录像格式
              </label>
              <select
                id="recording-plan-format"
                aria-label="录像格式"
                value={planForm.format}
                onChange={(event) => updatePlanForm('format', event.target.value)}
                style={{
                  width: '100%',
                  height: 32,
                  borderRadius: 6,
                  border: '1px solid #d9d9d9',
                  padding: '0 11px',
                  background: '#fff',
                }}
              >
                {availableFormats.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name || item.code}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <div>
              <label htmlFor="recording-plan-start-time" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                开始时间
              </label>
              <Input
                id="recording-plan-start-time"
                aria-label="开始时间"
                placeholder="00:00"
                value={planForm.startTime}
                onChange={(event) => updatePlanForm('startTime', event.target.value)}
              />
            </div>

            <div>
              <label htmlFor="recording-plan-end-time" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                结束时间
              </label>
              <Input
                id="recording-plan-end-time"
                aria-label="结束时间"
                placeholder="23:59"
                value={planForm.endTime}
                onChange={(event) => updatePlanForm('endTime', event.target.value)}
              />
            </div>
          </div>

          <div>
            <div style={{ marginBottom: 6, fontSize: 12, fontWeight: 600 }}>执行日期</div>
            <Checkbox.Group
              value={planForm.daysOfWeek}
              options={PLAN_DAY_OPTIONS}
              onChange={(value) => updatePlanForm('daysOfWeek', value)}
            />
          </div>

          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Checkbox checked={planForm.enabled} onChange={(event) => updatePlanForm('enabled', event.target.checked)}>
              启用计划
            </Checkbox>
            <Checkbox checked={planForm.recordAudio} onChange={(event) => updatePlanForm('recordAudio', event.target.checked)}>
              同时录制音频
            </Checkbox>
          </div>

          <div>
            <label htmlFor="recording-plan-remark" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
              备注
            </label>
            <TextArea
              id="recording-plan-remark"
              aria-label="备注"
              rows={3}
              value={planForm.remark}
              onChange={(event) => updatePlanForm('remark', event.target.value)}
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}

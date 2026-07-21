import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Button, Space, App, Image, Tooltip, Typography, Select, Modal, Input, Switch, Badge } from 'antd';
import {
  AlertOutlined,
  ReloadOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import FilterBar from '../../components/FilterBar';
import ProTable from '../../components/ProTable';
import { WorkflowStatusBadge } from '../../components/StatusBadge';
import AlarmDetailDrawer from './AlarmDetailDrawer';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost, apiGet } from '../../api/client';
import { formatTime } from '../../utils/format';
import { getBootstrapPath, getBootstrapQuery } from '../../bootstrap';

const { Text } = Typography;

const ALARM_FILTERS = [
  { key: 'status', label: '状态', type: 'select', options: [
    { value: '', label: '全部' },
    { value: 'new', label: '新告警' },
    { value: 'acknowledged', label: '已确认' },
    { value: 'resolved', label: '已解决' },
    { value: 'dismissed', label: '已忽略' },
    { value: 'assigned', label: '已分配' },
  ]},
  { key: 'control_code', label: '布控', type: 'input', placeholder: '布控编号' },
  { key: 'stream_code', label: '视频流', type: 'input', placeholder: '视频流编号' },
  { key: 'algorithm_code', label: '算法', type: 'input', placeholder: '算法编号' },
  { key: 'date_range', label: '日期', type: 'dateRange' },
];

function parseApplyUrl(applyUrl) {
  if (!applyUrl) return {};
  try {
    const u = applyUrl.startsWith('http')
      ? new URL(applyUrl)
      : new URL(applyUrl, globalThis.location.origin);
    const out = {};
    u.searchParams.forEach((v, k) => {
      out[k] = v;
    });
    return out;
  } catch {
    return {};
  }
}

function normalizeFilterValues(filterValues) {
  const next = { ...filterValues };
  if (next.date_range && Array.isArray(next.date_range) && next.date_range[0] && next.date_range[1]) {
    const [a, b] = next.date_range;
    next.start = (a.format ? a.format('YYYY-MM-DD HH:mm:ss') : String(a));
    next.end = (b.format ? b.format('YYYY-MM-DD HH:mm:ss') : String(b));
    delete next.date_range;
  }
  return next;
}

function stripPagination(obj) {
  if (!obj || typeof obj !== 'object') return {};
  const { p, ps, date_range, ...rest } = obj;
  return rest;
}

function buildInitialAlarmParams(query, currentPath) {
  const params = {
    p: query.get('p') || 1,
    ps: query.get('ps') || 20,
    status: query.get('status') || '',
  };
  const isReviewRoute = currentPath === '/alarm/review';
  const mode = query.get('mode') || (isReviewRoute ? 'review' : '');
  const reviewTab = query.get('review_tab') || '';
  const unread = query.get('unread') || '';
  if (mode) params.mode = mode;
  if (reviewTab) params.review_tab = reviewTab;
  if (unread) params.unread = unread;
  return params;
}

export default function AlarmsPage() {
  const { message, modal } = App.useApp();
  const currentPath = getBootstrapPath();
  const query = getBootstrapQuery();
  const initialParamsRef = useRef(buildInitialAlarmParams(query, currentPath));
  const [params, setParams] = useState(initialParamsRef.current);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState(null);
  const [savePresetOpen, setSavePresetOpen] = useState(false);
  const [savePresetName, setSavePresetName] = useState('');
  const [presetSelectId, setPresetSelectId] = useState(undefined);
  const [pollEnabled, setPollEnabled] = useState(false);
  const [autoRefreshOnPoll, setAutoRefreshOnPoll] = useState(true);
  const [pendingNewCount, setPendingNewCount] = useState(0);
  const [semanticOpen, setSemanticOpen] = useState(false);
  const [semanticQuery, setSemanticQuery] = useState('');
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [semanticResult, setSemanticResult] = useState(null);
  const [handledModalOpen, setHandledModalOpen] = useState(false);
  const [handledRemark, setHandledRemark] = useState('');
  const [legacyHandleLoading, setLegacyHandleLoading] = useState(false);
  const [previewMedia, setPreviewMedia] = useState(null);
  const pollAfterRef = useRef(0);
  const paramsRef = useRef(params);
  paramsRef.current = params;

  const { data, loading, run } = useApi(API.alarms, params);

  const rows = data?.rows || [];
  const total = data?.total || 0;
  const presets = data?.presets || {};
  const presetItems = presets.items || [];
  const activePreset = presetItems.find((i) => i.is_active);

  useEffect(() => {
    if (!rows.length) return;
    const maxId = Math.max(0, ...rows.map((r) => Number(r.id) || 0));
    if (maxId > pollAfterRef.current) {
      pollAfterRef.current = maxId;
    }
  }, [rows]);

  useEffect(() => {
    if (!pollEnabled) return undefined;
    const tick = async () => {
      try {
        const p = paramsRef.current;
        const pollRest = { ...normalizeFilterValues(p) };
        delete pollRest.p;
        delete pollRest.ps;
        delete pollRest.status;
        const res = await apiGet(API.alarmPoll, {
          after_id: pollAfterRef.current,
          ...pollRest,
        });
        const newCount = Number(res?.new_count || 0);
        const newestId = res?.newest_id == null ? pollAfterRef.current : Number(res.newest_id);
        if (newCount > 0) {
          setPendingNewCount(newCount);
          if (autoRefreshOnPoll) {
            await run(paramsRef.current);
            setPendingNewCount(0);
          }
        }
        if (!Number.isNaN(newestId) && newestId >= pollAfterRef.current) {
          pollAfterRef.current = newestId;
        }
      } catch {
        /* ignore poll errors */
      }
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => clearInterval(id);
  }, [pollEnabled, autoRefreshOnPoll, run]);

  const handleSearch = useCallback((filterValues) => {
    const next = normalizeFilterValues(filterValues);
    setParams((prev) => ({ ...prev, ...next, p: 1 }));
  }, []);

  const handleReset = useCallback(() => {
    setPresetSelectId(undefined);
    setParams(initialParamsRef.current);
  }, []);

  const handleTableChange = useCallback((pagination) => {
    setParams((prev) => ({
      ...prev,
      p: pagination.current,
      ps: pagination.pageSize,
    }));
  }, []);

  const handleRefresh = useCallback(() => {
    setPendingNewCount(0);
    run(params);
  }, [params, run]);

  const openPreviewMedia = useCallback((record) => {
    if (!record) return;
    if (record.image_url) {
      setPreviewMedia({
        type: 'image',
        src: record.image_url,
        title: `告警预览 #${record.id || ''}`,
      });
      return;
    }
    if (record.video_url) {
      setPreviewMedia({
        type: 'video',
        src: record.video_url,
        title: `告警视频 #${record.id || ''}`,
      });
    }
  }, []);

  const getSelectedAlarmIdsString = useCallback(() => {
    return selectedRowKeys
      .map((item) => String(item || '').trim())
      .filter(Boolean)
      .join(',');
  }, [selectedRowKeys]);

  const runLegacyHandleAction = useCallback(async (handle, extraData = {}) => {
    const alarmIdsStr = getSelectedAlarmIdsString();
    if (!alarmIdsStr) {
      message.warning('请至少选中一条告警');
      return false;
    }

    setLegacyHandleLoading(true);
    try {
      await apiPost(API.postHandleAlarm, {
        handle,
        alarm_ids_str: alarmIdsStr,
        ...extraData,
      });
      message.success('操作成功');
      await run(params);
      return true;
    } catch (e) {
      message.error(e.message || '操作失败');
      return false;
    } finally {
      setLegacyHandleLoading(false);
    }
  }, [getSelectedAlarmIdsString, message, params, run]);

  const handleBatchDelete = useCallback(() => {
    const alarmIdsStr = getSelectedAlarmIdsString();
    if (!alarmIdsStr) {
      message.warning('请至少选中一条告警');
      return;
    }
    modal.confirm({
      title: '确认删除告警？',
      content: `将删除 ${alarmIdsStr.split(',').filter(Boolean).length} 条告警记录`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true, 'aria-label': '删除' },
      onOk: async () => {
        await runLegacyHandleAction('delete');
      },
    });
  }, [getSelectedAlarmIdsString, message, modal, runLegacyHandleAction]);

  const handleSubmitHandled = useCallback(async () => {
    const ok = await runLegacyHandleAction('handled', {
      handled_remark: handledRemark,
    });
    if (ok) {
      setHandledModalOpen(false);
      setHandledRemark('');
    }
  }, [handledRemark, runLegacyHandleAction]);

  const handleSemanticSearch = useCallback(async () => {
    const q = semanticQuery.trim();
    if (!q) {
      message.warning('请输入语义检索语句');
      return;
    }
    setSemanticLoading(true);
    try {
      const payload = await apiGet(API.alarmSemanticSearch, {
        ...stripPagination(normalizeFilterValues(params)),
        q,
      });
      setSemanticResult(payload || null);
    } catch (e) {
      message.error(e?.message || '语义检索失败');
      setSemanticResult(null);
    } finally {
      setSemanticLoading(false);
    }
  }, [message, params, semanticQuery]);

  const handleWorkflow = useCallback(async (alarmId, transition) => {
    try {
      const form = new FormData();
      form.append('alarm_ids', String(alarmId));
      form.append('transition', transition);
      await apiPost(API.alarmWorkflow, form);
      message.success('操作成功');
      run(params);
    } catch (e) {
      message.error(e.message || '操作失败');
    }
  }, [params, run, message]);

  const openDetail = useCallback((record) => {
    setDetailId(record.id);
    setDetailOpen(true);
  }, []);

  const getDetailHref = useCallback((record) => (
    record.detail_url || `/alarm/detail?id=${encodeURIComponent(record.id)}`
  ), []);

  const applyPresetById = useCallback((id) => {
    const item = presetItems.find((i) => String(i.id) === String(id));
    if (!item?.apply_url) return;
    const parsed = parseApplyUrl(item.apply_url);
    setParams((prev) => ({
      ...parsed,
      p: 1,
      ps: prev.ps,
    }));
  }, [presetItems]);

  const handlePresetSelect = useCallback((value) => {
    if (value == null || value === '') {
      setPresetSelectId(undefined);
      return;
    }
    setPresetSelectId(value);
    applyPresetById(value);
  }, [applyPresetById]);

  const selectedPreset = presetItems.find((i) => String(i.id) === String(presetSelectId ?? activePreset?.id));
  const canDeletePreset = Boolean(selectedPreset?.is_owned);

  const handleSavePreset = useCallback(async () => {
    const name = savePresetName.trim();
    if (!name) {
      message.warning('请输入预设名称');
      return;
    }
    try {
      const body = {
        name,
        target_mode: presets.target_mode || 'list',
        visibility_scope: 'private',
        ...stripPagination(normalizeFilterValues(params)),
      };
      await apiPost(API.alarmPresetsSave, body);
      message.success('已保存预设');
      setSavePresetOpen(false);
      setSavePresetName('');
      run(params);
    } catch (e) {
      message.error(e.message || '保存失败');
    }
  }, [savePresetName, presets.target_mode, params, run, message]);

  const handleDeletePreset = useCallback(() => {
    const id = presetSelectId ?? activePreset?.id;
    if (!id || !canDeletePreset) return;
    modal.confirm({
      title: '删除该筛选预设？',
      onOk: async () => {
        try {
          await apiPost(API.alarmPresetsDelete, {
            preset_id: String(id),
            target_mode: presets.target_mode || 'list',
            ...data?.filters,
          });
          message.success('已删除');
          setPresetSelectId(undefined);
          run(params);
        } catch (e) {
          message.error(e.message || '删除失败');
          throw e;
        }
      },
    });
  }, [presetSelectId, activePreset, canDeletePreset, presets.target_mode, data?.filters, params, run, message, modal]);

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 60,
      fixed: 'left',
    },
    {
      title: '预览',
      dataIndex: 'image_url',
      width: 96,
      render: (_, record) => {
        if (record.image_url) {
          return (
            <button
              type="button"
              aria-label={`预览抓拍 ${record.id}`}
              onClick={() => openPreviewMedia(record)}
              style={{
                display: 'inline-flex',
                padding: 0,
                border: 0,
                background: 'transparent',
                cursor: 'pointer',
              }}
            >
              <Image
                preview={false}
                src={record.image_url}
                width={56}
                height={40}
                style={{ objectFit: 'cover', borderRadius: 4 }}
                fallback="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNTYiIGhlaWdodD0iNDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjU2IiBoZWlnaHQ9IjQwIiBmaWxsPSIjZjBmMGYwIi8+PC9zdmc+"
              />
            </button>
          );
        }
        if (record.video_url) {
          return (
            <button
              type="button"
              aria-label={`预览视频 ${record.id}`}
              onClick={() => openPreviewMedia(record)}
              style={{
                width: 56,
                height: 40,
                borderRadius: 6,
                border: '1px solid #dbe3f0',
                background: '#0f172a',
                color: '#fff',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 4,
                padding: 0,
              }}
            >
              <PlayCircleOutlined />
              <span style={{ fontSize: 11, lineHeight: 1 }}>视频</span>
            </button>
          );
        }
        return '-';
      },
    },
    {
      title: '描述',
      dataIndex: 'desc',
      ellipsis: true,
      render: (v, r) => (
        <a
          href={getDetailHref(r)}
          onClick={(event) => {
            event.preventDefault();
            openDetail(r);
          }}
          style={{ cursor: 'pointer' }}
        >
          {v || '-'}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'workflow_status',
      width: 80,
      render: (v) => <WorkflowStatusBadge status={v} />,
    },
    {
      title: '视频流',
      dataIndex: 'stream_name',
      width: 120,
      ellipsis: true,
      render: (v, r) => (
        <Tooltip title={r.stream_code}>
          <Text style={{ fontSize: 13 }}>{v || r.stream_code || '-'}</Text>
        </Tooltip>
      ),
    },
    {
      title: '算法',
      dataIndex: 'algorithm_code',
      width: 120,
      ellipsis: true,
    },
    {
      title: '布控',
      dataIndex: 'control_code',
      width: 120,
      ellipsis: true,
    },
    {
      title: '时间',
      dataIndex: 'create_time',
      width: 160,
      render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(v)}</Text>,
    },
    {
      title: '操作',
      width: 120,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openDetail(r)}>详情</Button>
          {r.workflow_status === 'new' && (
            <Button type="link" size="small" onClick={() => handleWorkflow(r.id, 'acknowledge')}>
              确认
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const rowSelection = {
    selectedRowKeys,
    onChange: setSelectedRowKeys,
  };

  let selectPresetValue = presetSelectId;
  if (presetSelectId == null) {
    selectPresetValue = activePreset?.id == null ? undefined : activePreset.id;
  }

  return (
    <div>
      <PageHeader
        title="报警管理"
        icon={<AlertOutlined />}
        description="全部告警事件浏览与批量处理"
        extra={
          <Space wrap>
            <Badge count={pendingNewCount} size="small" offset={[-2, 2]}>
              <Button icon={<ReloadOutlined />} onClick={handleRefresh}>刷新</Button>
            </Badge>
            <span style={{ fontSize: 13, color: '#64748b' }}>新告警监听</span>
            <Switch checked={pollEnabled} onChange={setPollEnabled} />
            {pollEnabled ? (
              <>
                <span style={{ fontSize: 13, color: '#64748b' }}>自动刷新列表</span>
                <Switch checked={autoRefreshOnPoll} onChange={setAutoRefreshOnPoll} />
              </>
            ) : null}
            <Button disabled={selectedRowKeys.length === 0} loading={legacyHandleLoading} onClick={() => runLegacyHandleAction('read')}>
              批量已读
            </Button>
            <Button disabled={selectedRowKeys.length === 0} loading={legacyHandleLoading} onClick={() => setHandledModalOpen(true)}>
              批量已处理
            </Button>
            <Button disabled={selectedRowKeys.length === 0} loading={legacyHandleLoading} onClick={() => runLegacyHandleAction('unhandled')}>
              恢复未处理
            </Button>
            <Button danger disabled={selectedRowKeys.length === 0} loading={legacyHandleLoading} onClick={handleBatchDelete}>
              删除告警
            </Button>
            <Button onClick={() => setSemanticOpen(true)}>
              语义检索
            </Button>
          </Space>
        }
      />

      <div style={{ marginBottom: 12 }}>
        <Space wrap align="center">
          <Text type="secondary" style={{ fontSize: 13 }}>筛选预设</Text>
          <Select
            allowClear
            placeholder="选择已保存的筛选视图"
            style={{ minWidth: 220 }}
            value={selectPresetValue}
            onChange={handlePresetSelect}
            options={presetItems.map((i) => ({
              value: i.id,
              label: i.name,
            }))}
          />
          <Button type="default" onClick={() => setSavePresetOpen(true)}>保存预设</Button>
          <Button
            type="default"
            danger
            icon={<DeleteOutlined />}
            disabled={!canDeletePreset}
            onClick={handleDeletePreset}
          >
            删除预设
          </Button>
        </Space>
      </div>

      <FilterBar
        filters={ALARM_FILTERS}
        onSearch={handleSearch}
        onReset={handleReset}
      />

      <ProTable
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowKey="id"
        rowSelection={rowSelection}
        pagination={{
          current: data?.page || 1,
          pageSize: data?.page_size || 20,
          total,
        }}
        onChange={handleTableChange}
      />

      <Modal
        title={previewMedia?.title || '告警预览'}
        open={Boolean(previewMedia)}
        footer={null}
        onCancel={() => setPreviewMedia(null)}
        width={720}
        destroyOnHidden
      >
        {previewMedia?.type === 'image' ? (
          <Image
            src={previewMedia.src}
            preview={false}
            style={{ width: '100%', maxHeight: '70vh', objectFit: 'contain', borderRadius: 8 }}
            fallback="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNzIwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNzIwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2YwZjBmMCIvPjwvc3ZnPg=="
          />
        ) : null}
        {previewMedia?.type === 'video' ? (
          <video
            controls
            playsInline
            preload="metadata"
            src={previewMedia.src}
            style={{ width: '100%', maxHeight: '70vh', background: '#000', borderRadius: 8 }}
          />
        ) : null}
      </Modal>

      <Modal
        title="批量处理告警"
        open={handledModalOpen}
        onOk={handleSubmitHandled}
        onCancel={() => { setHandledModalOpen(false); setHandledRemark(''); }}
        confirmLoading={legacyHandleLoading}
        okText="提交处理"
        okButtonProps={{ 'aria-label': '提交处理' }}
      >
        <div style={{ marginBottom: 8, fontSize: 13, color: '#64748b' }}>
          已选中 {selectedRowKeys.length} 条告警
        </div>
        <div style={{ marginBottom: 8 }}>
          <label htmlFor="alarmHandledRemark" style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>
            处理备注
          </label>
          <Input.TextArea
            id="alarmHandledRemark"
            value={handledRemark}
            rows={4}
            onChange={(e) => setHandledRemark(e.target.value)}
            placeholder="可选，提交后透传 handled_remark"
          />
        </div>
      </Modal>

      <Modal
        title="保存筛选预设"
        open={savePresetOpen}
        onOk={handleSavePreset}
        onCancel={() => { setSavePresetOpen(false); setSavePresetName(''); }}
        okText="保存"
      >
        <Input
          placeholder="预设名称"
          value={savePresetName}
          onChange={(e) => setSavePresetName(e.target.value)}
          maxLength={100}
          style={{ marginTop: 8 }}
        />
      </Modal>

      <Modal
        title="语义检索"
        open={semanticOpen}
        onOk={handleSemanticSearch}
        onCancel={() => setSemanticOpen(false)}
        confirmLoading={semanticLoading}
        okText="检索"
        okButtonProps={{ 'aria-label': '检索' }}
        width={720}
      >
        <div style={{ marginBottom: 8 }}>
          <label htmlFor="alarmSemanticQuery" style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>
            检索语句
          </label>
          <Input
            id="alarmSemanticQuery"
            placeholder="例如：helmet loading / control:north-gate status:closed"
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            onPressEnter={handleSemanticSearch}
          />
        </div>

        {semanticResult ? (
          <div style={{ marginTop: 16 }}>
            <div style={{ marginBottom: 8, fontSize: 13, color: '#64748b' }}>
              后端: <strong>{semanticResult.backend || '-'}</strong>
            </div>
            {semanticResult.fallback_reason ? (
              <div style={{ marginBottom: 12, fontSize: 12, color: '#8c8c8c' }}>
                {semanticResult.fallback_reason}
              </div>
            ) : null}
            {Array.isArray(semanticResult.items) && semanticResult.items.length > 0 ? (
              <div style={{ display: 'grid', gap: 8 }}>
                {semanticResult.items.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      border: '1px solid #e5e7eb',
                      borderRadius: 8,
                      padding: 12,
                      background: '#fafafa',
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{item.desc || `告警 #${item.id}`}</div>
                    <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
                      {item.stream_name || item.stream_code || '-'} · {item.control_code || '-'}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: '#8c8c8c', fontSize: 12 }}>暂无匹配结果</div>
            )}
          </div>
        ) : null}
      </Modal>

      <AlarmDetailDrawer
        open={detailOpen}
        alarmId={detailId}
        onClose={() => { setDetailOpen(false); setDetailId(null); }}
        onAction={() => run(params)}
      />
    </div>
  );
}

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Collapse,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Progress,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from 'antd';
import {
  CloudDownloadOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  PlusOutlined,
  ReloadOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import PageHeader from '../../components/PageHeader';
import ProTable from '../../components/ProTable';
import SummaryCard, { PanelTitle } from '../../components/SummaryCard';
import useApi from '../../hooks/useApi';
import { API } from '../../api/endpoints';
import { apiPost } from '../../api/client';
import { formatTime } from '../../utils/format';
import './DiagnosticsPage.css';

const { Text, Link } = Typography;
const { TextArea } = Input;

const TASK_PLAN_DAY_OPTIONS = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 7 },
];

const TASK_PLAN_TYPE_OPTIONS = [
  { label: '重启软件', value: 'restartSoftware' },
  { label: '重启系统', value: 'restartSystem' },
  { label: '扫描离线流', value: 'scanOfflineStreams' },
  { label: '启动布控', value: 'controlStart' },
  { label: '停止布控', value: 'controlStop' },
  { label: '启动转发', value: 'forwardStart' },
  { label: '停止转发', value: 'forwardStop' },
];

const TASK_PLAN_TYPE_LABELS = Object.fromEntries(TASK_PLAN_TYPE_OPTIONS.map((item) => [item.value, item.label]));
const TASK_PLAN_SCHEDULE_LABELS = {
  daily: '每天定时',
  interval: '固定间隔',
};

const SUMMARY_KEY_ORDER = [
  'host',
  'system_name',
  'os_release',
  'cpu',
  'cpu_usage',
  'memory_usage',
  'disk_usage',
  'uptime',
  'summary_ok',
];

function formatValue(v) {
  if (v === null || v === undefined) return '-';
  if (typeof v === 'object') {
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

function summaryToItems(summary) {
  if (!summary || typeof summary !== 'object') return [];
  return Object.entries(summary).map(([key, val]) => ({
    key,
    label: key,
    value: <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}>{formatValue(val)}</pre>,
  }));
}

function orderedSummaryRows(summary) {
  if (!summary || typeof summary !== 'object') return [];
  const used = new Set();
  const rows = [];
  SUMMARY_KEY_ORDER.forEach((key) => {
    if (Object.hasOwn(summary, key)) {
      rows.push({ key, label: key, value: summary[key] });
      used.add(key);
    }
  });
  Object.entries(summary).forEach(([key, value]) => {
    if (!used.has(key)) {
      rows.push({ key, label: key, value });
    }
  });
  return rows;
}

function parsePercent(value) {
  const n = Number(String(value ?? '').replaceAll('%', '').trim());
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, n));
}

function DiagnosticValue({ keyName, value }) {
  if (typeof value === 'boolean') {
    return <Tag color={value ? 'success' : 'error'}>{value ? 'true' : 'false'}</Tag>;
  }

  const percent = parsePercent(value);
  if (String(keyName || '').endsWith('_usage') && percent !== null) {
    return (
      <span className="beacon-diagnostics-meter">
        <span className="beacon-diagnostics-meter__value">{formatValue(value)}</span>
        <Progress
          percent={percent}
          showInfo={false}
          size="small"
          status={percent >= 90 ? 'exception' : percent >= 75 ? 'active' : 'normal'}
        />
      </span>
    );
  }

  return <span className="beacon-diagnostics-value-text">{formatValue(value)}</span>;
}

function DiagnosticsKvList({ rows }) {
  if (!Array.isArray(rows) || !rows.length) {
    return <Text type="secondary">暂无诊断数据</Text>;
  }
  return (
    <div className="beacon-diagnostics-kv">
      {rows.map((item) => (
        <div className="beacon-diagnostics-kv__row" key={item.key || item.label}>
          <div className="beacon-diagnostics-kv__label">{item.label}</div>
          <div className="beacon-diagnostics-kv__value">
            <DiagnosticValue keyName={item.key || item.label} value={item.value} />
          </div>
        </div>
      ))}
    </div>
  );
}

function SinkMetric({ label, value, tone = 'slate' }) {
  return (
    <div className={`beacon-diagnostics-metric beacon-diagnostics-metric--${tone}`}>
      <span className="beacon-diagnostics-metric__label">{label}</span>
      <span className="beacon-diagnostics-metric__value">{value}</span>
    </div>
  );
}

function ExportFact({ label, value }) {
  return (
    <div className="beacon-diagnostics-export-row">
      <span className="beacon-diagnostics-export-row__label">{label}</span>
      <span className="beacon-diagnostics-export-row__value">{value}</span>
    </div>
  );
}

function renderOptionList(options, labelKey = 'label', valueKey = 'value') {
  if (!Array.isArray(options) || !options.length) return <Text type="secondary">无</Text>;
  return (
    <Space wrap size={[4, 4]}>
      {options.map((opt, i) => (
        <Tag key={`${opt[valueKey] ?? i}-${i}`}>{opt[labelKey] ?? formatValue(opt)}</Tag>
      ))}
    </Space>
  );
}

function formatSummaryLabel(key) {
  const mapping = {
    pending_count: '待处理数量',
    failed_count: '失败数量',
    enabled_count: '已启用数量',
    disabled_count: '未启用数量',
  };
  return mapping[String(key || '').trim()] || String(key || '').replaceAll('_', ' ');
}

function normalizeTaskPlanTime(value, fallback = '00:00') {
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
  const numericMask = Number(mask || 0);
  const days = [];
  for (let bit = 0; bit < 7; bit += 1) {
    if ((numericMask & (1 << bit)) !== 0) {
      days.push(bit + 1);
    }
  }
  return days.length ? days : TASK_PLAN_DAY_OPTIONS.map((item) => item.value);
}

function daysOfWeekToMask(days) {
  return (Array.isArray(days) ? days : []).reduce((mask, value) => {
    const day = Number(value || 0);
    if (day >= 1 && day <= 7) {
      return mask | (1 << (day - 1));
    }
    return mask;
  }, 0) || 127;
}

function snakeTaskTypeToExternal(value) {
  const raw = String(value || '').trim();
  if (Object.hasOwn(TASK_PLAN_TYPE_LABELS, raw)) {
    return raw;
  }
  const mapping = {
    restart_software: 'restartSoftware',
    restart_system: 'restartSystem',
    scan_offline_streams: 'scanOfflineStreams',
    control_start: 'controlStart',
    control_stop: 'controlStop',
    forward_start: 'forwardStart',
    forward_stop: 'forwardStop',
  };
  return mapping[raw] || 'restartSoftware';
}

function externalTaskTypeToSnake(value) {
  const mapping = {
    restartSoftware: 'restart_software',
    restartSystem: 'restart_system',
    scanOfflineStreams: 'scan_offline_streams',
    controlStart: 'control_start',
    controlStop: 'control_stop',
    forwardStart: 'forward_start',
    forwardStop: 'forward_stop',
  };
  return mapping[String(value || '').trim()] || 'restart_software';
}

function buildDefaultTaskPlanForm() {
  return {
    code: '',
    name: '',
    enabled: true,
    taskType: 'restartSoftware',
    scheduleType: 'daily',
    runTime: '00:00',
    intervalSeconds: 60,
    daysOfWeek: TASK_PLAN_DAY_OPTIONS.map((item) => item.value),
    targetCodes: '',
    optionsJson: '',
  };
}

function buildEditTaskPlanForm(row) {
  return {
    code: String(row?.code || '').trim(),
    name: String(row?.name || '').trim(),
    enabled: Boolean(row?.enabled),
    taskType: snakeTaskTypeToExternal(row?.task_type),
    scheduleType: String(row?.schedule_type || 'daily').trim() === 'interval' ? 'interval' : 'daily',
    runTime: normalizeTaskPlanTime(row?.run_time, '00:00'),
    intervalSeconds: Number(row?.interval_seconds || 60) || 60,
    daysOfWeek: daysMaskToDaysOfWeek(row?.days_mask),
    targetCodes: String(row?.target_codes || '').trim(),
    optionsJson: String(row?.options_json || '').trim(),
  };
}

function formatTaskPlanType(row) {
  return TASK_PLAN_TYPE_LABELS[snakeTaskTypeToExternal(row?.task_type)] || row?.task_type || '-';
}

function formatTaskPlanSchedule(row) {
  const scheduleType = String(row?.schedule_type || '').trim();
  if (scheduleType === 'interval') {
    const seconds = Number(row?.interval_seconds || 0) || 0;
    return `每 ${seconds || 60} 秒`;
  }
  const runTime = normalizeTaskPlanTime(row?.run_time, '00:00');
  const days = daysMaskToDaysOfWeek(row?.days_mask).map((value) => TASK_PLAN_DAY_OPTIONS.find((item) => item.value === value)?.label || value);
  const dayLabel = days.length === 7 ? '每天' : days.join(' / ');
  return `${dayLabel} · ${runTime}`;
}

export default function DiagnosticsPage() {
  const { message } = App.useApp();
  const { data, loading, error, run } = useApi(API.diagnostics);
  const [cleanupForm] = Form.useForm();
  const [outboxForm] = Form.useForm();
  const [logForm] = Form.useForm();
  const [taskPlans, setTaskPlans] = useState([]);
  const [taskPlansLoading, setTaskPlansLoading] = useState(false);
  const [taskPlansError, setTaskPlansError] = useState(null);
  const [taskPlanModalOpen, setTaskPlanModalOpen] = useState(false);
  const [taskPlanModalMode, setTaskPlanModalMode] = useState('add');
  const [taskPlanForm, setTaskPlanForm] = useState(() => buildDefaultTaskPlanForm());
  const [taskPlanSubmitting, setTaskPlanSubmitting] = useState(false);
  const [taskPlanActionCode, setTaskPlanActionCode] = useState('');
  const [taskPlanPendingDelete, setTaskPlanPendingDelete] = useState(null);

  const summaryRows = useMemo(() => orderedSummaryRows(data?.summary || {}), [data?.summary]);
  const toolbox = data?.ops_toolbox || {};
  const cleanupDefaults = toolbox.cleanup?.defaults || {};
  const outboxDefaults = toolbox.outbox?.defaults || {};
  const loggingDefaults = toolbox.logging?.defaults || {};
  const sinkSummary = toolbox.sink_test?.summary || {};
  const outboxSummary = toolbox.outbox?.summary || {};
  const sinkEnabledCount = Number(sinkSummary.enabled_count ?? 0) || 0;
  const sinkDisabledCount = Number(sinkSummary.disabled_count ?? 0) || 0;
  const sinkTotalCount = sinkEnabledCount + sinkDisabledCount;
  const sinkEnabledPercent = sinkTotalCount > 0 ? Math.round((sinkEnabledCount / sinkTotalCount) * 100) : 0;

  const loadTaskPlans = useCallback(async () => {
    setTaskPlansLoading(true);
    setTaskPlansError(null);
    try {
      const payload = await apiPost(API.taskPlanList, {});
      setTaskPlans(Array.isArray(payload) ? payload : []);
    } catch (e) {
      setTaskPlans([]);
      setTaskPlansError(e);
    } finally {
      setTaskPlansLoading(false);
    }
  }, []);

  useEffect(() => {
    cleanupForm.setFieldsValue({
      targets: cleanupDefaults.selected_targets || ['metrics_cache'],
      dry_run: cleanupDefaults.dry_run !== false,
      log_retention_days: cleanupDefaults.log_retention_days ?? 7,
      tmp_max_age_hours: cleanupDefaults.tmp_max_age_hours ?? 24,
    });
  }, [cleanupForm, cleanupDefaults]);

  useEffect(() => {
    outboxForm.setFieldsValue({
      outbox_id: 0,
      event_id: '',
      sink_type: '',
      reset_attempts: Boolean(outboxDefaults.reset_attempts),
    });
  }, [outboxForm, outboxDefaults]);

  useEffect(() => {
    logForm.setFieldsValue({
      level: loggingDefaults.level ?? undefined,
      logger: loggingDefaults.logger ?? '',
    });
  }, [logForm, loggingDefaults]);

  useEffect(() => {
    loadTaskPlans();
  }, [loadTaskPlans]);

  const postOps = async (url, body, ok) => {
    try {
      await apiPost(url, body);
      message.success(ok || '已执行');
    } catch (e) {
      message.error(e?.message || '失败');
    }
  };

  const runCleanup = async () => {
    const v = await cleanupForm.validateFields();
    await postOps(
      API.opsCleanup,
      {
        targets: v.targets,
        dry_run: v.dry_run,
        log_retention_days: v.log_retention_days,
        tmp_max_age_hours: v.tmp_max_age_hours,
      },
      v.dry_run ? '清理预览已完成，未删除数据' : '清理已执行',
    );
  };

  const runOutbox = async () => {
    const v = await outboxForm.validateFields();
    await postOps(
      API.opsOutboxReplay,
      {
        outbox_id: v.outbox_id || 0,
        event_id: (v.event_id || '').trim(),
        sink_type: v.sink_type || '',
        reset_attempts: Boolean(v.reset_attempts),
      },
      '消息已重新投递',
    );
  };

  const runLogLevel = async () => {
    const v = await logForm.validateFields();
    await postOps(API.opsLoggingSetLevel, { level: v.level, logger: v.logger || '' }, '日志级别已调整');
  };

  const runSinkTest = async () => {
    await postOps(API.alarmSinksTestSend, {}, '测试告警已发送');
  };

  const openAddTaskPlanModal = useCallback(() => {
    setTaskPlanModalMode('add');
    setTaskPlanForm(buildDefaultTaskPlanForm());
    setTaskPlanModalOpen(true);
  }, []);

  const openEditTaskPlanModal = useCallback((row) => {
    setTaskPlanModalMode('edit');
    setTaskPlanForm(buildEditTaskPlanForm(row));
    setTaskPlanModalOpen(true);
  }, []);

  const updateTaskPlanForm = useCallback((key, value) => {
    setTaskPlanForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const submitTaskPlan = useCallback(async () => {
    const payload = {
      code: String(taskPlanForm.code || '').trim(),
      name: String(taskPlanForm.name || '').trim(),
      enabled: Boolean(taskPlanForm.enabled),
      taskType: String(taskPlanForm.taskType || 'restartSoftware').trim() || 'restartSoftware',
      scheduleType: String(taskPlanForm.scheduleType || 'daily').trim() === 'interval' ? 'interval' : 'daily',
      daysOfWeek: Array.isArray(taskPlanForm.daysOfWeek) && taskPlanForm.daysOfWeek.length
        ? taskPlanForm.daysOfWeek.map(Number).filter((item) => Number.isInteger(item) && item >= 1 && item <= 7)
        : TASK_PLAN_DAY_OPTIONS.map((item) => item.value),
      targetCodes: String(taskPlanForm.targetCodes || '').trim(),
      optionsJson: String(taskPlanForm.optionsJson || '').trim(),
    };

    if (!payload.code) {
      message.warning('请填写计划编码');
      return;
    }
    if (!payload.name) {
      message.warning('请填写计划名称');
      return;
    }

    if (payload.scheduleType === 'interval') {
      const intervalValue = Number(taskPlanForm.intervalSeconds || 0) || 0;
      payload.intervalSeconds = intervalValue > 0 ? intervalValue : 60;
    } else {
      payload.runTime = normalizeTaskPlanTime(taskPlanForm.runTime, '00:00');
    }

    setTaskPlanSubmitting(true);
    try {
      const result = await apiPost(taskPlanModalMode === 'add' ? API.taskPlanAdd : API.taskPlanEdit, payload);
      const nextRow = {
        ...taskPlanForm,
        ...result,
        code: payload.code,
        name: payload.name,
        enabled: payload.enabled,
        task_type: externalTaskTypeToSnake(payload.taskType),
        schedule_type: payload.scheduleType,
        run_time: payload.runTime || '',
        interval_seconds: payload.intervalSeconds || 0,
        days_mask: daysOfWeekToMask(payload.daysOfWeek),
        target_codes: payload.targetCodes,
        options_json: payload.optionsJson,
      };
      setTaskPlans((prev) => {
        if (taskPlanModalMode === 'add') {
          return [nextRow, ...prev];
        }
        return prev.map((row) => (row.code === payload.code ? { ...row, ...nextRow } : row));
      });
      message.success(taskPlanModalMode === 'add' ? '任务计划已新增' : '任务计划已更新');
      setTaskPlanModalOpen(false);
    } catch (e) {
      message.error(e?.message || '保存任务计划失败');
    } finally {
      setTaskPlanSubmitting(false);
    }
  }, [message, taskPlanForm, taskPlanModalMode]);

  const toggleTaskPlan = useCallback(async (row) => {
    setTaskPlanActionCode(row.code);
    try {
      await apiPost(API.taskPlanEdit, {
        code: row.code,
        enabled: !row.enabled,
      });
      setTaskPlans((prev) => prev.map((item) => (
        item.code === row.code
          ? { ...item, enabled: !row.enabled }
          : item
      )));
      message.success(row.enabled ? '任务计划已停用' : '任务计划已启用');
    } catch (e) {
      message.error(e?.message || '切换任务计划状态失败');
    } finally {
      setTaskPlanActionCode('');
    }
  }, [message]);

  const deleteTaskPlan = useCallback(async (row) => {
    setTaskPlanActionCode(row.code);
    try {
      await apiPost(API.taskPlanDelete, { code: row.code });
      setTaskPlans((prev) => prev.filter((item) => item.code !== row.code));
      message.success('任务计划已删除');
      setTaskPlanPendingDelete(null);
    } catch (e) {
      message.error(e?.message || '删除任务计划失败');
    } finally {
      setTaskPlanActionCode('');
    }
  }, [message]);

  const taskPlanColumns = [
    {
      title: '计划',
      key: 'plan',
      ellipsis: true,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text>{row.name || row.code || '-'}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {row.code || '-'}
          </Text>
        </Space>
      ),
    },
    {
      title: '任务类型',
      dataIndex: 'task_type',
      width: 140,
      render: (_, row) => formatTaskPlanType(row),
    },
    {
      title: '调度',
      key: 'schedule',
      width: 180,
      render: (_, row) => formatTaskPlanSchedule(row),
    },
    {
      title: '目标',
      dataIndex: 'target_codes',
      ellipsis: true,
      render: (value) => value || '-',
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (value) => (value ? <Tag color="success">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '最近执行',
      dataIndex: 'last_run_at',
      width: 170,
      render: (value) => formatTime(value),
    },
    {
      title: '最近结果',
      dataIndex: 'last_result_msg',
      ellipsis: true,
      render: (value, row) => value || row.last_result_code || '-',
    },
    {
      title: '更新时间',
      dataIndex: 'update_time',
      width: 170,
      render: (value) => formatTime(value),
    },
    {
      title: '操作',
      key: 'ops',
      width: 180,
      fixed: 'right',
      render: (_, row) => (
        <Space size={0} wrap>
          <Button type="link" size="small" autoInsertSpace={false} onClick={() => openEditTaskPlanModal(row)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            autoInsertSpace={false}
            loading={taskPlanActionCode === row.code}
            onClick={() => toggleTaskPlan(row)}
          >
            {row.enabled ? '停用' : '启用'}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            autoInsertSpace={false}
            onClick={() => setTaskPlanPendingDelete(row)}
          >
            {taskPlanPendingDelete?.code === row.code ? '待确认' : '删除'}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="系统诊断"
        icon={<ToolOutlined />}
        description="系统诊断探针与健康检查"
        extra={(
          <Button icon={<ReloadOutlined />} onClick={() => { run(); loadTaskPlans(); }}>
            刷新
          </Button>
        )}
      />

      {error ? <Alert type="error" message={error.message || '加载失败'} style={{ marginBottom: 16 }} showIcon /> : null}

      <Spin spinning={loading}>
        <div
          className="beacon-support-grid beacon-equal-height-grid"
          data-testid="diagnostics-overview-grid"
          data-layout="full-width"
          style={{ marginBottom: 16 }}
        >
          <SummaryCard
            title="诊断概要"
            meta="运行态摘要"
            icon={<ToolOutlined />}
            tone="blue"
            className="beacon-diagnostics-summary-card"
            bodyStyle={{ padding: '10px 14px' }}
          >
            <DiagnosticsKvList rows={summaryRows} />
          </SummaryCard>

          <Card
            className="beacon-panel-card beacon-panel-card--tone-cyan"
            size="small"
            title={<PanelTitle title="告警投递" meta="通道状态与待投递消息" icon={<DeploymentUnitOutlined />} tone="cyan" />}
          >
            <div className="beacon-diagnostics-metric-grid">
              <SinkMetric label="已启用" value={sinkEnabledCount} tone="green" />
              <SinkMetric label="未启用" value={sinkDisabledCount} tone="slate" />
              <SinkMetric label="待投递" value={outboxSummary.pending_count ?? 0} tone="cyan" />
              <SinkMetric label="失败" value={outboxSummary.failed_count ?? 0} tone="orange" />
            </div>
            <Space className="beacon-diagnostics-sink-list" direction="vertical" size={10}>
              <div className="beacon-diagnostics-sink-list__section">
                <Text type="secondary">已启用通道</Text>
                <div>{renderOptionList(toolbox.sink_test?.enabled_sinks, 'label', 'name')}</div>
              </div>
              <Progress percent={sinkEnabledPercent} size="small" status={sinkEnabledCount ? 'active' : 'normal'} />
              <div className="beacon-diagnostics-sink-list__section">
                <Text type="secondary">未启用通道</Text>
                <div>{renderOptionList(toolbox.sink_test?.disabled_sinks, 'label', 'name')}</div>
              </div>
            </Space>
          </Card>

          <Card
            className="beacon-panel-card beacon-panel-card--tone-slate"
            size="small"
            title={<PanelTitle title="诊断导出" meta="下载当前诊断包" icon={<CloudDownloadOutlined />} tone="slate" />}
          >
            <div className="beacon-diagnostics-export-list">
              <ExportFact label="导出文件" value="ZIP 诊断包" />
              <ExportFact label="任务计划数" value={taskPlans.length} />
              <ExportFact label="工具箱区块" value={Object.keys(toolbox || {}).length} />
            </div>
            <div className="beacon-diagnostics-export-action">
              <Typography.Link href={API.opsDiagnosticsExport} target="_blank" rel="noreferrer">
                导出 ZIP 包
              </Typography.Link>
            </div>
          </Card>
        </div>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-blue"
          title={<PanelTitle title="运维配置概览" meta="清理策略、消息重放、日志配置与告警投递" icon={<DatabaseOutlined />} tone="blue" />}
          size="small"
          style={{ marginBottom: 16 }}
        >
          <Collapse
            size="small"
            ghost
            items={[
              {
                key: 'cleanup',
                label: '清理策略',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Text strong>目标</Text>
                    {renderOptionList(toolbox.cleanup?.target_options, 'label', 'value')}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      默认: {formatValue(toolbox.cleanup?.defaults)}
                    </Text>
                  </Space>
                ),
              },
              {
                key: 'outbox',
                label: '消息重放',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <List
                      size="small"
                      dataSource={summaryToItems(toolbox.outbox?.summary || {})}
                      renderItem={(item) => (
                        <List.Item>
                          <Space direction="vertical" size={0}>
                            <Text type="secondary" style={{ fontSize: 12 }}>{formatSummaryLabel(item.key)}</Text>
                            {item.value}
                          </Space>
                        </List.Item>
                      )}
                    />
                    <Text strong>投递通道</Text>
                    {renderOptionList(toolbox.outbox?.sink_options, 'label', 'value')}
                  </Space>
                ),
              },
              {
                key: 'logging',
                label: '日志配置',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Text strong>级别</Text>
                    {renderOptionList((toolbox.logging?.level_options || []).map((x) => ({ label: x, value: x })))}
                    <Text strong>日志模块</Text>
                    {renderOptionList(toolbox.logging?.logger_options, 'label', 'value')}
                  </Space>
                ),
              },
              {
                key: 'sink_test',
                label: '告警投递检测',
                forceRender: true,
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <List
                      size="small"
                      dataSource={summaryToItems(toolbox.sink_test?.summary || {})}
                      renderItem={(item) => (
                        <List.Item>
                          <Space direction="vertical" size={0}>
                            <Text type="secondary" style={{ fontSize: 12 }}>{formatSummaryLabel(item.key)}</Text>
                            {item.value}
                          </Space>
                        </List.Item>
                      )}
                    />
                    <Text strong>已启用</Text>
                    {renderOptionList(toolbox.sink_test?.enabled_sinks, 'label', 'name')}
                    <Text strong>未启用</Text>
                    {renderOptionList(toolbox.sink_test?.disabled_sinks, 'label', 'name')}
                  </Space>
                ),
              },
            ]}
          />
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-green"
          title={<PanelTitle title="任务计划" meta="定时运维任务编排" icon={<PlusOutlined />} tone="green" />}
          size="small"
          style={{ marginBottom: 16 }}
          extra={(
            <Space wrap>
              <Button size="small" icon={<ReloadOutlined />} onClick={loadTaskPlans}>
                刷新任务计划
              </Button>
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openAddTaskPlanModal}>
                新增任务计划
              </Button>
            </Space>
          )}
        >
          {taskPlansError ? (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message={taskPlansError.message || '加载任务计划失败'}
            />
          ) : null}

          <ProTable
            rowKey={(row) => row.code || row.id}
            columns={taskPlanColumns}
            dataSource={taskPlans}
            loading={taskPlansLoading}
            pagination={{ pageSize: 8 }}
            scroll={{ x: 980 }}
          />
        </Card>

        <Card
          className="beacon-panel-card beacon-panel-card--tone-orange"
          title={<PanelTitle title="执行运维操作" meta="按类别执行清理、重放与测试" icon={<ToolOutlined />} tone="orange" />}
          size="small"
        >
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <div>
              <Text strong>清理</Text>
              <Form form={cleanupForm} layout="vertical" style={{ maxWidth: 480, marginTop: 8 }}>
                <Form.Item name="targets" label="目标">
                  <Select
                    mode="multiple"
                    options={(toolbox.cleanup?.target_options || []).map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Form.Item>
                <Form.Item name="dry_run" label="仅预览，不执行清理" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item name="log_retention_days" label="日志保留天数">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="tmp_max_age_hours" label="临时文件最长保留(小时)">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
                <Button type="primary" onClick={runCleanup}>
                  执行清理
                </Button>
              </Form>
            </div>

            <div>
              <Text strong>消息重放</Text>
              <Form form={outboxForm} layout="vertical" style={{ maxWidth: 480, marginTop: 8 }}>
                <Form.Item name="outbox_id" label="待投递记录 ID（与事件 ID 二选一）">
                  <InputNumber min={0} style={{ width: '100%' }} placeholder="0 表示不用" />
                </Form.Item>
                <Form.Item name="event_id" label="事件 ID">
                  <Input placeholder="evt-..." />
                </Form.Item>
                <Form.Item name="sink_type" label="投递通道">
                  <Select
                    allowClear
                    options={(toolbox.outbox?.sink_options || []).map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Form.Item>
                <Form.Item name="reset_attempts" label="重置重试次数" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Button type="primary" onClick={runOutbox}>
                  重放
                </Button>
              </Form>
            </div>

            <div>
              <Text strong>日志级别</Text>
              <Form form={logForm} layout="vertical" style={{ maxWidth: 480, marginTop: 8 }}>
                <Form.Item name="level" label="级别" rules={[{ required: true }]}>
                  <Select options={(toolbox.logging?.level_options || []).map((x) => ({ value: x, label: x }))} />
                </Form.Item>
                <Form.Item name="logger" label="日志模块（默认全部）">
                  <Select
                    allowClear
                    options={(toolbox.logging?.logger_options || []).map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Form.Item>
                <Button type="primary" onClick={runLogLevel}>
                  应用
                </Button>
              </Form>
            </div>

            <div>
              <Text strong>诊断包导出</Text>
              <div style={{ marginTop: 8 }}>
                <Link href={API.opsDiagnosticsExport} target="_blank" rel="noreferrer">
                  下载诊断导出（ZIP）
                </Link>
              </div>
            </div>

            <div>
              <Text strong>告警投递测试</Text>
              <div style={{ marginTop: 8 }}>
                <Button onClick={runSinkTest}>向已启用通道发送测试告警</Button>
              </div>
            </div>
          </Space>
        </Card>
      </Spin>

      <Modal
        title={taskPlanModalMode === 'add' ? '新增任务计划' : '编辑任务计划'}
        open={taskPlanModalOpen}
        onCancel={() => {
          if (!taskPlanSubmitting) {
            setTaskPlanModalOpen(false);
          }
        }}
        footer={[
          <Button
            key="cancel"
            autoInsertSpace={false}
            disabled={taskPlanSubmitting}
            onClick={() => setTaskPlanModalOpen(false)}
          >
            取消
          </Button>,
          <Button
            key="save"
            type="primary"
            autoInsertSpace={false}
            loading={taskPlanSubmitting}
            onClick={submitTaskPlan}
          >
            保存
          </Button>,
        ]}
        destroyOnHidden
      >
        <div style={{ display: 'grid', gap: 12 }}>
          <div>
            <label htmlFor="task-plan-code" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
              计划编码
            </label>
            <Input
              id="task-plan-code"
              aria-label="计划编码"
              value={taskPlanForm.code}
              disabled={taskPlanModalMode === 'edit'}
              onChange={(event) => updateTaskPlanForm('code', event.target.value)}
            />
          </div>

          <div>
            <label htmlFor="task-plan-name" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
              计划名称
            </label>
            <Input
              id="task-plan-name"
              aria-label="计划名称"
              value={taskPlanForm.name}
              onChange={(event) => updateTaskPlanForm('name', event.target.value)}
            />
          </div>

          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <div>
              <label htmlFor="task-plan-type" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                任务类型
              </label>
              <select
                id="task-plan-type"
                aria-label="任务类型"
                value={taskPlanForm.taskType}
                onChange={(event) => updateTaskPlanForm('taskType', event.target.value)}
                style={{
                  width: '100%',
                  height: 32,
                  borderRadius: 6,
                  border: '1px solid #d9d9d9',
                  padding: '0 11px',
                  background: '#fff',
                }}
              >
                {TASK_PLAN_TYPE_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="task-plan-schedule-type" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                调度方式
              </label>
              <select
                id="task-plan-schedule-type"
                aria-label="调度方式"
                value={taskPlanForm.scheduleType}
                onChange={(event) => updateTaskPlanForm('scheduleType', event.target.value)}
                style={{
                  width: '100%',
                  height: 32,
                  borderRadius: 6,
                  border: '1px solid #d9d9d9',
                  padding: '0 11px',
                  background: '#fff',
                }}
              >
                {Object.entries(TASK_PLAN_SCHEDULE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {taskPlanForm.scheduleType === 'interval' ? (
            <div>
              <label htmlFor="task-plan-interval" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                间隔秒数
              </label>
              <Input
                id="task-plan-interval"
                aria-label="间隔秒数"
                value={String(taskPlanForm.intervalSeconds ?? '')}
                onChange={(event) => updateTaskPlanForm('intervalSeconds', event.target.value)}
              />
            </div>
          ) : (
            <div>
              <label htmlFor="task-plan-run-time" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
                执行时间
              </label>
              <Input
                id="task-plan-run-time"
                aria-label="执行时间"
                placeholder="00:00"
                value={taskPlanForm.runTime}
                onChange={(event) => updateTaskPlanForm('runTime', event.target.value)}
              />
            </div>
          )}

          <div>
            <div style={{ marginBottom: 6, fontSize: 12, fontWeight: 600 }}>执行日期</div>
            <Checkbox.Group
              value={taskPlanForm.daysOfWeek}
              options={TASK_PLAN_DAY_OPTIONS}
              onChange={(value) => updateTaskPlanForm('daysOfWeek', value)}
            />
          </div>

          <div>
            <label htmlFor="task-plan-target-codes" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
              目标编号
            </label>
            <Input
              id="task-plan-target-codes"
              aria-label="目标编号"
              placeholder="多个编号可直接传 CSV"
              value={taskPlanForm.targetCodes}
              onChange={(event) => updateTaskPlanForm('targetCodes', event.target.value)}
            />
          </div>

          <div>
            <label htmlFor="task-plan-options-json" style={{ display: 'block', marginBottom: 6, fontSize: 12, fontWeight: 600 }}>
              扩展参数 JSON
            </label>
            <TextArea
              id="task-plan-options-json"
              aria-label="扩展参数 JSON"
              rows={3}
              value={taskPlanForm.optionsJson}
              onChange={(event) => updateTaskPlanForm('optionsJson', event.target.value)}
            />
          </div>

          <div>
            <Checkbox checked={taskPlanForm.enabled} onChange={(event) => updateTaskPlanForm('enabled', event.target.checked)}>
              启用计划
            </Checkbox>
          </div>
        </div>
      </Modal>

      <Modal
        title="删除任务计划"
        open={Boolean(taskPlanPendingDelete)}
        onCancel={() => {
          if (!taskPlanActionCode) {
            setTaskPlanPendingDelete(null);
          }
        }}
        footer={[
          <Button
            key="cancel"
            autoInsertSpace={false}
            disabled={Boolean(taskPlanActionCode)}
            onClick={() => setTaskPlanPendingDelete(null)}
          >
            取消
          </Button>,
          <Button
            key="confirm"
            type="primary"
            autoInsertSpace={false}
            loading={Boolean(taskPlanActionCode)}
            onClick={() => {
              if (taskPlanPendingDelete) {
                deleteTaskPlan(taskPlanPendingDelete);
              }
            }}
          >
            确定
          </Button>,
        ]}
        destroyOnHidden
      >
        <Text>
          确认删除 {taskPlanPendingDelete?.name || taskPlanPendingDelete?.code || '当前计划'}？
        </Text>
      </Modal>
    </div>
  );
}

import React from 'react';
import PropTypes from 'prop-types';
import { Tag } from 'antd';
import './StatusBadge.css';

const STATUS_MAP = {
  online: { color: 'success', text: '在线' },
  offline: { color: 'default', text: '离线' },
  running: { color: 'processing', text: '运行中' },
  stopped: { color: 'error', text: '已停止' },
  warning: { color: 'warning', text: '警告' },
  error: { color: 'error', text: '错误' },
  success: { color: 'success', text: '成功' },
  pending: { color: 'default', text: '待处理' },
  new: { color: 'blue', text: '新告警' },
  acknowledged: { color: 'orange', text: '已确认' },
  resolved: { color: 'green', text: '已解决' },
  dismissed: { color: 'default', text: '已忽略' },
  assigned: { color: 'purple', text: '已分配' },
  in_progress: { color: 'processing', text: '处理中' },
  escalated: { color: 'red', text: '已升级' },
  enabled: { color: 'success', text: '启用' },
  disabled: { color: 'default', text: '禁用' },
};

const ALARM_LEVEL_MAP = {
  1: { color: 'red', text: '紧急' },
  2: { color: 'orange', text: '重要' },
  3: { color: 'gold', text: '次要' },
  4: { color: 'blue', text: '提示' },
};

const DOT_COLOR_MAP = {
  success: 'var(--color-status-online, #52c41a)',
  processing: 'var(--beacon-tone-blue-icon-color, #2563eb)',
  error: 'var(--color-status-error, #ff4d4f)',
  warning: 'var(--color-status-warning, #faad14)',
  default: 'var(--beacon-text-faint, #94a3b8)',
  blue: 'var(--beacon-tone-blue-icon-color, #2563eb)',
  red: 'var(--color-status-error, #ff4d4f)',
  orange: '#fa8c16',
  gold: '#faad14',
  green: 'var(--color-status-online, #52c41a)',
  purple: '#722ed1',
};

const PULSE_STATUSES = new Set(['running', 'processing', 'in_progress']);

export default function StatusBadge({ status, text, type = 'status', variant = 'tag' }) {
  let config;
  if (type === 'alarm_level') {
    config = ALARM_LEVEL_MAP[status] || { color: 'default', text: `级别${status}` };
  } else {
    config = STATUS_MAP[status] || { color: 'default', text: status || '未知' };
  }

  const label = text || config.text;

  if (variant === 'dot') {
    const dotColor = DOT_COLOR_MAP[config.color] || DOT_COLOR_MAP.default;
    const shouldPulse = PULSE_STATUSES.has(status);
    return (
      <span className="beacon-status-dot">
        <span
          className={`beacon-status-dot__circle${shouldPulse ? ' beacon-status-dot__circle--pulse' : ''}`}
          style={{ background: dotColor }}
        />
        <span className="beacon-status-dot__label">{label}</span>
      </span>
    );
  }

  return <Tag color={config.color}>{label}</Tag>;
}

export function AlarmLevelBadge({ level }) {
  return <StatusBadge status={level} type="alarm_level" />;
}

export function WorkflowStatusBadge({ status }) {
  return <StatusBadge status={status} />;
}

StatusBadge.propTypes = {
  status: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  text: PropTypes.node,
  type: PropTypes.oneOf(['status', 'alarm_level']),
  variant: PropTypes.oneOf(['tag', 'dot']),
};

AlarmLevelBadge.propTypes = {
  level: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
};

WorkflowStatusBadge.propTypes = {
  status: PropTypes.string,
};

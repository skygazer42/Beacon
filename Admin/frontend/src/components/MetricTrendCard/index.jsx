import React, { useMemo } from 'react';
import PropTypes from 'prop-types';
import { Card, Typography } from 'antd';
import { buildSparklineGeometry, getTrendDelta } from '../../utils/trends';

const { Text } = Typography;

export default function MetricTrendCard({
  title,
  value,
  history,
  dataKey,
  color = '#2563eb',
  unit = 'pt',
}) {
  const geometry = useMemo(
    () => buildSparklineGeometry(history, dataKey),
    [history, dataKey]
  );

  const delta = useMemo(
    () => getTrendDelta(history, dataKey),
    [history, dataKey]
  );

  const deltaPrefix = delta >= 0 ? '+' : '';
  const trendText = delta === null
    ? '采样中'
    : `较首笔 ${deltaPrefix}${(delta * 100).toFixed(1)} ${unit}`;

  const firstLabel = history?.[0]?.label || '--:--:--';
  const lastLabel = history?.[history.length - 1]?.label || '--:--:--';

  return (
    <Card
      className="beacon-panel-card beacon-trend-card"
      size="small"
      styles={{ body: { padding: '12px 14px' } }}
    >
      <div className="beacon-trend-card__header">
        <div className="beacon-trend-card__label">
          <span className="beacon-trend-card__dot" style={{ background: color }} />
          <span>{title}</span>
        </div>
        <Text type="secondary" style={{ fontSize: 12, textAlign: 'right' }}>
          {trendText}
        </Text>
      </div>

      <div className="beacon-trend-card__value">{value}</div>

      <div className="beacon-trend-card__chart-shell">
        <svg viewBox="0 0 220 72" width="100%" height="72" aria-hidden="true" focusable="false">
          {geometry.areaPoints ? (
            <polygon
              points={geometry.areaPoints}
              fill={color}
              fillOpacity="0.12"
            />
          ) : null}
          {geometry.linePoints ? (
            <polyline
              points={geometry.linePoints}
              fill="none"
              stroke={color}
              strokeWidth="2.5"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ) : null}
          {geometry.lastPoint ? (
            <circle
              cx={geometry.lastPoint.x}
              cy={geometry.lastPoint.y}
              r="3.5"
              fill={color}
              stroke="var(--beacon-surface-panel, #ffffff)"
              strokeWidth="2"
            />
          ) : null}
        </svg>
      </div>

      <div className="beacon-trend-card__footer">
        <span>{firstLabel}</span>
        <span>最近 {history?.length || 0} 次</span>
        <span>{lastLabel}</span>
      </div>
    </Card>
  );
}

MetricTrendCard.propTypes = {
  title: PropTypes.string.isRequired,
  value: PropTypes.node,
  history: PropTypes.arrayOf(PropTypes.shape({
    label: PropTypes.node,
  })).isRequired,
  dataKey: PropTypes.string.isRequired,
  color: PropTypes.string,
  unit: PropTypes.string,
};

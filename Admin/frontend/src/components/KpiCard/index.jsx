import React from 'react';
import PropTypes from 'prop-types';
import { Card, theme } from 'antd';

export default function KpiCard({
  title,
  value,
  suffix,
  prefix,
  icon,
  trend,
  color,
  onClick,
  loading,
  metaItems = [],
}) {
  const { token } = theme.useToken();
  const accentColor = color || token.colorPrimary;

  return (
    <Card
      className="beacon-kpi-card"
      size="small"
      hoverable={!!onClick}
      onClick={onClick}
      style={{ minWidth: 180, width: '100%', cursor: onClick ? 'pointer' : 'default' }}
      styles={{ body: { padding: 0 } }}
      loading={loading}
    >
      <div className="beacon-kpi-card__accent" style={{ background: accentColor }} />
      <div className="beacon-kpi-card__inner">
        <div className="beacon-kpi-card__label">{title}</div>
        <div className="beacon-kpi-card__content">
          {icon ? (
            <div
              className="beacon-kpi-card__icon"
              style={{
                background: `rgba(${hexToRgb(accentColor)}, 0.15)`,
                color: accentColor,
              }}
            >
              {icon}
            </div>
          ) : null}
          <div className="beacon-kpi-card__metric">
            <div className="beacon-kpi-card__value-row">
              {prefix ? <span className="beacon-kpi-card__affix">{prefix}</span> : null}
              <span className="beacon-kpi-card__value" style={{ color: accentColor }}>
                {value ?? '-'}
              </span>
              {suffix ? <span className="beacon-kpi-card__affix">{suffix}</span> : null}
            </div>

            {metaItems.length ? (
              <div className="beacon-kpi-card__meta-row">
                {metaItems.map((item) => (
                  <span className="beacon-kpi-card__meta-item" key={`${title}-${item.label}`}>
                    <span className="beacon-kpi-card__meta-label">{item.label}</span>
                    <strong className="beacon-kpi-card__meta-value">{item.value}</strong>
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </div>
      {trend !== undefined && (
        <div
          className="beacon-kpi-card__trend"
          style={{ color: trend >= 0 ? 'var(--color-status-online)' : 'var(--color-alarm-critical)' }}
        >
          {trend >= 0 ? '+' : ''}{trend}%
        </div>
      )}
    </Card>
  );
}

export function KpiCardGroup({ children }) {
  return (
    <div className="beacon-kpi-card-group beacon-equal-height-grid">
      {children}
    </div>
  );
}

const kpiMetaItemShape = PropTypes.shape({
  label: PropTypes.node.isRequired,
  value: PropTypes.node,
});

KpiCard.propTypes = {
  title: PropTypes.node.isRequired,
  value: PropTypes.node,
  suffix: PropTypes.node,
  prefix: PropTypes.node,
  icon: PropTypes.node,
  trend: PropTypes.number,
  color: PropTypes.string,
  onClick: PropTypes.func,
  loading: PropTypes.bool,
  metaItems: PropTypes.arrayOf(kpiMetaItemShape),
};

KpiCardGroup.propTypes = {
  children: PropTypes.node,
};

/**
 * Convert a hex color string to an "r, g, b" string for use in rgba().
 * Falls back to "0, 0, 0" for non-hex inputs.
 */
function hexToRgb(hex) {
  if (!hex || typeof hex !== 'string') return '0, 0, 0';
  const cleaned = hex.replace('#', '');
  if (!/^[0-9a-fA-F]{3,8}$/.test(cleaned)) return '0, 0, 0';
  const full = cleaned.length === 3
    ? cleaned.split('').map(c => c + c).join('')
    : cleaned;
  const num = Number.parseInt(full.substring(0, 6), 16);
  return `${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}`;
}

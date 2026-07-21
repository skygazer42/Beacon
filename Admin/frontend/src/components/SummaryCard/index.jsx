import React from 'react';
import PropTypes from 'prop-types';
import { Card } from 'antd';

export function PanelTitle({ title, meta, icon, tone = 'slate' }) {
  return (
    <span className="beacon-card-title">
      {icon ? (
        <span className={`beacon-card-title__icon beacon-card-title__icon--${tone}`}>
          {icon}
        </span>
      ) : null}
      <span className="beacon-card-title__text">
        <span className="beacon-card-title__label">{title}</span>
        {meta ? <span className="beacon-card-title__meta">{meta}</span> : null}
      </span>
    </span>
  );
}

PanelTitle.propTypes = {
  title: PropTypes.node.isRequired,
  meta: PropTypes.node,
  icon: PropTypes.node,
  tone: PropTypes.string,
};

export function SummaryList({ items = [] }) {
  return (
    <div className="beacon-summary-kv">
      {items.map((item) => (
        <div className="beacon-summary-kv__row" key={item.key || item.label}>
          <div className="beacon-summary-kv__label">{item.label}</div>
          <div className="beacon-summary-kv__value">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

const summaryItemShape = PropTypes.shape({
  key: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  label: PropTypes.node.isRequired,
  value: PropTypes.node,
});

SummaryList.propTypes = {
  items: PropTypes.arrayOf(summaryItemShape),
};

export default function SummaryCard({
  title,
  items,
  children,
  className = '',
  bodyStyle = {},
  stretch = true,
  extra,
  size = 'small',
  tone = 'slate',
  meta,
  icon,
}) {
  const classes = [
    'beacon-panel-card',
    'beacon-summary-card',
    `beacon-panel-card--tone-${tone}`,
    stretch ? 'beacon-panel-card--stretch' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <Card
      className={classes}
      size={size}
      title={<PanelTitle title={title} meta={meta} icon={icon} tone={tone} />}
      extra={extra}
      styles={{ body: { padding: '12px 16px', ...bodyStyle } }}
    >
      {Array.isArray(items) && items.length ? (
        <div className="beacon-summary-card__main">
          <SummaryList items={items} />
        </div>
      ) : null}
      {children}
    </Card>
  );
}

SummaryCard.propTypes = {
  title: PropTypes.node.isRequired,
  items: PropTypes.arrayOf(summaryItemShape),
  children: PropTypes.node,
  className: PropTypes.string,
  bodyStyle: PropTypes.object,
  stretch: PropTypes.bool,
  extra: PropTypes.node,
  size: PropTypes.string,
  tone: PropTypes.string,
  meta: PropTypes.node,
  icon: PropTypes.node,
};

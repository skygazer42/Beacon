import React from 'react';
import PropTypes from 'prop-types';
import './Skeleton.css';

const TABLE_CELL_WIDTHS = ['58%', '66%', '74%', '62%', '78%'];

function Bone({ className, style }) {
  return <div className={`beacon-skeleton__bone ${className || ''}`} style={style} />;
}

Bone.propTypes = {
  className: PropTypes.string,
  style: PropTypes.object,
};

export function SkeletonCard() {
  return (
    <div className="beacon-skeleton-card">
      <Bone className="beacon-skeleton-card__accent" />
      <Bone className="beacon-skeleton-card__label" />
      <Bone className="beacon-skeleton-card__value" />
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 5 }) {
  return (
    <div className="beacon-skeleton-table">
      <div className="beacon-skeleton-table__head">
        {Array.from({ length: cols }, (_, i) => (
          <Bone key={i} className="beacon-skeleton-table__head-cell" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="beacon-skeleton-table__row">
          {Array.from({ length: cols }, (_, c) => (
            <Bone
              key={c}
              className="beacon-skeleton-table__cell"
              style={{ width: c === 0 ? '80%' : TABLE_CELL_WIDTHS[(r + c) % TABLE_CELL_WIDTHS.length] }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

SkeletonTable.propTypes = {
  rows: PropTypes.number,
  cols: PropTypes.number,
};

export default function SkeletonPage({ kpiCount = 4 }) {
  return (
    <div className="beacon-skeleton-page" role="status" aria-live="polite" aria-busy="true">
      <span className="beacon-skeleton-page__sr-label">正在加载页面</span>
      <div className="beacon-skeleton-page__header">
        <Bone className="beacon-skeleton__bone beacon-skeleton-page__header-icon" />
        <div className="beacon-skeleton-page__header-lines">
          <Bone className="beacon-skeleton__bone beacon-skeleton-page__header-title" />
          <Bone className="beacon-skeleton__bone beacon-skeleton-page__header-desc" />
        </div>
      </div>
      <div className="beacon-skeleton-page__kpi-row">
        {Array.from({ length: kpiCount }, (_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
      <SkeletonTable />
    </div>
  );
}

SkeletonPage.propTypes = {
  kpiCount: PropTypes.number,
};

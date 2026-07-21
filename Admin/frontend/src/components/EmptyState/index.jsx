import React from 'react';
import PropTypes from 'prop-types';
import { InboxOutlined } from '@ant-design/icons';
import './EmptyState.css';

/**
 * Beacon EmptyState — reusable empty / zero-data placeholder.
 *
 * @param {object}      props
 * @param {ReactNode}   [props.icon]         Custom icon (defaults to InboxOutlined)
 * @param {string}      [props.title]        Heading text
 * @param {string}      [props.description]  Supporting copy
 * @param {ReactNode}   [props.action]       Optional call-to-action element (button, link, etc.)
 * @param {'card'|'page'} [props.variant]    Size variant — 'card' (compact) or 'page' (full-page)
 * @param {string}      [props.className]    Additional CSS class
 * @param {object}      [props.style]        Inline style overrides
 */
export default function EmptyState({
  icon,
  title = '\u6682\u65e0\u6570\u636e',
  description = '\u5f53\u524d\u6ca1\u6709\u53ef\u663e\u793a\u7684\u5185\u5bb9',
  action,
  variant = 'card',
  className,
  style,
}) {
  const cls = [
    'beacon-empty-state',
    `beacon-empty-state--${variant}`,
    className,
  ].filter(Boolean).join(' ');

  return (
    <div className={cls} style={style}>
      <div className="beacon-empty-state__icon">
        {icon || <InboxOutlined />}
      </div>
      <h4 className="beacon-empty-state__title">{title}</h4>
      {description && (
        <p className="beacon-empty-state__description">{description}</p>
      )}
      {action && <div className="beacon-empty-state__action">{action}</div>}
    </div>
  );
}

EmptyState.propTypes = {
  icon: PropTypes.node,
  title: PropTypes.node,
  description: PropTypes.node,
  action: PropTypes.node,
  variant: PropTypes.oneOf(['card', 'page']),
  className: PropTypes.string,
  style: PropTypes.object,
};

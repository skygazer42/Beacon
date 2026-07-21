import React from 'react';
import PropTypes from 'prop-types';
import './PageHeader.css';

/**
 * Beacon PageHeader — page-level heading with optional icon, description, and actions.
 *
 * Backward-compatible: existing props (title, icon, extra, children) keep working.
 *
 * @param {object}    props
 * @param {string}    props.title        Page heading text
 * @param {ReactNode} [props.icon]       Leading icon
 * @param {string}    [props.description] Subtitle / secondary description
 * @param {boolean}   [props.display]    When true, renders title in Fraunces display font
 * @param {ReactNode} [props.extra]      Right-aligned actions
 * @param {ReactNode} [props.children]   Inline content after the title (backward compat)
 */
export default function PageHeader({ title, icon, description, display, extra, children }) {
  const titleCls = [
    'beacon-page-header__title',
    display && 'beacon-page-header__title--display',
  ].filter(Boolean).join(' ');

  return (
    <div className="beacon-page-header">
      <div className="beacon-page-header__row">
        <div className="beacon-page-header__left">
          {icon && <span className="beacon-page-header__icon">{icon}</span>}
          <div>
            <h3 className={titleCls}>{title}</h3>
            {description && (
              <p className="beacon-page-header__description">{description}</p>
            )}
          </div>
          {children}
        </div>
        {extra && <div className="beacon-page-header__extra">{extra}</div>}
      </div>
      <div className="beacon-page-header__divider" />
    </div>
  );
}

PageHeader.propTypes = {
  title: PropTypes.node.isRequired,
  icon: PropTypes.node,
  description: PropTypes.node,
  display: PropTypes.bool,
  extra: PropTypes.node,
  children: PropTypes.node,
};

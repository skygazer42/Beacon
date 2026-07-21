import React from 'react';
import PropTypes from 'prop-types';
import { Drawer, Descriptions, Space } from 'antd';
import { SkeletonCard } from '../Skeleton';
import EmptyState from '../EmptyState';
import './DetailDrawer.css';

export default function DetailDrawer({
  open,
  onClose,
  title = '详情',
  width = 640,
  loading = false,
  footer,
  children,
  ...rest
}) {
  let drawerBody = <EmptyState variant="card" title="暂无数据" />;
  if (children) {
    drawerBody = children;
  }
  if (loading) {
    drawerBody = (
      <div className="beacon-detail-drawer__loading">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  return (
    <Drawer
      title={title}
      open={open}
      onClose={onClose}
      width={width}
      destroyOnHidden
      className="beacon-detail-drawer"
      footer={footer && (
        <div className="beacon-detail-drawer__footer">
          <Space>{footer}</Space>
        </div>
      )}
      styles={{ body: { padding: '16px 24px' } }}
      {...rest}
    >
      {drawerBody}
    </Drawer>
  );
}

DetailDrawer.propTypes = {
  open: PropTypes.bool,
  onClose: PropTypes.func,
  title: PropTypes.node,
  width: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  loading: PropTypes.bool,
  footer: PropTypes.node,
  children: PropTypes.node,
};

export function DetailSection({ title, items, column = 2 }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="beacon-detail-section">
      {title && <div className="beacon-detail-section__title">{title}</div>}
      <div className="beacon-detail-section__body">
        <Descriptions column={column} size="small" bordered>
          {items.map((item) => (
            <Descriptions.Item key={item.key || String(item.label)} label={item.label} span={item.span}>
              {item.value ?? '-'}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </div>
    </div>
  );
}

DetailSection.propTypes = {
  title: PropTypes.node,
  items: PropTypes.arrayOf(PropTypes.shape({
    key: PropTypes.string,
    label: PropTypes.node.isRequired,
    value: PropTypes.node,
    span: PropTypes.number,
  })),
  column: PropTypes.number,
};

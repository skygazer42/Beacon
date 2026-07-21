import React, { useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import { Popover, Badge, List, Typography, Button } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import EmptyState from '../EmptyState';

const { Text } = Typography;

export default function NotificationCenter({ notifications = [], onRead, onClear }) {
  const [open, setOpen] = useState(false);
  const unreadCount = notifications.filter(n => !n.read).length;

  const handleRead = useCallback((id) => {
    onRead?.(id);
  }, [onRead]);

  const renderNotificationBody = useCallback((item) => {
    const content = (
      <>
        <List.Item.Meta
          avatar={item.icon}
          title={<Text strong={!item.read} style={{ fontSize: 13 }}>{item.title}</Text>}
          description={(
            <div style={{ display: 'grid', gap: 4 }}>
              {item.description ? <Text type="secondary" style={{ fontSize: 12 }}>{item.description}</Text> : null}
              {item.time ? <Text type="secondary" style={{ fontSize: 12 }}>{item.time}</Text> : null}
            </div>
          )}
        />
        {!item.read && (
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--beacon-tone-blue-icon-color, #2563eb)', flexShrink: 0, marginTop: 6 }} />
        )}
      </>
    );

    const sharedStyle = {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
      width: '100%',
      padding: '10px 12px',
      opacity: item.read ? 0.6 : 1,
      color: 'inherit',
      textAlign: 'left',
      background: 'transparent',
      border: 0,
      cursor: 'pointer',
    };

    if (item.href) {
      return (
        <a href={item.href} onClick={() => handleRead(item.id)} style={{ ...sharedStyle, textDecoration: 'none' }}>
          {content}
        </a>
      );
    }

    return (
      <button type="button" onClick={() => handleRead(item.id)} style={sharedStyle}>
        {content}
      </button>
    );
  }, [handleRead]);

  const content = notifications.length === 0 ? (
    <div style={{ width: 320, padding: '24px 0' }}>
      <EmptyState variant="card" title="暂无通知" description="所有通知已处理" />
    </div>
  ) : (
    <div style={{ width: 320, maxHeight: 400, overflow: 'auto' }}>
      <List
        size="small"
        dataSource={notifications.slice(0, 20)}
        renderItem={(item) => (
          <List.Item style={{ padding: 0 }}>
            {renderNotificationBody(item)}
          </List.Item>
        )}
      />
      {onClear && (
        <div style={{ textAlign: 'center', padding: '8px 0', borderTop: '1px solid var(--beacon-border-muted)' }}>
          <Button type="link" size="small" onClick={onClear}>全部已读</Button>
        </div>
      )}
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
      overlayClassName="beacon-notification-popover"
    >
      <Badge count={unreadCount} size="small" offset={[-2, 2]}>
        <Button
          type="text"
          icon={<BellOutlined />}
          style={{ fontSize: 18 }}
          className="beacon-icon-button beacon-notification-center__trigger"
          aria-label="通知中心"
        />
      </Badge>
    </Popover>
  );
}

NotificationCenter.propTypes = {
  notifications: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
    read: PropTypes.bool,
    icon: PropTypes.node,
    title: PropTypes.node.isRequired,
    description: PropTypes.node,
    time: PropTypes.node,
    href: PropTypes.string,
  })),
  onRead: PropTypes.func,
  onClear: PropTypes.func,
};

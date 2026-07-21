import React from 'react';
import PropTypes from 'prop-types';
import { Table } from 'antd';
import EmptyState from '../EmptyState';

export default function ProTable({
  columns,
  dataSource,
  loading,
  rowKey = 'id',
  pagination,
  onChange,
  rowSelection,
  scroll,
  size = 'small',
  sticky = true,
  bordered = false,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  emptyAction,
  ...rest
}) {
  const stickyEnabled = import.meta.env.TEST ? false : sticky;

  const enhancedColumns = columns.map(col => ({
    ...col,
    ellipsis: col.ellipsis === false ? false : { showTitle: true },
  }));

  const defaultPagination = pagination === false ? false : {
    showSizeChanger: true,
    showQuickJumper: true,
    showTotal: (total) => `\u5171 ${total} \u6761`,
    pageSizeOptions: ['10', '20', '50', '100'],
    size: 'small',
    ...pagination,
  };

  return (
    <Table
      className="beacon-pro-table"
      columns={enhancedColumns}
      dataSource={dataSource}
      loading={loading}
      rowKey={rowKey}
      pagination={defaultPagination}
      onChange={onChange}
      rowSelection={rowSelection}
      scroll={scroll || { x: 'max-content' }}
      size={size}
      sticky={stickyEnabled}
      bordered={bordered}
      locale={{
        emptyText: (
          <EmptyState
            variant="card"
            icon={emptyIcon}
            title={emptyTitle}
            description={emptyDescription}
            action={emptyAction}
          />
        ),
      }}
      {...rest}
    />
  );
}

const tableColumnShape = PropTypes.shape({
  ellipsis: PropTypes.oneOfType([PropTypes.bool, PropTypes.object]),
});

ProTable.propTypes = {
  columns: PropTypes.arrayOf(tableColumnShape).isRequired,
  dataSource: PropTypes.array,
  loading: PropTypes.oneOfType([PropTypes.bool, PropTypes.object]),
  rowKey: PropTypes.oneOfType([PropTypes.string, PropTypes.func]),
  pagination: PropTypes.oneOfType([PropTypes.bool, PropTypes.object]),
  onChange: PropTypes.func,
  rowSelection: PropTypes.object,
  scroll: PropTypes.object,
  size: PropTypes.string,
  sticky: PropTypes.bool,
  bordered: PropTypes.bool,
  emptyIcon: PropTypes.node,
  emptyTitle: PropTypes.node,
  emptyDescription: PropTypes.node,
  emptyAction: PropTypes.node,
};

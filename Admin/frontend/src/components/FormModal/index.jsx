import React from 'react';
import PropTypes from 'prop-types';
import { Modal, Button, Space } from 'antd';

export default function FormModal({
  open,
  onClose,
  onSubmit,
  title,
  loading = false,
  submitText = '确认',
  cancelText = '取消',
  width = 520,
  children,
  ...rest
}) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={title}
      width={width}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onClose}>{cancelText}</Button>
          <Button type="primary" loading={loading} onClick={onSubmit}>
            {submitText}
          </Button>
        </Space>
      }
      {...rest}
    >
      {children}
    </Modal>
  );
}

FormModal.propTypes = {
  open: PropTypes.bool,
  onClose: PropTypes.func,
  onSubmit: PropTypes.func,
  title: PropTypes.node.isRequired,
  loading: PropTypes.bool,
  submitText: PropTypes.node,
  cancelText: PropTypes.node,
  width: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  children: PropTypes.node,
};

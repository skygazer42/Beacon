import React from 'react';
import { Result } from 'antd';
import { getBootstrapPath } from '../bootstrap';

export default function PlaceholderPage() {
  const path = getBootstrapPath();
  return (
    <Result
      status="info"
      title="页面建设中"
      subTitle={`当前路径：${path}，该页面即将上线。`}
    />
  );
}

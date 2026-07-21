import React from 'react';
import { render } from '@testing-library/react';
import { App as AntdApp, ConfigProvider } from 'antd';
import { afterAll, beforeAll, vi } from 'vitest';

export function installDigitalHumanPageTestEnv() {
  beforeAll(() => {
    window.matchMedia = window.matchMedia || (() => ({
      matches: false,
      media: '',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    vi.spyOn(window, 'getComputedStyle').mockImplementation(() => ({
      getPropertyValue: () => '',
      overflow: 'auto',
      overflowX: 'auto',
      overflowY: 'auto',
    }));
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });
}

export function renderDigitalHumanPage(node) {
  return render(
    <ConfigProvider>
      <AntdApp>{node}</AntdApp>
    </ConfigProvider>,
  );
}

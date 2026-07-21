import React from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntdApp, ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import useThemeStore from './stores/themeStore';
import { getThemeConfig } from './theme/tokens';
import './index.css';

function ThemedApp() {
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const themeConfig = getThemeConfig(resolvedTheme, theme.darkAlgorithm);

  return (
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      <AntdApp>
        <App />
      </AntdApp>
    </ConfigProvider>
  );
}

const rootEl = document.getElementById('beacon-app-root');
if (rootEl) {
  const root = createRoot(rootEl);
  root.render(<ThemedApp />);
}

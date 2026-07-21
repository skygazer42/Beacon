import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import {
  AlgorithmFormRoutePage,
  DigitalHumanAlertCenterRoutePage,
  DigitalHumanDashboardRoutePage,
  DigitalHumanDeviceMonitorRoutePage,
  DigitalHumanMonitorLogsRoutePage,
  DigitalHumanOpsReportRoutePage,
  DigitalHumanSystemSettingsRoutePage,
  LoginRoutePage,
  ProfileRoutePage,
  ROUTE_MAP,
  default as App,
} from './App';
import { getBootstrapPath, getBootstrapQueryString, resetBootstrapCache } from './bootstrap';

vi.mock('./layouts/AppLayout', () => ({
  default: ({ children }) => <div data-testid="app-layout">{children}</div>,
}));

vi.mock('./pages/auth/LoginPage', () => ({
  default: () => <div>standalone login page</div>,
}));

afterEach(() => {
  document.body.innerHTML = '';
  window.history.replaceState({}, '', '/');
  resetBootstrapCache();
});

describe('ROUTE_MAP', () => {
  it('routes profile to the dedicated lazy route component', () => {
    expect(ROUTE_MAP['/profile']).toBe(ProfileRoutePage);
  });

  it('routes login to the standalone login route component', () => {
    expect(ROUTE_MAP['/login']).toBe(LoginRoutePage);
  });

  it('routes algorithm add and edit to the same lazy form route', () => {
    expect(ROUTE_MAP['/algorithm/add']).toBe(AlgorithmFormRoutePage);
    expect(ROUTE_MAP['/algorithm/edit']).toBe(AlgorithmFormRoutePage);
  });

  it('routes digital human monitoring pages to dedicated lazy routes', () => {
    expect(ROUTE_MAP['/digital-human/dashboard']).toBe(DigitalHumanDashboardRoutePage);
    expect(ROUTE_MAP['/digital-human/device-monitor']).toBe(DigitalHumanDeviceMonitorRoutePage);
    expect(ROUTE_MAP['/digital-human/alert-center']).toBe(DigitalHumanAlertCenterRoutePage);
    expect(ROUTE_MAP['/digital-human/monitor-logs']).toBe(DigitalHumanMonitorLogsRoutePage);
    expect(ROUTE_MAP['/digital-human/ops-report']).toBe(DigitalHumanOpsReportRoutePage);
    expect(ROUTE_MAP['/digital-human/system-settings']).toBe(DigitalHumanSystemSettingsRoutePage);
  });
});

describe('app bootstrap', () => {
  it('renders login without the app shell layout chrome', async () => {
    window.history.replaceState({}, '', '/login');
    resetBootstrapCache();

    render(<App />);

    expect(await screen.findByText('standalone login page')).toBeInTheDocument();
    expect(screen.queryByTestId('app-layout')).toBeNull();
  });

  it('falls back to the browser pathname and search without a bootstrap payload', () => {
    window.history.replaceState({}, '', '/login?tenant=demo');
    resetBootstrapCache();

    expect(getBootstrapPath()).toBe('/login');
    expect(getBootstrapQueryString()).toBe('tenant=demo');
  });
});

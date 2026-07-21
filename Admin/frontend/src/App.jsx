import React, { Suspense, lazy } from 'react';
import { getBootstrapPath } from './bootstrap';
import PlaceholderPage from './pages/PlaceholderPage';
import SkeletonPage from './components/Skeleton';
import PageTransition from './components/PageTransition/index';

function lazyPage(loader) {
  return lazy(loader);
}

function RouteLoadingState() {
  return <SkeletonPage kpiCount={4} />;
}

export const DashboardRoutePage = lazyPage(() => import('./pages/dashboard/DashboardPage'));
export const AppLayoutShell = lazyPage(() => import('./layouts/AppLayout'));
export const AlarmsRoutePage = lazyPage(() => import('./pages/alarms/AlarmsPage'));
export const AlarmDetailRoutePage = lazyPage(() => import('./pages/alarms/AlarmDetailPage'));
export const StreamsRoutePage = lazyPage(() => import('./pages/streams/StreamsPage'));
export const StreamAddEditRoutePage = lazyPage(() => import('./pages/streams/StreamAddEditPage'));
export const StreamPlayerRoutePage = lazyPage(() => import('./pages/streams/StreamPlayerPage'));
export const ControlsRoutePage = lazyPage(() => import('./pages/controls/ControlsPage'));
export const ControlEditorRoutePage = lazyPage(() => import('./pages/controls/ControlEditorPage'));
export const ControlLogsRoutePage = lazyPage(() => import('./pages/controls/ControlLogsPage'));
export const AlarmSoundsRoutePage = lazyPage(() => import('./pages/alarms/AlarmSoundsPage'));
export const AlgorithmsRoutePage = lazyPage(() => import('./pages/algorithms/AlgorithmsPage'));
export const AlgorithmFormRoutePage = lazyPage(() => import('./pages/algorithms/AlgorithmFormPage'));
export const AlgorithmVersionsRoutePage = lazyPage(() => import('./pages/algorithms/AlgorithmVersionsPage'));
export const CloudEdgeClustersRoutePage = lazyPage(() => import('./pages/cloud/CloudEdgeClustersPage'));
export const CloudAlarmsRoutePage = lazyPage(() => import('./pages/cloud/CloudAlarmsPage'));
export const CloudAlarmDetailRoutePage = lazyPage(() => import('./pages/cloud/CloudAlarmDetailPage'));
export const CloudRemoteStreamsRoutePage = lazyPage(() => import('./pages/cloud/CloudRemoteStreamsPage'));
export const CloudRemoteStreamDetailRoutePage = lazyPage(() => import('./pages/cloud/CloudRemoteStreamDetailPage'));
export const CloudRemoteRecordingsRoutePage = lazyPage(() => import('./pages/cloud/CloudRemoteRecordingsPage'));
export const CloudRemotePlatformRoutePage = lazyPage(() => import('./pages/cloud/CloudRemotePlatformPage'));
export const CloudIamRoutePage = lazyPage(() => import('./pages/cloud/CloudIamPage'));
export const DigitalHumanDashboardRoutePage = lazyPage(() => import('./pages/digitalHuman/DigitalHumanDashboardPage'));
export const DigitalHumanDeviceMonitorRoutePage = lazyPage(() => import('./pages/digitalHuman/DigitalHumanDeviceMonitorPage'));
export const DigitalHumanAlertCenterRoutePage = lazyPage(() => import('./pages/digitalHuman/DigitalHumanAlertCenterPage'));
export const DigitalHumanMonitorLogsRoutePage = lazyPage(() => import('./pages/digitalHuman/DigitalHumanMonitorLogsPage'));
export const DigitalHumanOpsReportRoutePage = lazyPage(() => import('./pages/digitalHuman/DigitalHumanOpsReportPage'));
export const DigitalHumanSystemSettingsRoutePage = lazyPage(() => import('./pages/digitalHuman/DigitalHumanSystemSettingsPage'));
export const DiagnosticsRoutePage = lazyPage(() => import('./pages/ops/DiagnosticsPage'));
export const PlatformRoutePage = lazyPage(() => import('./pages/ops/PlatformPage'));
export const UpgradeRoutePage = lazyPage(() => import('./pages/ops/UpgradePage'));
export const UsersRoutePage = lazyPage(() => import('./pages/system/UsersPage'));
export const AuditRoutePage = lazyPage(() => import('./pages/system/AuditPage'));
export const ApiKeysRoutePage = lazyPage(() => import('./pages/system/ApiKeysPage'));
export const LicenseRoutePage = lazyPage(() => import('./pages/system/LicensePage'));
export const ConfigRoutePage = lazyPage(() => import('./pages/system/ConfigPage'));
export const OnvifRoutePage = lazyPage(() => import('./pages/system/OnvifPage'));
export const ProfileRoutePage = lazyPage(() => import('./pages/system/ProfilePage'));
export const RecordingRoutePage = lazyPage(() => import('./pages/recording/RecordingPage'));
export const ScreenRoutePage = lazyPage(() => import('./pages/screen/ScreenPage'));
export const FacesRoutePage = lazyPage(() => import('./pages/faces/FacesPage'));
export const DeveloperRoutePage = lazyPage(() => import('./pages/developer/DeveloperPage'));
export const LoginRoutePage = lazyPage(() => import('./pages/auth/LoginPage'));

const STANDALONE_ROUTES = new Set(['/login']);

export const ROUTE_MAP = {
  '/': DashboardRoutePage,
  '/login': LoginRoutePage,
  '/alarms': AlarmsRoutePage,
  '/alarm/detail': AlarmDetailRoutePage,
  '/alarm/review': AlarmsRoutePage,
  '/stream/index': StreamsRoutePage,
  '/stream/add': StreamAddEditRoutePage,
  '/stream/edit': StreamAddEditRoutePage,
  '/stream/player': StreamPlayerRoutePage,
  '/stream/multi': StreamPlayerRoutePage,
  '/controls': ControlsRoutePage,
  '/control/add': ControlEditorRoutePage,
  '/control/edit': ControlEditorRoutePage,
  '/control/logs': ControlLogsRoutePage,
  '/algorithm/index': AlgorithmsRoutePage,
  '/algorithm/add': AlgorithmFormRoutePage,
  '/algorithm/edit': AlgorithmFormRoutePage,
  '/algorithm/versions': AlgorithmVersionsRoutePage,
  '/alarm_sound/index': AlarmSoundsRoutePage,
  '/face/index': FacesRoutePage,
  '/screen/index': ScreenRoutePage,
  '/recording/manager': RecordingRoutePage,
  '/ops/diagnostics': DiagnosticsRoutePage,
  '/ops/platform': PlatformRoutePage,
  '/ops/upgrade': UpgradeRoutePage,
  '/ops/audit': AuditRoutePage,
  '/ops/apikeys': ApiKeysRoutePage,
  '/profile': ProfileRoutePage,
  '/user/manage': UsersRoutePage,
  '/developer/index': DeveloperRoutePage,
  '/config/export': ConfigRoutePage,
  '/config/import': ConfigRoutePage,
  '/config/history': ConfigRoutePage,
  '/config/system': ConfigRoutePage,
  '/license/manager': LicenseRoutePage,
  '/onvif/discover': OnvifRoutePage,
  '/cloud/edge-clusters': CloudEdgeClustersRoutePage,
  '/cloud/alarms': CloudAlarmsRoutePage,
  '/cloud/alarm/detail': CloudAlarmDetailRoutePage,
  '/cloud/remote/streams': CloudRemoteStreamsRoutePage,
  '/cloud/remote/stream/detail': CloudRemoteStreamDetailRoutePage,
  '/cloud/remote/recordings': CloudRemoteRecordingsRoutePage,
  '/cloud/remote/platform': CloudRemotePlatformRoutePage,
  '/cloud/iam': CloudIamRoutePage,
  '/digital-human/dashboard': DigitalHumanDashboardRoutePage,
  '/digital-human/device-monitor': DigitalHumanDeviceMonitorRoutePage,
  '/digital-human/alert-center': DigitalHumanAlertCenterRoutePage,
  '/digital-human/monitor-logs': DigitalHumanMonitorLogsRoutePage,
  '/digital-human/ops-report': DigitalHumanOpsReportRoutePage,
  '/digital-human/system-settings': DigitalHumanSystemSettingsRoutePage,
};

export default function App() {
  const path = getBootstrapPath();
  const PageComponent = ROUTE_MAP[path] || PlaceholderPage;

  if (STANDALONE_ROUTES.has(path)) {
    return (
      <Suspense fallback={<RouteLoadingState />}>
        <PageComponent />
      </Suspense>
    );
  }

  return (
    <Suspense fallback={<RouteLoadingState />}>
      <AppLayoutShell currentPath={path}>
        <Suspense fallback={<RouteLoadingState />}>
          <PageTransition>
            <PageComponent />
          </PageTransition>
        </Suspense>
      </AppLayoutShell>
    </Suspense>
  );
}

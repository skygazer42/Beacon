import React, { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { Avatar, Drawer, Dropdown, Layout, Tooltip } from 'antd';
import {
  AlertOutlined,
  ApiOutlined,
  AppstoreOutlined,
  BellOutlined,
  BuildOutlined,
  CloudOutlined,
  CodeOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  DesktopOutlined,
  DownOutlined,
  ExperimentOutlined,
  EyeOutlined,
  FileTextOutlined,
  HomeOutlined,
  LaptopOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  SettingOutlined,
  SunOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  getBootstrapUser,
  getSiteBranding,
  isBootstrapPopupMode,
} from '../bootstrap';
import { API } from '../api/endpoints';
import NotificationCenter from '../components/NotificationCenter';
import useApi from '../hooks/useApi';
import useMediaQuery from '../hooks/useMediaQuery';
import useThemeStore from '../stores/themeStore';
import './AppLayout.css';

const { Header, Sider, Content } = Layout;

const PRIMARY_ITEMS = [
  { key: 'overview', label: '系统总览', href: '/', match: ['/'], icon: <HomeOutlined /> },
  { key: 'device-monitor', label: '视频资源', href: '/stream/index', match: ['/stream/index'], icon: <DesktopOutlined /> },
  { key: 'big-screen', label: '大屏监控', href: '/screen/index', match: ['/screen'], icon: <DesktopOutlined /> },
  { key: 'alarm-center', label: '告警中心', href: '/alarms', match: ['/alarms', '/alarm'], icon: <AlertOutlined /> },
  { key: 'inference-task', label: '布控中心', href: '/controls', match: ['/controls', '/control/add', '/control/edit', '/control/logs'], icon: <DeploymentUnitOutlined /> },
];

const NAV_SECTIONS = [
  {
    key: 'video-analysis',
    title: '视频与算法',
    items: [
      { key: 'recording-manage', label: '录像管理', href: '/recording/manager', match: ['/recording'], icon: <AppstoreOutlined /> },
      { key: 'model-manage', label: '算法管理', href: '/algorithm/index', match: ['/algorithm'], icon: <ExperimentOutlined /> },
      { key: 'face-manage', label: '人脸库管理', href: '/face/index', match: ['/face'], icon: <EyeOutlined /> },
    ],
  },
  {
    key: 'cloud',
    title: '云中心',
    items: [
      { key: 'cloud-platform', label: '云边连接', href: '/cloud/edge-clusters', match: ['/cloud/edge-clusters', '/cloud/remote'], icon: <CloudOutlined /> },
      { key: 'cloud-alarms', label: '云端告警', href: '/cloud/alarms', match: ['/cloud/alarms', '/cloud/alarm'], icon: <AlertOutlined /> },
      { key: 'cloud-iam', label: '云端权限', href: '/cloud/iam', match: ['/cloud/iam'], icon: <CloudOutlined /> },
      { key: 'digital-human', label: '数字人监管', href: '/digital-human/dashboard', match: ['/digital-human'], icon: <AppstoreOutlined />, staffOnly: true },
    ],
  },
  {
    key: 'ops',
    title: '平台运维',
    items: [
      { key: 'resource-monitor', label: '平台概览', href: '/ops/platform', match: ['/ops/platform'], icon: <DatabaseOutlined /> },
      { key: 'ops-toolbox', label: '诊断中心', href: '/ops/diagnostics', match: ['/ops/diagnostics'], icon: <ToolOutlined /> },
      { key: 'log-center', label: '日志中心', href: '/ops/audit', match: ['/ops/audit'], icon: <FileTextOutlined /> },
      { key: 'image-manage', label: '升级中心', href: '/ops/upgrade', match: ['/ops/upgrade'], icon: <BuildOutlined /> },
      { key: 'device-scan', label: '设备扫描', href: '/onvif/discover', match: ['/onvif'], icon: <SettingOutlined /> },
    ],
  },
  {
    key: 'system',
    title: '系统管理',
    items: [
      { key: 'system-settings', label: '系统设置', href: '/config/system', match: ['/config'], icon: <SettingOutlined /> },
      { key: 'user-manage', label: '账号权限', href: '/user/manage', match: ['/user/manage'], icon: <UserOutlined /> },
      { key: 'license-manage', label: '授权管理', href: '/license/manager', match: ['/license'], icon: <SettingOutlined /> },
      { key: 'api-keys', label: 'API 安全', href: '/ops/apikeys', match: ['/ops/apikeys'], icon: <ApiOutlined /> },
      { key: 'developer-entry', label: '开发入口', href: '/developer/index', match: ['/developer'], icon: <CodeOutlined /> },
      { key: 'alarm-sounds', label: '告警声管理', href: '/alarm_sound/index', match: ['/alarm_sound'], icon: <AlertOutlined /> },
    ],
  },
];

const THEME_ICONS = {
  dark: <MoonOutlined />,
  light: <SunOutlined />,
  system: <LaptopOutlined />,
};

const THEME_LABELS = {
  dark: '深色模式',
  light: '浅色模式',
  system: '跟随系统',
};

const READ_NOTIFICATIONS_STORAGE_KEY = '__BEACON_READ_NOTIFICATION_IDS__';

function normalizeNotificationId(id) {
  return String(id ?? '').trim();
}

function getSessionStorage() {
  try {
    return globalThis.sessionStorage || null;
  } catch {
    return null;
  }
}

function loadReadNotificationIds() {
  const storage = getSessionStorage();
  if (!storage) {
    return new Set();
  }
  try {
    const raw = storage.getItem(READ_NOTIFICATIONS_STORAGE_KEY);
    if (!raw) {
      return new Set();
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return new Set();
    }
    return new Set(parsed.map((id) => normalizeNotificationId(id)).filter(Boolean));
  } catch {
    return new Set();
  }
}

function persistReadNotificationIds(ids) {
  const storage = getSessionStorage();
  if (!storage) {
    return;
  }
  try {
    const values = [...(ids || [])].map((id) => normalizeNotificationId(id)).filter(Boolean);
    if (values.length === 0) {
      storage.removeItem(READ_NOTIFICATIONS_STORAGE_KEY);
      return;
    }
    storage.setItem(READ_NOTIFICATIONS_STORAGE_KEY, JSON.stringify(values));
  } catch {
    // ignore storage failures and keep in-memory read state
  }
}

function matchesPath(currentPath, item) {
  if (!item) return false;
  if (item.href === '/' && currentPath === '/') return true;
  return (item.match || []).some((prefix) => {
    if (prefix === '/') return currentPath === '/';
    return currentPath === prefix || currentPath.startsWith(`${prefix}/`);
  });
}

function resolveSelectedSectionKey(currentPath, sections = NAV_SECTIONS) {
  for (const section of sections) {
    if (section.items.some((item) => matchesPath(currentPath, item))) {
      return section.key;
    }
  }
  return null;
}

function buildUserInitial(user) {
  const name = user?.username || 'A';
  return name.slice(0, 1).toUpperCase();
}

function canAccessNavItem(item, user) {
  return !item?.staffOnly || Boolean(user?.isStaff || user?.isSuperuser);
}

function resolveSelectedNavKey(currentPath, sections = NAV_SECTIONS) {
  const primaryItem = PRIMARY_ITEMS.find((item) => matchesPath(currentPath, item));
  if (primaryItem) return primaryItem.key;

  for (const section of sections) {
    const matchedItem = section.items.find((item) => matchesPath(currentPath, item));
    if (matchedItem) return matchedItem.key;
  }

  return null;
}

function resolveNotificationIcon(item) {
  switch (item?.kind) {
    case 'alarm_unread':
      return <AlertOutlined />;
    case 'platform_analyzer':
      return <ApiOutlined />;
    case 'platform_resource':
      return <DatabaseOutlined />;
    case 'license_error':
      return <SettingOutlined />;
    default:
      return item?.level === 'critical' ? <AlertOutlined /> : <BellOutlined />;
  }
}

export default function AppLayout({ currentPath, children }) {
  const user = getBootstrapUser();
  const navClusters = useMemo(() => {
    return NAV_SECTIONS
      .map((section) => ({
        ...section,
        items: section.items.filter((item) => canAccessNavItem(item, user)),
      }))
      .filter((section) => section.items.length > 0);
  }, [user]);
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [openSectionKey, setOpenSectionKey] = useState(() => resolveSelectedSectionKey(currentPath, navClusters));
  const [readNotificationIds, setReadNotificationIds] = useState(loadReadNotificationIds);
  const isMobile = useMediaQuery('(max-width: 900px)');
  const { data: notificationsData, run: refreshNotifications } = useApi(
    API.notifications,
    undefined,
    { defaultData: { items: [] } },
  );

  const branding = getSiteBranding();
  const appVersion = `Beacon ${branding.version}`;
  const popupMode = isBootstrapPopupMode();
  const themeMode = useThemeStore((state) => state.mode);
  const toggleTheme = useThemeStore((state) => state.toggle);

  const handleNavigate = useCallback((href) => {
    if (href) globalThis.location.href = href;
    if (isMobile) setDrawerOpen(false);
  }, [isMobile]);

  useEffect(() => {
    const timer = globalThis.setInterval(() => {
      refreshNotifications();
    }, 30000);
    return () => globalThis.clearInterval(timer);
  }, [refreshNotifications]);

  useEffect(() => {
    const currentIds = new Set(
      (notificationsData?.items || [])
        .map((item) => normalizeNotificationId(item?.id))
        .filter(Boolean),
    );
    setReadNotificationIds((prev) => {
      const next = new Set([...prev].filter((id) => currentIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [notificationsData]);

  useEffect(() => {
    persistReadNotificationIds(readNotificationIds);
  }, [readNotificationIds]);

  const selectedSectionKey = useMemo(
    () => resolveSelectedSectionKey(currentPath, navClusters),
    [currentPath, navClusters],
  );

  useEffect(() => {
    setOpenSectionKey(selectedSectionKey);
  }, [selectedSectionKey]);

  const toggleSection = useCallback((sectionKey) => {
    setOpenSectionKey((current) => current === sectionKey ? null : sectionKey);
  }, []);

  const markNotificationRead = useCallback((id) => {
    const normalizedId = normalizeNotificationId(id);
    if (!normalizedId) {
      return;
    }
    setReadNotificationIds((prev) => {
      if (prev.has(normalizedId)) {
        return prev;
      }
      const next = new Set(prev);
      next.add(normalizedId);
      return next;
    });
  }, []);

  const clearNotifications = useCallback(() => {
    setReadNotificationIds((prev) => {
      const next = new Set(prev);
      (notificationsData?.items || []).forEach((item) => {
        const normalizedId = normalizeNotificationId(item?.id);
        if (normalizedId) next.add(normalizedId);
      });
      return next;
    });
  }, [notificationsData]);

  const userMenuItems = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人信息',
      onClick: () => { globalThis.location.href = '/profile'; },
    },
    { type: 'divider' },
    {
      key: 'developer',
      icon: <CodeOutlined />,
      label: '开发入口',
      onClick: () => { globalThis.location.href = '/developer/index'; },
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: () => { globalThis.location.href = '/logout'; },
    },
  ];

  const selectedNavKey = useMemo(
    () => resolveSelectedNavKey(currentPath, navClusters),
    [currentPath, navClusters],
  );
  const notifications = useMemo(
    () => (notificationsData?.items || []).map((item) => ({
      ...item,
      read: readNotificationIds.has(normalizeNotificationId(item.id)),
      icon: resolveNotificationIcon(item),
    })),
    [notificationsData, readNotificationIds],
  );

  if (popupMode) {
    return <div className="beacon-popup-container">{children}</div>;
  }

  function renderNavItem(item, compact = false) {
    const selected = item.key === selectedNavKey;
    const itemLabel = compact ? null : <span className="beacon-shell-nav__item-label">{item.label}</span>;
    const node = (
      <button
        key={item.key}
        type="button"
        className={`beacon-shell-nav__item${selected ? ' beacon-shell-nav__item--selected' : ''}${compact ? ' beacon-shell-nav__item--compact' : ''}`}
        onClick={() => handleNavigate(item.href)}
        aria-current={selected ? 'page' : undefined}
        title={item.label}
      >
        <span className="beacon-shell-nav__item-icon">{item.icon}</span>
        {itemLabel}
      </button>
    );

    if (compact) {
      return (
        <Tooltip key={item.key} placement="right" title={item.label}>
          {node}
        </Tooltip>
      );
    }
    return node;
  }

  function renderSidebarNav(compact = false) {
    const compactCurrentItem = compact
      ? navClusters.flatMap((section) => section.items).find((item) => item.key === selectedNavKey)
      : null;

    return (
      <nav className={`beacon-shell-nav${compact ? ' beacon-shell-nav--compact' : ''}`} aria-label="主导航">
        <div className="beacon-shell-nav__primary">
          {PRIMARY_ITEMS.map((item) => renderNavItem(item, compact))}
        </div>

        {compactCurrentItem ? (
          <div className="beacon-shell-nav__items">
            {renderNavItem(compactCurrentItem, true)}
          </div>
        ) : null}

        {compact ? null : navClusters.map((section) => {
          if (section.items.length === 1) {
            return (
              <section className="beacon-shell-nav__cluster" key={section.key}>
                {renderNavItem(section.items[0])}
              </section>
            );
          }

          const isOpen = openSectionKey === section.key;

          return (
            <section className="beacon-shell-nav__cluster" key={section.key}>
              <button
                type="button"
                className="beacon-shell-nav__section-toggle"
                onClick={() => toggleSection(section.key)}
                aria-expanded={isOpen}
              >
                <span className="beacon-shell-nav__section-text">{section.title}</span>
                <DownOutlined className={`beacon-shell-nav__section-icon${isOpen ? ' beacon-shell-nav__section-icon--open' : ''}`} />
              </button>

              {isOpen ? (
                <div className="beacon-shell-nav__items">
                  {section.items.map((item) => renderNavItem(item))}
                </div>
              ) : null}
            </section>
          );
        })}
      </nav>
    );
  }

  const desktopCompact = !isMobile && collapsed;
  const mainLayoutCls = [
    'beacon-main-layout',
    desktopCompact ? 'beacon-main-layout--collapsed' : '',
  ].filter(Boolean).join(' ');

  const brandArea = (
    <div className={`beacon-sider-brand${desktopCompact ? ' beacon-sider-brand--collapsed' : ''}`}>
      <img src={branding.logo} alt={branding.name} className="beacon-sider-brand-logo" />
      {desktopCompact ? null : <span className="beacon-sider-brand-title">{branding.title}</span>}
    </div>
  );

  const sidebarBody = (
    <div className="beacon-shell-sidebar">
      {brandArea}
      <div className="beacon-sider-scroll">{renderSidebarNav(desktopCompact)}</div>
      <div className={`beacon-sider-footer${desktopCompact ? ' beacon-sider-footer--compact' : ''}`}>
        <span className="beacon-sider-footer__version">{desktopCompact ? branding.version : appVersion}</span>
      </div>
    </div>
  );

  return (
    <Layout className="beacon-layout">
      {isMobile ? null : (
        <Sider
          trigger={null}
          collapsible
          collapsed={collapsed}
          width={236}
          collapsedWidth={64}
          className="beacon-sider beacon-sider-desktop"
        >
          {sidebarBody}
        </Sider>
      )}

      {isMobile ? (
        <Drawer
          placement="left"
          width={260}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          className="beacon-mobile-drawer"
          styles={{ body: { padding: 0 } }}
        >
          <div className="beacon-shell-sidebar beacon-shell-sidebar--mobile">
            <div className="beacon-sider-brand">
              <img src={branding.logo} alt={branding.name} className="beacon-sider-brand-logo" />
              <span className="beacon-sider-brand-title">{branding.title}</span>
            </div>
            <div className="beacon-sider-scroll">{renderSidebarNav(false)}</div>
            <div className="beacon-sider-footer">
              <span className="beacon-sider-footer__version">{appVersion}</span>
            </div>
          </div>
        </Drawer>
      ) : null}

      <Layout className={mainLayoutCls}>
        <Header className="beacon-header">
          <div className="beacon-header-left">
            {isMobile ? (
              <button
                type="button"
                className="beacon-hamburger-btn beacon-icon-button"
                onClick={() => setDrawerOpen(true)}
                aria-label="打开导航菜单"
              >
                <MenuOutlined />
              </button>
            ) : (
              <button
                type="button"
                className="beacon-collapse-btn beacon-icon-button"
                onClick={() => setCollapsed((prev) => !prev)}
                aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
              >
                {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              </button>
            )}
          </div>

          <div className="beacon-header-right">
            <NotificationCenter
              notifications={notifications}
              onRead={markNotificationRead}
              onClear={clearNotifications}
            />

            <button
              type="button"
              className="beacon-theme-btn beacon-icon-button"
              onClick={toggleTheme}
              aria-label={THEME_LABELS[themeMode]}
              title={THEME_LABELS[themeMode]}
            >
              {THEME_ICONS[themeMode]}
            </button>

            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
              <div className="beacon-user-trigger">
                <Avatar size="small" className="beacon-user-avatar">
                  {buildUserInitial(user)}
                </Avatar>
                <span className="beacon-user-name">{user.username || 'admin'}</span>
              </div>
            </Dropdown>
          </div>
        </Header>

        <Content className="beacon-content">
          <div className="beacon-page-container">{children}</div>
        </Content>
      </Layout>
    </Layout>
  );
}

AppLayout.propTypes = {
  currentPath: PropTypes.string,
  children: PropTypes.node,
};

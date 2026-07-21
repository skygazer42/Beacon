const FONT_FAMILY = "'Manrope', 'PingFang SC', 'Microsoft YaHei', sans-serif";

const sharedTokens = {
  fontFamily: FONT_FAMILY,
  fontSize: 14,
  fontSizeHeading1: 24,
  fontSizeHeading2: 20,
  fontSizeHeading3: 16,
  fontSizeHeading4: 14,
  fontSizeSM: 12,

  borderRadius: 8,
  borderRadiusSM: 6,
  borderRadiusLG: 12,

  padding: 16,
  paddingSM: 12,
  paddingXS: 8,
  paddingXXS: 4,

  margin: 16,
  marginSM: 12,
  marginXS: 8,
  marginXXS: 4,

  controlHeight: 34,
  controlHeightSM: 28,
};

export const lightTokens = {
  ...sharedTokens,
  colorPrimary: '#3964fe',
  colorSuccess: '#16a34a',
  colorWarning: '#d97706',
  colorError: '#dc2626',
  colorInfo: '#3964fe',

  colorBgLayout: '#f7f9fc',
  colorBgContainer: '#ffffff',
  colorBgElevated: '#ffffff',
  colorBorder: '#e5e7eb',
  colorBorderSecondary: '#eef1f5',

  colorText: '#1f2937',
  colorTextSecondary: '#6b7280',
  colorTextTertiary: '#9ca3af',
  colorTextDisabled: '#d1d5db',
};

export const darkTokens = {
  ...sharedTokens,
  colorPrimary: '#6b86ff',
  colorSuccess: '#22c55e',
  colorWarning: '#f59e0b',
  colorError: '#ef4444',
  colorInfo: '#6b86ff',

  colorBgLayout: '#0f1115',
  colorBgContainer: '#181b22',
  colorBgElevated: '#20242d',
  colorBorder: '#2a2f3a',
  colorBorderSecondary: '#222731',

  colorText: '#dce2ec',
  colorTextSecondary: '#98a2b2',
  colorTextTertiary: '#687386',
  colorTextDisabled: '#4f5968',
};

const lightComponents = {
  Table: {
    headerBg: '#f7f9fc',
    headerColor: '#374151',
    rowHoverBg: '#f9fafb',
    cellPaddingBlock: 8,
    cellPaddingInline: 12,
  },
  Layout: {
    siderBg: '#0b0d12',
    headerBg: '#ffffff',
    bodyBg: '#f7f9fc',
  },
  Menu: {
    darkItemBg: '#0b0d12',
    darkItemColor: '#ffffffa6',
    darkItemHoverBg: '#ffffff14',
    darkItemSelectedBg: '#3964fe',
    darkItemSelectedColor: '#ffffff',
  },
  Card: {
    paddingLG: 16,
  },
  Tag: {
    defaultBg: '#f4f7fb',
  },
  Button: {
    borderRadius: 8,
  },
  Input: {
    borderRadius: 8,
  },
  Select: {
    borderRadius: 8,
  },
};

const darkComponents = {
  Table: {
    headerBg: '#1c2130',
    headerColor: '#cbd5e1',
    rowHoverBg: '#1c2130',
    cellPaddingBlock: 8,
    cellPaddingInline: 12,
  },
  Layout: {
    siderBg: '#0b0d12',
    headerBg: '#14171d',
    bodyBg: '#0f1115',
  },
  Menu: {
    darkItemBg: '#0b0d12',
    darkItemColor: '#ffffffa6',
    darkItemHoverBg: '#ffffff14',
    darkItemSelectedBg: '#4d6bfe',
    darkItemSelectedColor: '#ffffff',
  },
  Card: {
    paddingLG: 16,
    colorBgContainer: '#181b22',
    colorBorderSecondary: '#2a2f3a',
  },
  Tag: {
    defaultBg: '#1c2130',
    defaultColor: '#d1d7e0',
  },
  Button: {
    borderRadius: 8,
  },
  Input: {
    borderRadius: 8,
    colorBgContainer: '#181b22',
  },
  Select: {
    borderRadius: 8,
    colorBgContainer: '#181b22',
  },
  Modal: {
    contentBg: '#181b22',
    headerBg: '#181b22',
  },
  Drawer: {
    colorBgElevated: '#181b22',
  },
  Popover: {
    colorBgElevated: '#20242d',
  },
  Dropdown: {
    colorBgElevated: '#20242d',
  },
};

export function getThemeConfig(resolvedTheme, darkAlgorithm) {
  const isDark = resolvedTheme === 'dark';
  return {
    token: isDark ? darkTokens : lightTokens,
    components: isDark ? darkComponents : lightComponents,
    algorithm: isDark ? darkAlgorithm : undefined,
  };
}

// Backward compat default export (light theme)
const beaconTheme = {
  token: lightTokens,
  components: lightComponents,
};

export default beaconTheme;

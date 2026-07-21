import { create } from 'zustand';

const STORAGE_KEY = 'beacon-theme';
const THEME_MODE_ORDER = ['light', 'dark', 'system'];
const VALID_MODES = new Set(THEME_MODE_ORDER);

function getSystemTheme() {
  if (globalThis.window === undefined) return 'dark';
  return globalThis.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function readStoredMode() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && VALID_MODES.has(stored)) return stored;
  } catch {}
  return 'light';
}

function resolveTheme(mode) {
  return mode === 'system' ? getSystemTheme() : mode;
}

function applyTheme(resolved) {
  document.documentElement.dataset.theme = resolved;
}

const initialMode = readStoredMode();
const initialResolved = resolveTheme(initialMode);
applyTheme(initialResolved);

const useThemeStore = create((set, get) => ({
  mode: initialMode,
  resolvedTheme: initialResolved,

  setMode: (mode) => {
    if (!VALID_MODES.has(mode)) return;
    const resolved = resolveTheme(mode);
    try { localStorage.setItem(STORAGE_KEY, mode); } catch {}
    applyTheme(resolved);
    set({ mode, resolvedTheme: resolved });
  },

  toggle: () => {
    const { mode } = get();
    const next = THEME_MODE_ORDER[(THEME_MODE_ORDER.indexOf(mode) + 1) % THEME_MODE_ORDER.length];
    get().setMode(next);
  },
}));

function subscribeSystemThemeChanges() {
  if (globalThis.window === undefined) return;

  const mql = globalThis.matchMedia('(prefers-color-scheme: dark)');
  mql.addEventListener('change', () => {
    const { mode } = useThemeStore.getState();
    if (mode === 'system') {
      const resolved = getSystemTheme();
      applyTheme(resolved);
      useThemeStore.setState({ resolvedTheme: resolved });
    }
  });
}

// Listen for system theme changes (affects 'system' mode)
subscribeSystemThemeChanges();

export default useThemeStore;

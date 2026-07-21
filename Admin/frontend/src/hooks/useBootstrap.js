import { useMemo } from 'react';
import { readBootstrap, getBootstrapPath, getBootstrapQuery, getBootstrapUser, getSiteBranding } from '../bootstrap';

export function useBootstrap() {
  return useMemo(() => readBootstrap(), []);
}

export function useCurrentPath() {
  return useMemo(() => getBootstrapPath(), []);
}

export function useQueryParams() {
  return useMemo(() => getBootstrapQuery(), []);
}

export function useUser() {
  return useMemo(() => getBootstrapUser(), []);
}

export function useBranding() {
  return useMemo(() => getSiteBranding(), []);
}

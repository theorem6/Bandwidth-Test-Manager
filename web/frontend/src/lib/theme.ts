/**
 * Theme mode: light, dark, or system (follow OS preference).
 * Persisted in localStorage; applied as data-theme="light" | "dark" on document.documentElement.
 */

import { writable } from 'svelte/store';

const STORAGE_KEY = 'netperf-theme';

export type ThemeMode = 'light' | 'dark' | 'system';

function getStored(): ThemeMode {
  if (typeof window === 'undefined') return 'system';
  const v = localStorage.getItem(STORAGE_KEY);
  if (v === 'light' || v === 'dark' || v === 'system') return v;
  return 'dark'; /* default to dark theme */
}

function getResolvedTheme(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'light') return 'light';
  if (mode === 'dark') return 'dark';
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
  return 'light';
}

function applyTheme(resolved: 'light' | 'dark') {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', resolved);
  }
}

export const themeMode = writable<ThemeMode>(getStored());
export const themeResolved = writable<'light' | 'dark'>(getResolvedTheme(getStored()));

let systemQuery: MediaQueryList | null = null;

function initSystemListener() {
  if (typeof window === 'undefined') return;
  systemQuery = window.matchMedia('(prefers-color-scheme: dark)');
  systemQuery.addEventListener('change', () => {
    themeMode.update((m) => {
      if (m === 'system') {
        const r = getResolvedTheme('system');
        themeResolved.set(r);
        applyTheme(r);
      }
      return m;
    });
  });
}

export function setTheme(mode: ThemeMode) {
  themeMode.set(mode);
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, mode);
  }
  const resolved = getResolvedTheme(mode);
  themeResolved.set(resolved);
  applyTheme(resolved);
}

/** Call once on app load to apply stored theme and listen for system changes. */
export function initTheme() {
  const mode = getStored();
  const resolved = getResolvedTheme(mode);
  themeResolved.set(resolved);
  applyTheme(resolved);
  initSystemListener();
}

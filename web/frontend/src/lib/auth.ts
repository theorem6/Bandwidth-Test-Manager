import { writable } from 'svelte/store';

const STORAGE_KEY = 'netperf_auth';

export interface AuthUser {
  username: string;
  role: 'admin' | 'readonly';
  token: string; // base64(username:password) for Authorization header
}

function loadStored(): AuthUser | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as AuthUser;
    if (data?.username && data?.role && data?.token) return data;
  } catch {
    // ignore
  }
  return null;
}

function persist(user: AuthUser | null) {
  if (typeof window === 'undefined') return;
  if (user) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  else sessionStorage.removeItem(STORAGE_KEY);
}

function createAuthStore() {
  const { subscribe, set } = writable<AuthUser | null>(loadStored());
  return {
    subscribe,
    setUser(user: AuthUser) {
      persist(user);
      set(user);
    },
    logout() {
      persist(null);
      set(null);
    },
  };
}

export const auth = createAuthStore();

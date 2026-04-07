/**
 * Server-driven branding (colors, logo, CSS) from GET /api/branding.
 */
import { writable } from 'svelte/store';
import { getBase } from './api';
import type { Branding } from './api';

export const branding = writable<Branding | null>(null);

const BUILTIN = {
  logo: '/static/hyperion-logo.svg',
  title: 'Bandwidth Test Manager',
  tagline: 'hyperionsolutionsgroup.com',
};

const CUSTOM_STYLE_ID = 'netperf-brand-custom-css';

export function builtinDefaults() {
  return { ...BUILTIN };
}

/** Fetch branding (no auth). */
export async function fetchBranding(): Promise<Branding> {
  const base = getBase();
  const r = await fetch(`${base}/api/branding`, { cache: 'no-store' });
  const body = (await r.json().catch(() => ({}))) as Branding;
  if (!r.ok) {
    return {
      app_title: '',
      tagline: '',
      logo_url: '',
      logo_alt: '',
      primary_color: '',
      primary_hover_color: '',
      navbar_gradient_start: '',
      navbar_gradient_end: '',
      navbar_bg_start: '',
      navbar_bg_end: '',
      custom_css: '',
    };
  }
  return body;
}

function hexToRgbTuple(hex: string): [number, number, number] | null {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  const n = parseInt(full, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Apply CSS variables and optional custom stylesheet. Call after initTheme(). */
export function applyBrandingToDocument(b: Branding) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;

  const clearKeys = [
    '--color-primary',
    '--color-primary-hover',
    '--brand-gradient-start',
    '--brand-gradient-end',
    '--navbar-bg-start',
    '--navbar-bg-end',
    '--bs-primary-rgb',
  ];
  for (const k of clearKeys) {
    root.style.removeProperty(k);
  }

  if (b.primary_color) {
    root.style.setProperty('--color-primary', b.primary_color);
    const rgb = hexToRgbTuple(b.primary_color);
    if (rgb) {
      root.style.setProperty('--bs-primary-rgb', `${rgb[0]}, ${rgb[1]}, ${rgb[2]}`);
    }
  }
  if (b.primary_hover_color) {
    root.style.setProperty('--color-primary-hover', b.primary_hover_color);
  }
  if (b.navbar_gradient_start) {
    root.style.setProperty('--brand-gradient-start', b.navbar_gradient_start);
  }
  if (b.navbar_gradient_end) {
    root.style.setProperty('--brand-gradient-end', b.navbar_gradient_end);
  }
  if (b.navbar_bg_start) {
    root.style.setProperty('--navbar-bg-start', b.navbar_bg_start);
  }
  if (b.navbar_bg_end) {
    root.style.setProperty('--navbar-bg-end', b.navbar_bg_end);
  }

  let el = document.getElementById(CUSTOM_STYLE_ID) as HTMLStyleElement | null;
  if (b.custom_css?.trim()) {
    if (!el) {
      el = document.createElement('style');
      el.id = CUSTOM_STYLE_ID;
      document.head.appendChild(el);
    }
    el.textContent = b.custom_css;
  } else if (el) {
    el.remove();
  }
}

export async function loadBranding(): Promise<Branding> {
  const b = await fetchBranding();
  branding.set(b);
  applyBrandingToDocument(b);
  const t = (b.app_title || BUILTIN.title).trim();
  document.title = t;
  return b;
}

export function effectiveLogo(b: Branding | null): string {
  if (!b) return BUILTIN.logo;
  return (b.logo_url || '').trim() || BUILTIN.logo;
}

export function effectiveTitle(b: Branding | null): string {
  if (!b) return BUILTIN.title;
  return (b.app_title || '').trim() || BUILTIN.title;
}

export function effectiveTagline(b: Branding | null): string {
  if (!b) return BUILTIN.tagline;
  const t = (b.tagline || '').trim();
  if (t) return t;
  const anyBrand =
    (b.logo_url || '').trim() ||
    (b.app_title || '').trim() ||
    (b.primary_color || '').trim() ||
    (b.custom_css || '').trim();
  return anyBrand ? '' : BUILTIN.tagline;
}

export function effectiveLogoAlt(b: Branding | null, title: string): string {
  if (!b) return title;
  return (b.logo_alt || '').trim() || title;
}

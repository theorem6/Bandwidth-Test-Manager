/** Allowed cron schedules (must match server whitelist in main.py). */
export const CRON_PRESETS = [
  {
    id: 'hourly',
    label: 'Once every hour',
    detail: 'Runs at 5 minutes past each hour (server time).',
    cron: '5 * * * *',
  },
  {
    id: 'daily',
    label: 'Once per day',
    detail: 'Runs every day at 6:05 AM (server time).',
    cron: '5 6 * * *',
  },
  {
    id: 'four_daily',
    label: 'Four times per day',
    detail: 'Every 6 hours: 12:05 AM, 6:05 AM, 12:05 PM, and 6:05 PM (server time).',
    cron: '5 */6 * * *',
  },
] as const;

const ALLOWED = new Set(CRON_PRESETS.map((p) => p.cron));

/** Map saved config value to one of the presets (handles legacy custom crons). */
export function normalizeCronToPreset(cron: string): string {
  const c = cron.trim().replace(/\s+/g, ' ');
  if (ALLOWED.has(c)) return c;
  // Legacy: common hourly / daily patterns → closest preset
  const parts = c.split(/\s+/);
  if (parts.length >= 5) {
    const hour = parts[1];
    const day = parts[2];
    if (hour === '*/6') return '5 */6 * * *';
    if (hour === '*' && day === '*') return '5 * * * *';
  }
  return '5 6 * * *';
}

export function presetLabelForCron(cron: string): string {
  const n = normalizeCronToPreset(cron);
  const p = CRON_PRESETS.find((x) => x.cron === n);
  return p ? p.label : 'Once every hour';
}

export function describeCronSchedule(cron: string): string {
  const n = normalizeCronToPreset(cron);
  const p = CRON_PRESETS.find((x) => x.cron === n);
  return p ? `${p.label}. ${p.detail}` : cron;
}

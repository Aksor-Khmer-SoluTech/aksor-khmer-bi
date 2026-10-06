export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

/** Status-palette thresholds — fixed steps, not themed (see the dataviz
 * skill's status palette: good/warning/serious/critical are reserved and
 * always paired with a text label, never color alone). */
export type MeterState = "good" | "warning" | "serious" | "critical";

export function meterState(percent: number): MeterState {
  if (percent >= 93) return "critical";
  if (percent >= 80) return "serious";
  if (percent >= 60) return "warning";
  return "good";
}

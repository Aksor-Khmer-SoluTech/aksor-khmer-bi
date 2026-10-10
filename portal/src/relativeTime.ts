/** "5 minutes ago" / "yesterday" / a date -- how long ago something happened. */
export function ago(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 172_800) return "yesterday";
  return new Date(iso).toLocaleDateString();
}

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "in 12 h" / "in 3 days" / a date -- how long until something happens. */
export function until(iso: string): string {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  if (seconds <= 0) return "now";
  if (seconds < 3600) return `in ${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86_400) return `in ${Math.round(seconds / 3600)} h`;
  if (seconds < 14 * 86_400) return `in ${plural(Math.round(seconds / 86_400), "day")}`;
  return `on ${new Date(iso).toLocaleDateString()}`;
}

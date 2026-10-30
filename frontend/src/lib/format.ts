/** Formatting helpers — pure functions, unit-tested. */

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds % 1 === 0 ? 0 : 2)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function formatClock(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) totalSeconds = 0;
  const m = Math.floor(totalSeconds / 60);
  const s = Math.floor(totalSeconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes == null || Number.isNaN(minutes)) return "—";
  if (minutes < 1) return "<1 min";
  return `${minutes < 10 ? minutes.toFixed(1) : Math.round(minutes)} min`;
}

export function percentOf(value: number, total: number): number {
  if (!total || total <= 0) return 0;
  return Math.min(100, Math.max(0, (value / total) * 100));
}

export const JOB_STAGE_ORDER = [
  "QUEUED", "PREFLIGHT", "INITIALIZING", "GENERATING", "ASSEMBLING",
  "INTERPOLATING", "ENCODING", "VALIDATING", "COMPLETED",
] as const;

export const STAGE_LABELS: Record<string, string> = {
  QUEUED: "Queued",
  PREFLIGHT: "Pre-flight checks",
  INITIALIZING: "Initializing engine",
  GENERATING: "Generating frames (AI inference)",
  ASSEMBLING: "Assembling video",
  INTERPOLATING: "Interpolating frames",
  ENCODING: "Encoding MP4",
  VALIDATING: "Validating output",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

export function isTerminal(status: string | null | undefined): boolean {
  return status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
}

/** System display bits: readiness banner (health ≠ readiness), resource
 *  bars, hardware tiles. VRAM shown is DEDICATED memory only — shared
 *  system RAM is never counted as VRAM. */

import {
  AlertTriangle, CheckCircle2, CircleSlash, Cpu, HardDrive, MemoryStick,
  MonitorSmartphone, XCircle,
} from "lucide-react";
import type { SystemReport } from "../lib/types";
import { formatBytes } from "../lib/format";
import { Badge, StatTile } from "./ui";

export function ReadinessBanner({ report }: { report: SystemReport | null }) {
  if (!report) {
    return (
      <div className="flex items-center gap-2.5 rounded-xl border border-line bg-ink-900 px-4 py-3 text-xs text-faint">
        <CircleSlash size={15} /> Waiting for the backend…
      </div>
    );
  }
  const r = report.readiness;
  const tone = r.level === "READY"
    ? { cls: "border-ok/30 bg-ok-soft text-ok", Icon: CheckCircle2, label: "READY — generation preflight passes" }
    : r.level === "WARNING"
      ? { cls: "border-warn/30 bg-warn-soft text-warn", Icon: AlertTriangle, label: "READY WITH WARNINGS" }
      : { cls: "border-danger/30 bg-danger-soft text-danger", Icon: XCircle, label: "NOT READY — generation is blocked" };
  const { cls, Icon, label } = tone;

  return (
    <div className={`rounded-xl border px-4 py-3 ${cls}`} role="status">
      <p className="flex items-center gap-2 text-xs font-semibold">
        <Icon size={15} /> {label}
      </p>
      {r.reasons.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-0.5">
          {r.reasons.map((x) => <li key={x} className="text-[11.5px] leading-snug opacity-90">• {x}</li>)}
        </ul>
      )}
      {r.warnings.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-0.5">
          {r.warnings.map((x) => <li key={x} className="text-[11.5px] leading-snug opacity-80">• {x}</li>)}
        </ul>
      )}
      <p className="mt-1.5 text-[10.5px] opacity-70">
        HTTP health being 200 only means the API answers — this verdict additionally checks
        engine, FFmpeg, models and free resources.
      </p>
    </div>
  );
}

function Bar({ label, used, total, unit, dangerAt = 90 }: {
  label: string; used: number | null; total: number | null; unit: string; dangerAt?: number;
}) {
  const pct = used != null && total ? Math.min(100, Math.round((used / total) * 100)) : null;
  const color = pct == null ? "bg-ink-600" : pct >= dangerAt ? "bg-danger" : pct >= 75 ? "bg-warn" : "bg-accent";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-[11px]">
        <span className="text-muted">{label}</span>
        <span className="font-mono text-faint">
          {used != null && total ? `${used.toFixed(1)} / ${total.toFixed(1)} ${unit}` : "n/a"}
          {pct != null && <span className="ml-1.5">({pct}%)</span>}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-750">
        <div className={`h-full rounded-full transition-[width] duration-500 ${color}`}
          style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  );
}

export function ResourceBars({ report }: { report: SystemReport | null }) {
  if (!report) return null;
  const mem = report.memory;
  const gpu = report.gpu;
  const disk = report.disks[0];
  return (
    <div className="flex flex-col gap-3.5 rounded-2xl border border-line-soft bg-ink-900/70 p-4">
      <Bar label="System RAM (8 GB machine — pressure watched before jobs)"
        used={mem.total_gb != null && mem.available_gb != null ? mem.total_gb - mem.available_gb : null}
        total={mem.total_gb} unit="GB" dangerAt={88} />
      {gpu && gpu.vram_total_mb != null && (
        <Bar label={`Dedicated VRAM — ${gpu.name ?? "GPU"} (shared memory NOT counted)`}
          used={gpu.vram_used_mb != null ? gpu.vram_used_mb / 1024 : null}
          total={gpu.vram_total_mb / 1024} unit="GB" dangerAt={92} />
      )}
      {disk && (
        <Bar label={`Disk — ${disk.path}`}
          used={disk.total_gb != null && disk.free_gb != null ? disk.total_gb - disk.free_gb : null}
          total={disk.total_gb} unit="GB" />
      )}
    </div>
  );
}

export function HardwareTiles({ report }: { report: SystemReport | null }) {
  if (!report) return null;
  const gpu = report.gpu;
  const disk = report.disks[0];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile label="CPU" value={report.cpu.name ?? "unknown"}
        sub={`${report.cpu.physical_cores ?? "?"}c / ${report.cpu.logical_cores ?? "?"}t`} />
      <StatTile
        label="GPU"
        value={gpu?.name ?? "none detected"}
        tone={gpu?.cuda_available === true ? "ok" : gpu ? "warn" : "danger"}
        sub={gpu
          ? `${gpu.vram_total_mb != null ? `${(gpu.vram_total_mb / 1024).toFixed(1)} GB dedicated VRAM` : "VRAM unknown"}${gpu.driver_version ? ` · driver ${gpu.driver_version}` : ""}`
          : "Generation requires an NVIDIA GPU with CUDA"}
      />
      <StatTile label="RAM"
        value={report.memory.total_gb != null ? `${report.memory.total_gb.toFixed(1)} GB` : "?"}
        tone={report.memory.used_percent != null && report.memory.used_percent > 88 ? "warn" : undefined}
        sub={report.memory.available_gb != null ? `${report.memory.available_gb.toFixed(1)} GB available` : undefined} />
      <StatTile label="Disk free"
        value={disk?.free_gb != null ? `${disk.free_gb.toFixed(0)} GB` : "?"}
        tone={disk?.free_gb != null && disk.free_gb < 10 ? "danger" : disk?.free_gb != null && disk.free_gb < 20 ? "warn" : undefined}
        sub={disk?.path} />
      <StatTile label="ComfyUI engine"
        value={report.engine.online ? "online" : "offline"}
        tone={report.engine.online ? "ok" : "danger"}
        sub={report.engine.online
          ? `v${report.engine.comfyui_version ?? "?"} · torch ${report.engine.torch_version ?? "?"}`
          : "Start it from the System page or run Start-Studio"} />
      <StatTile label="FFmpeg"
        value={report.ffmpeg.available ? "available" : "missing"}
        tone={report.ffmpeg.available ? "ok" : "danger"}
        sub={report.ffmpeg.version ?? report.ffmpeg.hint ?? undefined} />
      <StatTile label="Installed models"
        value={String(report.installed_models.length)}
        sub={report.installed_models.length ? report.installed_models.join(", ") : "Install from the Models page"} />
      <StatTile label="Queue"
        value={report.queue.running_job_id ? "1 running" : "idle"}
        sub={`${report.queue.queued} queued · max ${report.queue.max_queue_length} (sequential by design)`} />
    </div>
  );
}

export function OsLine({ report }: { report: SystemReport | null }) {
  if (!report) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-faint">
      <Badge tone="neutral"><MonitorSmartphone size={10} /> {report.os.system} {report.os.release} ({report.os.machine})</Badge>
      <Badge tone="neutral"><Cpu size={10} /> Python {report.python_version}</Badge>
      <Badge tone="neutral"><MemoryStick size={10} /> NOVA {report.backend_version}</Badge>
      <Badge tone="neutral"><HardDrive size={10} /> {formatBytes(report.disks[0]?.free_gb != null ? report.disks[0].free_gb * 1e9 : null)} free</Badge>
    </div>
  );
}

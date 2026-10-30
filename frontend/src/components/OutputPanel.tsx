/** Completed-output panel: VideoPlayer + exact validated metadata +
 *  honest provenance + actions (download / reveal / reuse). */

import { Download, FolderOpen, Gauge, Wand2 } from "lucide-react";
import { videoFileUrl } from "../lib/api";
import { formatBytes } from "../lib/format";
import type { GenerationJob } from "../lib/types";
import { Badge } from "./ui";
import { VideoPlayer } from "./VideoPlayer";
import { ProvenanceBadges } from "./VideoCard";

function MetaRow({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="shrink-0 text-[11px] text-faint">{label}</span>
      <span className={`truncate text-right text-[11.5px] text-muted ${mono ? "font-mono" : ""}`} title={value}>
        {value}
      </span>
    </div>
  );
}

export function OutputPanel({ job, onReuse, onReveal }: {
  job: GenerationJob;
  onReuse: () => void;
  onReveal: () => void;
}) {
  const v = job.output;
  if (!v || !v.file_exists) {
    return (
      <div className="rounded-xl border border-line bg-ink-900 p-4 text-xs text-faint">
        No output file recorded for this job.
      </div>
    );
  }
  const metrics = job.metrics ?? {};

  return (
    <div className="flex flex-col gap-4">
      <VideoPlayer src={videoFileUrl(v.video_id)} poster={v.thumbnail_url ?? undefined} />

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ok"><Gauge size={10} /> duration validated ±1 frame</Badge>
        <ProvenanceBadges v={v} small />
      </div>

      <div className="grid grid-cols-1 gap-x-8 sm:grid-cols-2">
        <div className="divide-y divide-line-soft/60">
          <MetaRow label="Exact duration" value={`${(v.duration_seconds ?? 0).toFixed(3)} s`} />
          <MetaRow label="Resolution" value={`${v.width}×${v.height} px`} />
          <MetaRow label="Frame rate" value={`${v.fps?.toFixed(2)} fps${v.interpolated ? " (interpolated)" : " (native)"}`} />
          <MetaRow label="Codec" value={v.codec ?? "h264"} />
          <MetaRow label="File size" value={formatBytes(v.size_bytes)} />
        </div>
        <div className="divide-y divide-line-soft/60">
          <MetaRow label="Seed" value={v.seed != null ? String(v.seed) : "—"} />
          <MetaRow label="Model" value={v.model_id} mono={false} />
          <MetaRow label="Route" value={v.route_label ?? v.generation_mode} mono={false} />
          {typeof metrics.generation_seconds === "number" && (
            <MetaRow label="Generation time" value={`${metrics.generation_seconds.toFixed(1)} s`} />
          )}
          {typeof metrics.total_seconds === "number" && (
            <MetaRow label="Total job time" value={`${metrics.total_seconds.toFixed(1)} s`} />
          )}
        </div>
      </div>

      {v.interpolated && (
        <p className="rounded-lg border border-accent/20 bg-accent-soft/40 px-3 py-2 text-[11.5px] leading-relaxed text-muted">
          <strong className="text-accent-hi">Honest label:</strong> frames above the model's native
          8 fps were estimated by motion interpolation. The diffusion model generated every
          source frame; interpolation only smooths playback.
        </p>
      )}
      {v.upscaled && (
        <p className="rounded-lg border border-line bg-ink-900 px-3 py-2 text-[11.5px] leading-relaxed text-muted">
          <strong className="text-txt">Honest label:</strong> this export was resized with Lanczos
          (conventional filtering) — not AI super-resolution. No detail was invented.
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <a href={videoFileUrl(v.video_id)} download={`nova-${v.video_id.slice(0, 8)}.mp4`}
          className="focus-ring inline-flex h-9 items-center gap-2 rounded-xl bg-accent px-4 text-xs font-medium text-white shadow-[0_2px_12px_rgba(79,141,255,0.25)] transition hover:bg-[#6ba0ff]">
          <Download size={14} /> Download MP4
        </a>
        <button onClick={onReveal}
          className="focus-ring inline-flex h-9 items-center gap-2 rounded-xl border border-line bg-ink-750 px-4 text-xs font-medium text-txt transition hover:bg-ink-700">
          <FolderOpen size={14} /> Show in folder
        </button>
        <button onClick={onReuse}
          className="focus-ring inline-flex h-9 items-center gap-2 rounded-xl bg-transparent px-4 text-xs font-medium text-muted transition hover:bg-ink-800 hover:text-txt">
          <Wand2 size={14} /> Reuse settings
        </button>
      </div>
    </div>
  );
}

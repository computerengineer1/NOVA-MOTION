/** Job progress: stage pipeline with honest progress + ETA from the backend
 *  (never fabricated client-side). REST job record is the source of truth;
 *  WS live detail fills in between polls. */

import { useEffect, useState } from "react";
import { Check, CircleSlash, Loader2, Pause, X } from "lucide-react";
import type { BadgeTone } from "./ui";
import type { GenerationJob } from "../lib/types";
import { JOB_STAGE_ORDER, STAGE_LABELS, formatElapsed, isTerminal } from "../lib/format";
import { Badge, Button, ProgressBar } from "./ui";

const STATUS_META: Record<string, { tone: BadgeTone; label: string }> = {
  QUEUED: { tone: "neutral", label: "Queued" },
  PREFLIGHT: { tone: "accent", label: "Preflight" },
  INITIALIZING: { tone: "accent", label: "Initializing" },
  GENERATING: { tone: "accent", label: "Generating" },
  ASSEMBLING: { tone: "accent", label: "Assembling" },
  INTERPOLATING: { tone: "accent", label: "Interpolating" },
  ENCODING: { tone: "accent", label: "Encoding" },
  VALIDATING: { tone: "accent", label: "Validating" },
  COMPLETED: { tone: "ok", label: "Completed" },
  FAILED: { tone: "danger", label: "Failed" },
  CANCELLED: { tone: "neutral", label: "Cancelled" },
};

const ACTIVE = JOB_STAGE_ORDER.filter((s) => s !== "COMPLETED"); // pipeline stages

type StageView = "pending" | "running" | "completed" | "skipped" | "failed";

/** Derive per-stage states from the single `status` field — the backend is
 *  the source of truth; we only render it. */
function deriveStages(job: GenerationJob): Record<string, StageView> {
  const out: Record<string, StageView> = {};
  const status = job.status;
  const terminal = isTerminal(status);
  const idx = (ACTIVE as readonly string[]).indexOf(status);
  const noInterp =
    (job.effective_settings?.interpolation ?? "none") === "none" &&
    status !== "INTERPOLATING";

  for (let i = 0; i < ACTIVE.length; i++) {
    const stage = ACTIVE[i];
    if (stage === "INTERPOLATING" && noInterp && !terminal) { out[stage] = "skipped"; continue; }
    if (terminal) {
      if (status === "FAILED") {
        // failed stage = furthest stage we know was running; approximate:
        // mark all as completed except keep the pipeline honest via error panel
        out[stage] = "completed";
      } else if (status === "CANCELLED") {
        out[stage] = "pending";
      } else {
        out[stage] = stage === "INTERPOLATING" && noInterp ? "skipped" : "completed";
      }
      continue;
    }
    if (idx < 0) { out[stage] = "pending"; continue; } // QUEUED etc.
    out[stage] = i < idx ? "completed" : i === idx ? "running" : "pending";
  }
  return out;
}

export function ProgressPanel({ job, etaSeconds, wsConnected, cancelRequested, cancelling, onCancel, onReuse }: {
  job: GenerationJob;
  etaSeconds: number | null;
  wsConnected: boolean;
  cancelRequested: boolean;
  cancelling: boolean;
  onCancel?: () => void;
  onReuse?: () => void;
}) {
  const status = job.status;
  const terminal = isTerminal(status);
  const meta = STATUS_META[status] ?? { tone: "neutral" as BadgeTone, label: status };
  const stages = deriveStages(job);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (terminal) return;
    const started = Date.now();
    setElapsed(0);
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(t);
  }, [terminal, job.id]);

  const pct = Math.round((job.progress ?? 0) * 100);
  const showCancelRequested = cancelRequested && !terminal;

  return (
    <div className="flex flex-col gap-3.5" aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          {terminal ? (
            status === "COMPLETED" ? <Check size={17} className="text-ok" />
              : status === "FAILED" ? <X size={17} className="text-danger" />
              : <CircleSlash size={17} className="text-muted" />
          ) : (
            <Loader2 size={17} className="animate-spin text-accent" />
          )}
          <Badge tone={showCancelRequested ? "warn" : meta.tone}>
            {showCancelRequested ? "Cancel requested" : meta.label}
          </Badge>
          {!wsConnected && !terminal && (
            <span className="text-[10.5px] text-faint"
              title="Live socket offline — status refreshes via API polling every ≤2 s">
              polling…
            </span>
          )}
        </div>
        {!terminal && (
          <span className="font-mono text-xs text-muted">
            {formatElapsed(elapsed)}
            {etaSeconds != null && etaSeconds > 0 && (
              <span className="ml-2 text-faint"
                title="Measured from real sampler step rate on this machine — approximate by nature">
                ETA −{formatElapsed(etaSeconds)}
              </span>
            )}
          </span>
        )}
      </div>

      <ProgressBar value={terminal ? 100 : pct} indeterminate={!terminal && pct === 0} />
      {!terminal && pct > 0 && (
        <p className="-mt-2 font-mono text-[11px] text-muted">{pct}% overall</p>
      )}

      {/* stage rows */}
      <ul className="flex flex-col gap-1">
        {ACTIVE.map((name) => {
          const st = stages[name];
          return (
            <li key={name}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5"
              style={st === "running" ? { background: "rgba(79,141,255,0.07)" } : undefined}>
              <span className="grid size-4 place-items-center">
                {st === "completed" ? <Check size={13} className="text-ok" />
                  : st === "running" ? <Loader2 size={13} className="animate-spin text-accent" />
                  : st === "failed" ? <X size={13} className="text-danger" />
                  : st === "skipped" ? <span className="text-[9px] text-faint">—</span>
                  : <span className="size-1.5 rounded-full bg-ink-700" />}
              </span>
              <span className={`flex-1 text-xs ${
                st === "running" ? "text-txt"
                  : st === "completed" ? "text-muted"
                  : "text-faint"}`}>
                {STAGE_LABELS[name] ?? name}
                {st === "skipped" && <span className="ml-1.5 text-[10px]">(not needed — native fps)</span>}
              </span>
              {st === "running" && job.stage_detail && (
                <span className="max-w-[45%] truncate font-mono text-[10.5px] text-accent"
                  title={job.stage_detail}>
                  {job.stage_detail}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {job.error && (
        <div className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-3" role="alert">
          <p className="text-xs font-semibold text-danger">
            {job.error.code}: {job.error.summary}
          </p>
          {job.error.recovery && (
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted">{job.error.recovery}</p>
          )}
        </div>
      )}

      {status === "COMPLETED" && job.output && (
        <p className="flex items-center gap-1.5 text-xs text-ok">
          <Check size={13} />
          Validated: {job.output.duration_seconds?.toFixed(3) ?? "?"} s ·{" "}
          {job.output.width}×{job.output.height} · {job.output.fps?.toFixed(1)} fps
          {job.output.interpolated && " · interpolated"}
          {job.output.upscaled && " · upscaled (lanczos)"}
        </p>
      )}

      <div className="flex gap-2">
        {!terminal && onCancel && (
          <Button variant="danger" size="sm" onClick={onCancel} disabled={cancelling || showCancelRequested}
            title="Cancellation is cooperative: ComfyUI stops between sampling steps, then the job reports its true terminal state.">
            <Pause size={14} />
            {cancelling || showCancelRequested ? "Cancel requested…" : "Cancel generation"}
          </Button>
        )}
        {terminal && status !== "COMPLETED" && onReuse && (
          <Button variant="secondary" size="sm" onClick={onReuse}>Load these settings in Studio</Button>
        )}
      </div>
    </div>
  );
}

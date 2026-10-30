/** Generation settings: duration, aspect, resolution, steps/cfg, sampler,
 *  export fps, interpolation, upscale, mode — with unsupported combinations
 *  disabled and honest capability labels. */

import { AlertTriangle, Info } from "lucide-react";
import type { EffectiveSettings, ModelProfile, PreflightResult } from "../lib/types";
import { Field, Segmented, Select, Toggle } from "./ui";

export interface SettingsState {
  durationSeconds: number;
  aspectRatio: "16:9" | "9:16" | "1:1";
  resolutionId: string | null;
  steps: number;
  cfg: number;
  sampler: string;
  scheduler: string;
  generationMode: "auto" | "native_long" | "multi_shot";
  exportFps: 8 | 16 | 24;
  interpolation: "none" | "minterpolate" | "rife";
  upscaleExport: boolean;
}

export function GenerationSettings({ state, onChange, model, effective, busy, rifeAvailable }: {
  state: SettingsState;
  onChange: (patch: Partial<SettingsState>) => void;
  model: ModelProfile | null;
  effective: EffectiveSettings | null;
  busy: boolean;
  rifeAvailable: boolean;
}) {
  const caps = model?.capabilities ?? {};
  const durations = caps.durations_s ?? [8];
  const resolutions = (caps.resolutions ?? []).filter(
    (r) => r.aspect === state.aspectRatio,
  );
  const modes = caps.modes ?? ["native_long", "multi_shot"];
  const defaultRes = resolutions.find((r) => r.default) ?? resolutions[0];
  const effW = effective?.width ?? defaultRes?.width ?? 0;
  const effH = effective?.height ?? defaultRes?.height ?? 0;

  return (
    <div className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2">
      <Field label="Target duration" hint="8.000 s final export">
        <Select value={String(state.durationSeconds)} disabled={busy}
          onChange={(e) => onChange({ durationSeconds: Number(e.target.value) })}
          aria-label="Target duration in seconds">
          {durations.map((d) => (
            <option key={d} value={String(d)}>{d.toFixed(1)} s{d === 8 ? " (default)" : ""}</option>
          ))}
        </Select>
      </Field>

      <Field label="Aspect ratio">
        <Segmented
          ariaLabel="Aspect ratio"
          value={state.aspectRatio}
          onChange={(v) => onChange({ aspectRatio: v, resolutionId: null })}
          options={[
            { value: "16:9", label: "16:9 Landscape" },
            { value: "1:1", label: "1:1 Square" },
            { value: "9:16", label: "9:16 Portrait" },
          ]}
        />
      </Field>

      <Field label="Resolution" hint="native model size">
        <Select value={state.resolutionId ?? ""} disabled={busy}
          onChange={(e) => onChange({ resolutionId: e.target.value || null })}
          aria-label="Generation resolution">
          <option value="">Default for aspect</option>
          {resolutions.map((r) => (
            <option key={r.id} value={r.id}>
              {r.width}×{r.height}{r.high_vram_risk ? " ⚠ high VRAM risk" : ""}
            </option>
          ))}
        </Select>
        {resolutions.find((r) => r.id === state.resolutionId)?.high_vram_risk && (
          <p className="mt-1 flex items-start gap-1.5 text-[11px] leading-snug text-warn">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            This preset may exceed 4 GB VRAM even with low-memory mode. If it OOMs,
            one automatic lower-memory retry is attempted, then generation stops safely.
          </p>
        )}
        {resolutions.find((r) => r.id === state.resolutionId)?.note && (
          <p className="mt-1 text-[11px] text-faint">{resolutions.find((r) => r.id === state.resolutionId)?.note}</p>
        )}
      </Field>

      <Field label="Generation mode" hint={modes.length > 1 ? undefined : "fixed by model"}>
        <Select value={state.generationMode} disabled={busy}
          onChange={(e) => onChange({ generationMode: e.target.value as SettingsState["generationMode"] })}
          aria-label="Generation mode">
          <option value="auto">Auto (prefer continuous)</option>
          <option value="native_long" disabled={!modes.includes("native_long")}>
            Native long — one continuous run
          </option>
          <option value="multi_shot" disabled={!modes.includes("multi_shot")}>
            Multi-shot — 4 × ~2 s segments
          </option>
        </Select>
      </Field>

      <Field label="Quality steps" hint={`${state.steps} steps · 4–40`}>
        <input type="range" min={4} max={40} step={1} value={state.steps} disabled={busy}
          onChange={(e) => onChange({ steps: Number(e.target.value) })}
          aria-label="Inference steps"
          className="mt-2.5 h-1.5 w-full cursor-pointer accent-[#4f8dff]" />
        <div className="mt-1 flex justify-between text-[10.5px] text-faint">
          <span>faster / softer</span><span>slower / sharper</span>
        </div>
      </Field>

      <Field label="Guidance (CFG)" hint={state.cfg.toFixed(1)}>
        <input type="range" min={1} max={15} step={0.5} value={state.cfg} disabled={busy}
          onChange={(e) => onChange({ cfg: Number(e.target.value) })}
          aria-label="Classifier-free guidance scale"
          className="mt-2.5 h-1.5 w-full cursor-pointer accent-[#4f8dff]" />
        <div className="mt-1 flex justify-between text-[10.5px] text-faint">
          <span>creative</span><span>prompt-strict</span>
        </div>
      </Field>

      <Field label="Sampler" hint="advanced">
        <Select value={state.sampler} disabled={busy} aria-label="Sampler"
          onChange={(e) => onChange({ sampler: e.target.value })}>
          {["dpmpp_2m", "euler", "euler_ancestral", "dpmpp_sde", "uni_pc"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
      </Field>

      <Field label="Scheduler" hint="advanced">
        <Select value={state.scheduler} disabled={busy} aria-label="Scheduler"
          onChange={(e) => onChange({ scheduler: e.target.value })}>
          {["karras", "normal", "exponential", "sgm_uniform"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
      </Field>

      <Field label="Export frame rate" hint={`model native: ${caps.source_fps ?? 8} fps`}>
        <Segmented
          ariaLabel="Export frame rate"
          value={String(state.exportFps) as "8" | "16" | "24"}
          onChange={(v) => {
            const fps = Number(v) as 8 | 16 | 24;
            onChange({
              exportFps: fps,
              interpolation: fps > (caps.source_fps ?? 8) && state.interpolation === "none"
                ? "minterpolate" : fps === 8 ? "none" : state.interpolation,
            });
          }}
          options={[
            { value: "8", label: "8 fps · native", title: "Model-native frame rate — no post-processing" },
            { value: "16", label: "16 fps", title: "Requires interpolation" },
            { value: "24", label: "24 fps", title: "Requires interpolation" },
          ]}
        />
      </Field>

      <Field label="Interpolation" hint={state.exportFps > 8 ? "required above 8 fps" : "n/a at 8 fps"}>
        <Select value={state.interpolation} disabled={busy || state.exportFps === 8}
          aria-label="Interpolation method"
          onChange={(e) => onChange({ interpolation: e.target.value as SettingsState["interpolation"] })}>
          <option value="none">None — native frames only</option>
          <option value="minterpolate">
            FFmpeg minterpolate (motion-compensated, conventional — not generative)
          </option>
          <option value="rife" disabled={!rifeAvailable}>
            RIFE optical flow (AI) — {rifeAvailable ? "node pack installed" : "node pack not installed"}
          </option>
        </Select>
        {state.interpolation !== "none" && (
          <p className="mt-1 flex items-start gap-1.5 text-[11px] leading-snug text-faint">
            <Info size={12} className="mt-0.5 shrink-0" />
            Interpolation estimates in-between frames from motion. It does not create new
            events or guarantee physically correct motion, and the result is labeled as
            interpolated everywhere in the app.
          </p>
        )}
      </Field>

      <div className="sm:col-span-2">
        <Toggle
          checked={state.upscaleExport} disabled={busy}
          onChange={(v) => onChange({ upscaleExport: v })}
          label="Upscale export ×2 (Lanczos)"
          description={`Conventional resize to ${effW * 2}×${effH * 2} — NOT AI super-resolution; no new detail is created. Slightly larger file, softer look on big screens.`}
        />
      </div>
    </div>
  );
}

/** Live summary of what will actually happen (server-computed via preflight). */
export function EffectiveSummary({ effective, preflight }: {
  effective: EffectiveSettings | null; preflight: PreflightResult | null;
}) {
  if (!effective) {
    return (
      <div className="rounded-xl border border-line bg-ink-900 p-3.5 text-xs text-faint">
        Select a model and settings — the exact generation route will be summarized here.
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-line bg-ink-900 p-3.5">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted">
        <span>
          {effective.final_width}×{effective.final_height} px
          {effective.upscale_export ? " (lanczos ×2)" : ""}
        </span>
        <span>{effective.total_frames} source frames</span>
        <span>{effective.source_fps} fps model → {effective.export_fps} fps export</span>
        <span>{effective.segments > 1 ? `${effective.segments} segments × ${effective.frames_per_segment}f` : "single run"}</span>
        <span>≈{effective.estimated_output_size_mb ?? "?"} MB</span>
        {effective.estimated_minutes_low != null && (
          <span title="Rough estimate for RTX 2050-class hardware — not a promise">
            est. {effective.estimated_minutes_low}–{effective.estimated_minutes_high} min
          </span>
        )}
      </div>
      <p className="text-[11.5px] leading-relaxed text-faint">{effective.route_label}</p>
      {preflight && preflight.blockers.length > 0 && (
        <div className="mt-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2" role="alert">
          {preflight.blockers.map((b) => (
            <p key={b} className="flex items-start gap-1.5 text-[11.5px] leading-snug text-danger">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />{b}
            </p>
          ))}
        </div>
      )}
      {preflight && preflight.warnings.length > 0 && (
        <div className="mt-2.5 rounded-lg border border-warn/25 bg-warn-soft px-3 py-2">
          {preflight.warnings.map((w) => (
            <p key={w} className="flex items-start gap-1.5 text-[11.5px] leading-snug text-warn">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />{w}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

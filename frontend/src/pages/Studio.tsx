/** Studio — compose a generation, watch honest progress, get the validated
 *  8-second MP4. Everything shown comes from the backend; nothing is faked. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Boxes, History, Play, Sparkles } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useJobProgress, useSystemReport } from "../hooks/useBackend";
import { useToasts } from "../hooks/useToasts";
import { formatTimestamp, isTerminal } from "../lib/format";
import type {
  AppSettings, GenerationJob, ModelProfile, PreflightResult, PresetsResponse,
} from "../lib/types";
import { Badge, Button, Card, Select } from "../components/ui";
import { PromptEditor, type PromptState } from "../components/PromptEditor";
import {
  GenerationSettings, EffectiveSummary, type SettingsState,
} from "../components/GenerationSettings";
import { ProgressPanel } from "../components/ProgressPanel";
import { OutputPanel } from "../components/OutputPanel";
import { ReadinessBanner } from "../components/SystemBits";
import { Header, PageTitle } from "../components/Layout";

const DEFAULT_SETTINGS: SettingsState = {
  durationSeconds: 8, aspectRatio: "16:9", resolutionId: null,
  steps: 16, cfg: 7.5, sampler: "dpmpp_2m", scheduler: "karras",
  generationMode: "auto", exportFps: 8, interpolation: "none", upscaleExport: false,
};

export default function StudioPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const reuseId = searchParams.get("reuse");
  const { push } = useToasts();
  const { report } = useSystemReport();

  const [models, setModels] = useState<ModelProfile[] | null>(null);
  const [modelId, setModelId] = useState("");
  const [presets, setPresets] = useState<PresetsResponse | null>(null);
  const [rifeAvailable, setRifeAvailable] = useState(false);
  const [prompt, setPrompt] = useState<PromptState>({
    prompt: "", negativePrompt: "", stylePreset: null, seed: null, randomSeed: true,
  });
  const [settings, setSettings] = useState<SettingsState>(DEFAULT_SETTINGS);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelRequested, setCancelRequested] = useState(false);
  const [history, setHistory] = useState<GenerationJob[]>([]);
  const defaultsApplied = useRef(false);

  const progress = useJobProgress(jobId);
  const job = progress.job;
  const busy = submitting || (job != null && !isTerminal(job.status));

  const model = useMemo(
    () => models?.find((m) => m.model_id === modelId) ?? null, [models, modelId]);
  const installedModels = useMemo(
    () => (models ?? []).filter((m) => m.installed && m.compatibility?.installable !== false),
    [models]);

  /* ---- initial load ---- */
  useEffect(() => {
    (async () => {
      try {
        const [ms, ps, st] = await Promise.all([api.models(), api.presets(), api.getSettings()]);
        setModels(ms);
        setPresets(ps);
        setPrompt((p) => ({ ...p, negativePrompt: p.negativePrompt || ps.default_negative_prompt }));
        // pick default model: saved preference → recommended → first installed
        const usable = ms.filter((m) => m.installed && m.compatibility?.installable !== false);
        const pref = String((st as AppSettings).default_model_id ?? "");
        const pick = usable.find((m) => m.model_id === pref)
          ?? usable.find((m) => m.status === "recommended") ?? usable[0];
        if (pick) setModelId(pick.model_id);
        if (!defaultsApplied.current) {
          defaultsApplied.current = true;
          setSettings((s) => ({
            ...s,
            steps: Number((st as AppSettings).default_steps ?? s.steps),
            cfg: Number((st as AppSettings).default_cfg ?? s.cfg),
            sampler: String((st as AppSettings).default_sampler ?? s.sampler),
            scheduler: String((st as AppSettings).default_scheduler ?? s.scheduler),
            durationSeconds: Number((st as AppSettings).default_duration_seconds ?? s.durationSeconds),
            aspectRatio: ((st as AppSettings).default_aspect_ratio as SettingsState["aspectRatio"]) ?? s.aspectRatio,
            generationMode: ((st as AppSettings).default_generation_mode as SettingsState["generationMode"]) ?? s.generationMode,
            exportFps: (Number((st as AppSettings).default_export_fps ?? s.exportFps) as 8 | 16 | 24),
            interpolation: ((st as AppSettings).default_interpolation as SettingsState["interpolation"]) ?? s.interpolation,
            upscaleExport: Boolean((st as AppSettings).default_upscale_export ?? s.upscaleExport),
          }));
        }
      } catch (e) {
        push("error", "Could not load Studio data", e instanceof ApiError ? e.message : String(e));
      }
    })();
    (async () => {
      try {
        const caps = await api.engineCapabilities();
        setRifeAvailable(caps.rife_available);
      } catch { /* engine offline — rife stays disabled with explanation */ }
    })();
    (async () => {
      try { setHistory(await api.generations(8)); } catch { /* non-fatal */ }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- reuse settings from a previous generation ---- */
  useEffect(() => {
    if (!reuseId) return;
    (async () => {
      try {
        const g = await api.generation(reuseId);
        const r = g.request ?? {};
        setPrompt({
          prompt: r.prompt ?? g.original_prompt ?? "",
          negativePrompt: r.negative_prompt ?? g.negative_prompt ?? "",
          stylePreset: null,
          seed: r.random_seed ? null : (r.seed ?? g.seed),
          randomSeed: r.random_seed ?? (g.seed == null),
        });
        if (g.model_id) setModelId(g.model_id);
        setSettings((s) => ({
          ...s,
          durationSeconds: Number(r.duration_seconds ?? s.durationSeconds),
          aspectRatio: (r.aspect_ratio as SettingsState["aspectRatio"]) ?? s.aspectRatio,
          resolutionId: (r.resolution_id as string | null) ?? null,
          steps: Number(r.steps ?? s.steps),
          cfg: Number(r.cfg ?? s.cfg),
          sampler: String(r.sampler ?? s.sampler),
          scheduler: String(r.scheduler ?? s.scheduler),
          generationMode: (r.generation_mode as SettingsState["generationMode"]) ?? s.generationMode,
          exportFps: (Number(r.export_fps ?? s.exportFps) as 8 | 16 | 24),
          interpolation: (r.interpolation as SettingsState["interpolation"]) ?? s.interpolation,
          upscaleExport: Boolean(r.upscale_export ?? s.upscaleExport),
        }));
        setJobId(g.id);
        setSearchParams({}, { replace: true });
        push("success", "Settings restored", "Prompt, model and output options were loaded from the previous generation.");
      } catch (e) {
        push("error", "Could not reuse that generation", e instanceof ApiError ? e.message : String(e));
        setSearchParams({}, { replace: true });
      }
    })();
  }, [reuseId]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- debounced preflight (server computes the truth) ---- */
  const preflightKey = JSON.stringify({ modelId, prompt: prompt.prompt, settings });
  useEffect(() => {
    if (!modelId || prompt.prompt.trim().length === 0) { setPreflight(null); return; }
    let cancelled = false;
    setPreflightBusy(true);
    const t = window.setTimeout(async () => {
      try {
        const r = await api.preflight(buildPayload());
        if (!cancelled) setPreflight(r);
      } catch (e) {
        if (!cancelled) {
          setPreflight({
            ok: false, level: "BLOCKED", checks: [], warnings: [],
            blockers: [e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)],
          });
        }
      } finally {
        if (!cancelled) setPreflightBusy(false);
      }
    }, 600);
    return () => { cancelled = true; window.clearTimeout(t); };
  }, [preflightKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const buildPayload = useCallback(() => ({
    prompt: prompt.prompt.trim(),
    negative_prompt: prompt.negativePrompt,
    model_id: modelId,
    duration_seconds: settings.durationSeconds,
    aspect_ratio: settings.aspectRatio,
    resolution_id: settings.resolutionId,
    steps: settings.steps,
    cfg: settings.cfg,
    sampler: settings.sampler,
    scheduler: settings.scheduler,
    seed: prompt.randomSeed ? null : prompt.seed,
    random_seed: prompt.randomSeed,
    generation_mode: settings.generationMode,
    export_fps: settings.exportFps,
    interpolation: settings.exportFps === 8 ? "none" as const : settings.interpolation,
    upscale_export: settings.upscaleExport,
  }), [prompt, settings, modelId]);

  /* ---- terminal-state side effects ---- */
  const prevStatus = useRef<string | null>(null);
  useEffect(() => {
    const st = job?.status ?? null;
    if (st && st !== prevStatus.current && isTerminal(st)) {
      void api.generations(8).then(setHistory).catch(() => {});
      setCancelRequested(false);
      if (st === "COMPLETED") push("success", "Generation completed", "The output passed duration validation (±1 frame).");
      if (st === "CANCELLED") push("info", "Generation cancelled", "No partial file was kept as a completed video.");
    }
    prevStatus.current = st;
  }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    setSubmitting(true);
    try {
      const created = await api.submitGeneration(buildPayload());
      setJobId(created.id);
      setCancelRequested(false);
      push("info", "Generation queued", `Job ${created.id.slice(0, 8)}… — sequential execution; progress below is measured, not simulated.`);
    } catch (e) {
      if (e instanceof ApiError) push("error", `${e.code}: ${e.message}`, undefined, e.recovery);
      else push("error", "Submit failed", String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (!jobId) return;
    setCancelling(true);
    try {
      const r = await api.cancelGeneration(jobId);
      if (r.cancel_requested) {
        setCancelRequested(true);
        push("warning", "Cancellation requested",
          "ComfyUI stops between sampling steps — the job will report its true final state (CANCELLED) shortly.");
      }
    } catch (e) {
      push("error", "Cancel failed", e instanceof ApiError ? e.message : String(e));
    } finally {
      setCancelling(false);
    }
  };

  const blocked = preflight != null && preflight.level === "BLOCKED";
  const canSubmit = !!modelId && prompt.prompt.trim().length > 0 && !busy && !blocked && !submitting;
  const effective = preflight?.effective ?? null;

  return (
    <>
      <Header right={report ? <ReadinessMini report={report} /> : undefined}>
        <PageTitle title="Studio" subtitle="Text → exactly 8.000 seconds of validated local video" />
      </Header>

      <div className="flex flex-col gap-5">
        {report && report.readiness.level !== "READY" && <ReadinessBanner report={report} />}

        {models && installedModels.length === 0 && (
          <Card>
            <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
              <Boxes size={26} className="shrink-0 text-faint" />
              <div className="flex-1">
                <p className="text-sm font-medium text-txt">No model is installed yet</p>
                <p className="mt-0.5 text-xs leading-relaxed text-muted">
                  Generation needs the AnimateDiff + SD 1.5 weights (~4 GB, one-time download,
                  license shown before install). Nothing generates without real weights — there
                  is no demo fallback.
                </p>
              </div>
              <Link to="/models"
                className="focus-ring inline-flex h-10 items-center gap-2 rounded-xl bg-accent px-4 text-sm font-medium text-white shadow-[0_2px_12px_rgba(79,141,255,0.25)] transition hover:bg-[#6ba0ff]">
                Open Models page
              </Link>
            </div>
          </Card>
        )}

        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
          {/* left: composition */}
          <div className="flex min-w-0 flex-col gap-5">
            <Card title={<span className="flex items-center gap-2"><Sparkles size={15} className="text-accent" /> Prompt</span>}
              actions={installedModels.length > 0 && (
                <div>
                  <Select value={modelId} onChange={(e) => setModelId(e.target.value)}
                    aria-label="Generation model" className="h-8 w-56 text-xs" disabled={busy}>
                    {installedModels.map((m) => (
                      <option key={m.model_id} value={m.model_id}>
                        {m.name}{m.status === "recommended" ? " ★" : ""}
                      </option>
                    ))}
                  </Select>
                </div>
              )}>
              <PromptEditor state={prompt} onChange={(p) => setPrompt((s) => ({ ...s, ...p }))}
                presets={presets} busy={busy} />
            </Card>

            <Card title="Generation & export settings">
              <GenerationSettings
                state={settings}
                onChange={(p) => setSettings((s) => ({ ...s, ...p }))}
                model={model} effective={effective} busy={busy} rifeAvailable={rifeAvailable} />
              <div className="mt-4">
                <EffectiveSummary effective={effective} preflight={preflightBusy ? null : preflight} />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <Button size="lg" variant="primary" disabled={!canSubmit} onClick={submit}>
                  <Play size={16} />
                  {busy ? "Working…" : "Generate 8-second video"}
                </Button>
                {preflightBusy && <span className="text-[11px] text-faint">checking feasibility…</span>}
                {!rifeAvailable && settings.interpolation === "rife" && (
                  <span className="text-[11px] text-warn">
                    RIFE node pack not detected in the engine — switch to minterpolate or install
                    the optional pack (see Help).
                  </span>
                )}
              </div>
            </Card>
          </div>

          {/* right: progress / output / history */}
          <div className="flex min-w-0 flex-col gap-5">
            <Card title="Progress">
              {job ? (
                <ProgressPanel
                  job={job}
                  etaSeconds={progress.etaSeconds}
                  wsConnected={progress.wsConnected}
                  cancelRequested={cancelRequested}
                  cancelling={cancelling}
                  onCancel={cancel}
                  onReuse={() => { setJobId(null); }}
                />
              ) : (
                <p className="text-xs leading-relaxed text-faint">
                  Nothing running. Queue a generation — progress shown here is measured from real
                  sampler steps and pipeline stages (with an honest ETA once step rate is
                  measurable), never simulated.
                </p>
              )}
              {job?.status === "COMPLETED" && job.output && (
                <div className="mt-4 border-t border-line-soft pt-4">
                  <OutputPanel job={job}
                    onReuse={() => setSearchParams({ reuse: job.id })}
                    onReveal={() => {
                      void api.revealVideo(job.output!.video_id)
                        .then(() => push("success", "Opened in Explorer", job.output!.video_id.slice(0, 8)))
                        .catch((e) => push("error", "Could not reveal file", e instanceof ApiError ? e.message : String(e)));
                    }} />
                </div>
              )}
            </Card>

            <Card title={<span className="flex items-center gap-2"><History size={14} className="text-faint" /> Recent jobs</span>}
              actions={<Link to="/videos" className="text-[11px] text-accent hover:underline">My Videos →</Link>}>
              {history.length === 0 ? (
                <p className="text-xs text-faint">No jobs yet.</p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {history.map((h) => (
                    <li key={h.id}>
                      <button
                        className="focus-ring flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-ink-800"
                        onClick={() => setJobId(h.id)}>
                        <Badge tone={h.status === "COMPLETED" ? "ok" : h.status === "FAILED" ? "danger"
                          : h.status === "CANCELLED" ? "neutral" : "accent"}>
                          {h.status}
                        </Badge>
                        <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted" title={h.original_prompt}>
                          {h.original_prompt}
                        </span>
                        <span className="shrink-0 font-mono text-[10px] text-faint">
                          {formatTimestamp(h.created_at)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}

function ReadinessMini({ report }: { report: NonNullable<ReturnType<typeof useSystemReport>["report"]> }) {
  const level = report.readiness.level;
  const tone = level === "READY" ? "ok" : level === "WARNING" ? "warn" : "danger";
  return (
    <Badge tone={tone} title={[...report.readiness.reasons, ...report.readiness.warnings].join("\n") || undefined}>
      {level}
    </Badge>
  );
}

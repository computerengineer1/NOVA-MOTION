/** Settings — persisted generation defaults + safety policy switches.
 *  Security-critical values (loopback binding, telemetry-off) are shown as
 *  read-only facts, not toggles: they are not user-negotiable by design. */

import { useEffect, useState } from "react";
import { Lock, Save, ShieldCheck, Undo2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useToasts } from "../hooks/useToasts";
import type { AppSettings, ModelProfile } from "../lib/types";
import { Badge, Button, Card, Field, Input, Select, Toggle } from "../components/ui";
import { Header, PageTitle } from "../components/Layout";

export default function SettingsPage() {
  const { push } = useToasts();
  const [saved, setSaved] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [s, ms] = await Promise.all([api.getSettings(), api.models()]);
        setSaved(s);
        setDraft({ ...s });
        setModels(ms.filter((m) => m.installed));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      }
    })();
  }, []);

  if (error) {
    return (
      <>
        <Header><PageTitle title="Settings" /></Header>
        <div className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-xs text-danger" role="alert">
          {error}
        </div>
      </>
    );
  }
  if (!draft || !saved) {
    return (
      <>
        <Header><PageTitle title="Settings" /></Header>
        <p className="text-sm text-faint">Loading settings…</p>
      </>
    );
  }

  const set = (key: string, value: string | number | boolean) =>
    setDraft((d) => ({ ...(d ?? {}), [key]: value }));
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.patchSettings(draft);
      setSaved(updated);
      setDraft({ ...updated });
      push("success", "Settings saved", "Defaults apply to the next generation you queue.");
    } catch (e) {
      push("error", "Could not save settings", e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Header right={
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" disabled={!dirty}
            onClick={() => setDraft({ ...saved })}>
            <Undo2 size={13} /> Discard changes
          </Button>
          <Button size="sm" variant="primary" disabled={!dirty || saving} onClick={save}>
            <Save size={13} /> {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      }>
        <PageTitle title="Settings" subtitle="Generation defaults stored in the local SQLite database" />
      </Header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Generation defaults">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Default model">
              <Select value={String(draft.default_model_id ?? "")}
                onChange={(e) => set("default_model_id", e.target.value)}>
                {models.length === 0 && <option value={String(draft.default_model_id ?? "")}>
                  (none installed — {String(draft.default_model_id ?? "")})
                </option>}
                {models.map((m) => (
                  <option key={m.model_id} value={m.model_id}>{m.name}</option>
                ))}
              </Select>
            </Field>
            <Field label="Duration (seconds)">
              <Select value={String(draft.default_duration_seconds ?? 8)}
                onChange={(e) => set("default_duration_seconds", Number(e.target.value))}>
                {[2, 4, 6, 8].map((d) => (
                  <option key={d} value={String(d)}>{d}.0 s{d === 8 ? " (primary target)" : ""}</option>
                ))}
              </Select>
            </Field>
            <Field label="Steps" hint="4–40">
              <Input type="number" min={4} max={40} value={Number(draft.default_steps ?? 16)}
                onChange={(e) => set("default_steps", Math.min(40, Math.max(4, Number(e.target.value) || 16)))} />
            </Field>
            <Field label="CFG" hint="1.0–15.0">
              <Input type="number" min={1} max={15} step={0.5} value={Number(draft.default_cfg ?? 7.5)}
                onChange={(e) => set("default_cfg", Math.min(15, Math.max(1, Number(e.target.value) || 7.5)))} />
            </Field>
            <Field label="Sampler">
              <Select value={String(draft.default_sampler ?? "dpmpp_2m")}
                onChange={(e) => set("default_sampler", e.target.value)}>
                {["dpmpp_2m", "euler", "euler_ancestral", "dpmpp_sde", "uni_pc"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </Select>
            </Field>
            <Field label="Scheduler">
              <Select value={String(draft.default_scheduler ?? "karras")}
                onChange={(e) => set("default_scheduler", e.target.value)}>
                {["karras", "normal", "exponential", "sgm_uniform"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </Select>
            </Field>
            <Field label="Aspect ratio">
              <Select value={String(draft.default_aspect_ratio ?? "16:9")}
                onChange={(e) => set("default_aspect_ratio", e.target.value)}>
                {["16:9", "1:1", "9:16"].map((a) => <option key={a} value={a}>{a}</option>)}
              </Select>
            </Field>
            <Field label="Generation mode">
              <Select value={String(draft.default_generation_mode ?? "auto")}
                onChange={(e) => set("default_generation_mode", e.target.value)}>
                <option value="auto">auto</option>
                <option value="native_long">native_long</option>
                <option value="multi_shot">multi_shot</option>
              </Select>
            </Field>
            <Field label="Export fps">
              <Select value={String(draft.default_export_fps ?? 8)}
                onChange={(e) => set("default_export_fps", Number(e.target.value))}>
                {[8, 16, 24].map((f) => (
                  <option key={f} value={String(f)}>{f} fps{f === 8 ? " (native)" : " (interpolated)"}</option>
                ))}
              </Select>
            </Field>
            <Field label="Interpolation">
              <Select value={String(draft.default_interpolation ?? "none")}
                onChange={(e) => set("default_interpolation", e.target.value)}>
                <option value="none">none</option>
                <option value="minterpolate">minterpolate (FFmpeg)</option>
                <option value="rife">rife (optional node pack)</option>
              </Select>
            </Field>
          </div>

          <div className="mt-4 flex flex-col gap-3">
            <Toggle checked={Boolean(draft.default_upscale_export)}
              onChange={(v) => set("default_upscale_export", v)}
              label="Upscale exports ×2 (Lanczos) by default"
              description="Conventional resize — not AI super-resolution." />
            <Toggle checked={draft.random_seed_default !== false}
              onChange={(v) => set("random_seed_default", v)}
              label="Random seed by default"
              description="Off = reuse the last seed unless you type one (reproducible runs)." />
            <Toggle checked={draft.oom_auto_downgrade_once !== false}
              onChange={(v) => set("oom_auto_downgrade_once", v)}
              label="On CUDA out-of-memory: retry ONCE at lower memory"
              description="One automatic downgrade attempt (multi-shot route + smaller context), then a clean FAILED state with recovery advice. Never an infinite OOM retry loop." />
          </div>
        </Card>

        <div className="flex flex-col gap-5">
          <Card title={<span className="flex items-center gap-2"><ShieldCheck size={14} className="text-ok" /> Security & privacy (fixed by design)</span>}>
            <ul className="flex flex-col gap-2.5 text-[11.5px] leading-relaxed text-muted">
              <li className="flex items-start gap-2">
                <Lock size={12} className="mt-0.5 shrink-0 text-ok" />
                <span>Backend and engine bind to <code className="font-mono text-txt">127.0.0.1</code> only — unreachable from your network.</span>
              </li>
              <li className="flex items-start gap-2">
                <Lock size={12} className="mt-0.5 shrink-0 text-ok" />
                <span>No telemetry, analytics or tracking of any kind — FastAPI instrumentation is explicitly disabled at startup.</span>
              </li>
              <li className="flex items-start gap-2">
                <Lock size={12} className="mt-0.5 shrink-0 text-ok" />
                <span>No accounts, no cloud APIs, no paid services. After the one-time model download the app works fully offline.</span>
              </li>
              <li className="flex items-start gap-2">
                <Lock size={12} className="mt-0.5 shrink-0 text-ok" />
                <span>File access is path-traversal protected; subprocesses use argument arrays (no shell); user text is never evaluated.</span>
              </li>
              <li className="flex items-start gap-2">
                <Lock size={12} className="mt-0.5 shrink-0 text-ok" />
                <span>Sequential jobs only; memory is released after every job. Your videos and weights are never auto-deleted.</span>
              </li>
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge tone="ok">localhost only</Badge>
              <Badge tone="ok">telemetry: off</Badge>
              <Badge tone="ok">offline capable</Badge>
              <Badge tone="neutral">no demo mode</Badge>
            </div>
          </Card>

          <Card title="Ports">
            <div className="flex flex-col gap-1.5 font-mono text-[11px] text-muted">
              <span>backend + this UI → http://127.0.0.1:8317</span>
              <span>ComfyUI engine&nbsp;&nbsp;→ http://127.0.0.1:8188</span>
            </div>
            <p className="mt-2 text-[10.5px] leading-relaxed text-faint">
              Ports are fixed by the launcher scripts to keep the loopback-only promise simple
              and firewall-friendly. They are intentionally not editable from the browser.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}

/** Prompt editor: positive/negative prompts, char counters, examples,
 *  style presets, deterministic local enhancer (never silent), seed control. */

import { useMemo, useState } from "react";
import {
  BookOpen, Dice5, Eraser, Lock, Sparkles, Wand2,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useToasts } from "../hooks/useToasts";
import type { PresetsResponse } from "../lib/types";
import { Badge, Button, Input, Label, Select, Textarea } from "./ui";

const POSITIVE_MAX = 2000;
const NEGATIVE_MAX = 1000;

export interface PromptState {
  prompt: string;
  negativePrompt: string;
  stylePreset: string | null;
  seed: number | null;
  randomSeed: boolean;
}

export function PromptEditor({ state, onChange, presets, busy }: {
  state: PromptState;
  onChange: (patch: Partial<PromptState>) => void;
  presets: PresetsResponse | null;
  busy: boolean;
}) {
  const { push } = useToasts();
  const [enhancing, setEnhancing] = useState(false);
  const [enhanced, setEnhanced] = useState<{ text: string; explanation: string } | null>(null);
  const [showExamples, setShowExamples] = useState(false);

  const preset = useMemo(
    () => presets?.presets.find((p) => p.id === state.stylePreset) ?? null,
    [presets, state.stylePreset],
  );

  const doEnhance = async () => {
    if (!state.prompt.trim()) {
      push("warning", "Write a prompt first", "The enhancer extends your own words — it never writes from nothing.");
      return;
    }
    setEnhancing(true);
    try {
      const r = await api.enhance(state.prompt, state.stylePreset);
      setEnhanced({ text: r.enhanced_prompt, explanation: r.explanation });
    } catch (e) {
      push("error", "Enhancement failed", e instanceof ApiError ? e.message : String(e));
    } finally {
      setEnhancing(false);
    }
  };

  const applyEnhanced = () => {
    if (enhanced) {
      onChange({ prompt: enhanced.text });
      setEnhanced(null);
      push("success", "Enhanced prompt applied", "Your edit is reversible — the original wording was kept at the start.");
    }
  };

  const rollSeed = () => onChange({ seed: Math.floor(Math.random() * 2 ** 31), randomSeed: false });

  const promptTooLong = state.prompt.length > POSITIVE_MAX;
  const negativeTooLong = state.negativePrompt.length > NEGATIVE_MAX;

  return (
    <div className="flex flex-col gap-4">
      {/* positive prompt */}
      <div>
        <Label htmlFor="prompt" hint={`${state.prompt.length} / ${POSITIVE_MAX}`}>
          Prompt
        </Label>
        <Textarea
          id="prompt" rows={5} maxLength={POSITIVE_MAX + 200}
          placeholder="Describe the video you want… e.g. “A photorealistic cinematic shot of a massive wave crashing into a rocky coastline at sunset, realistic water physics, natural atmospheric haze, smooth camera movement.”"
          value={state.prompt}
          disabled={busy}
          onChange={(e) => onChange({ prompt: e.target.value })}
          className={promptTooLong ? "border-danger/60" : ""}
          aria-invalid={promptTooLong}
        />
        {promptTooLong && (
          <p className="mt-1 text-xs text-danger" role="alert">
            Prompt exceeds {POSITIVE_MAX} characters — the backend will reject it.
          </p>
        )}
      </div>

      {/* quick tools row */}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="accent-soft" onClick={doEnhance} disabled={busy || enhancing}
          title="Deterministic local template enhancement — no external AI service is ever called">
          {enhancing ? <Sparkles size={14} className="animate-pulse-slow" /> : <Wand2 size={14} />}
          Enhance prompt
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setShowExamples((v) => !v)}
          aria-expanded={showExamples}>
          <BookOpen size={14} /> Examples
        </Button>
        <Button size="sm" variant="ghost" disabled={busy || !state.prompt}
          onClick={() => { onChange({ prompt: "" }); setEnhanced(null); }}
          title="Clear the prompt">
          <Eraser size={14} /> Clear
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={rollSeed} disabled={busy} title="Roll a new seed">
            <Dice5 size={14} /> Seed
          </Button>
          <Input
            type="number" min={0} max={2 ** 63 - 1} aria-label="Seed"
            className="h-8 w-32" placeholder="random"
            value={state.randomSeed ? "" : (state.seed ?? "")}
            disabled={busy || state.randomSeed}
            onChange={(e) => onChange({
              seed: e.target.value === "" ? null : Number(e.target.value),
              randomSeed: e.target.value === "",
            })}
          />
          <label className="flex items-center gap-1.5 text-xs text-muted" title="Use a fresh random seed for every generation">
            <input type="checkbox" checked={state.randomSeed} disabled={busy}
              onChange={(e) => onChange({ randomSeed: e.target.checked, seed: e.target.checked ? null : state.seed })}
              className="h-3.5 w-3.5 accent-[#4f8dff]" />
            <Lock size={11} className={state.randomSeed ? "hidden" : "inline text-accent"} />
            Random
          </label>
        </div>
      </div>

      {/* enhancement result — explicit apply, never silent */}
      {enhanced && (
        <div className="rounded-xl border border-violet/30 bg-violet-soft/50 p-3.5" role="region"
          aria-label="Enhancement preview">
          <div className="mb-1.5 flex items-center gap-2">
            <Badge tone="violet"><Sparkles size={10} /> Local template enhancer</Badge>
            <span className="text-[11px] text-faint">nothing was replaced automatically</span>
          </div>
          <p className="mb-2 max-h-24 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-muted">
            {enhanced.text}
          </p>
          <p className="mb-3 text-[11px] leading-relaxed text-faint">{enhanced.explanation}</p>
          <div className="flex gap-2">
            <Button size="sm" variant="primary" onClick={applyEnhanced}>Apply enhanced prompt</Button>
            <Button size="sm" variant="ghost" onClick={() => setEnhanced(null)}>Discard</Button>
          </div>
        </div>
      )}

      {/* examples drawer */}
      {showExamples && presets && (
        <div className="rounded-xl border border-line bg-ink-900 p-2" role="region" aria-label="Example prompts">
          <ul className="flex flex-col gap-1">
            {presets.examples.map((ex) => (
              <li key={ex.slice(0, 40)}>
                <button
                  className="focus-ring w-full rounded-lg px-3 py-2 text-left text-xs leading-relaxed text-muted hover:bg-ink-800 hover:text-txt"
                  onClick={() => { onChange({ prompt: ex }); setShowExamples(false); }}
                  disabled={busy}
                >
                  {ex}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* style presets */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="style-preset" hint="prompt suggestions, not trained models">Style preset</Label>
          <Select id="style-preset" value={state.stylePreset ?? ""} disabled={busy}
            onChange={(e) => {
              const id = e.target.value || null;
              onChange({ stylePreset: id });
              setEnhanced(null);
            }}>
            <option value="">— none —</option>
            {presets?.presets.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </Select>
          {preset && (
            <p className="mt-1.5 text-[11px] leading-relaxed text-faint">{preset.description}</p>
          )}
          {preset && (
            <Button size="sm" variant="ghost" className="mt-1.5" disabled={busy}
              onClick={() => onChange({
                prompt: state.prompt.trim()
                  ? `${state.prompt.trim().replace(/,\s*$/, "")}, ${preset.positive_suffix}`
                  : preset.positive_suffix,
              })}
              title="Append the preset's descriptive tokens to your prompt">
              Append preset tokens
            </Button>
          )}
        </div>
        <div>
          <Label htmlFor="negative-prompt" hint={`${state.negativePrompt.length} / ${NEGATIVE_MAX}`}>
            Negative prompt
          </Label>
          <Textarea id="negative-prompt" rows={3} maxLength={NEGATIVE_MAX + 100}
            placeholder="what to avoid — e.g. blurry, watermark, static image"
            value={state.negativePrompt} disabled={busy}
            onChange={(e) => onChange({ negativePrompt: e.target.value })}
            className={negativeTooLong ? "border-danger/60" : ""}
          />
        </div>
      </div>
    </div>
  );
}

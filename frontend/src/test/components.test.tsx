/** Component-level tests: honest labeling, stage rendering, prompt enhance
 *  flow (apply/discard), UI primitives. */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../lib/api";
import type { EffectiveSettings, GenerationJob, PreflightResult, VideoOut } from "../lib/types";
import { Badge, Button, ProgressBar } from "../components/ui";
import { PromptEditor } from "../components/PromptEditor";
import { EffectiveSummary } from "../components/GenerationSettings";
import { ProvenanceBadges } from "../components/VideoCard";
import { ProgressPanel } from "../components/ProgressPanel";
import { ToastProvider } from "../hooks/useToasts";
import { Toaster } from "../components/Toaster";

function makeJob(overrides: Partial<GenerationJob> = {}): GenerationJob {
  return {
    id: "job-1", status: "GENERATING", stage_detail: "Sampling step 4/16 (segment 1/4)",
    progress: 0.25, original_prompt: "a wave", negative_prompt: "", seed: 7,
    model_id: "animatediff-sd15", workflow_id: "animatediff_t2v",
    generation_mode: "multi_shot",
    effective_settings: { interpolation: "none", export_fps: 8 },
    error: null, output: null, metrics: {},
    created_at: null, started_at: null, completed_at: null,
    ...overrides,
  };
}

const EFFECTIVE: EffectiveSettings = {
  width: 640, height: 360, resolution_id: "wide_640", source_fps: 8,
  total_frames: 64, segments: 4, frames_per_segment: 16, context_length: 16,
  route: "multi_shot",
  route_label: "4 independently sampled 2-second segments joined into one 8-second export.",
  export_fps: 16, interpolation: "minterpolate", upscale_export: true,
  upscale_factor: 2, final_width: 1280, final_height: 720,
  estimated_output_size_mb: 1.44, estimated_minutes_low: 3.2, estimated_minutes_high: 8.1,
};

function makeVideo(overrides: Partial<VideoOut> = {}): VideoOut {
  return {
    video_id: "v1", generation_id: "g1", status: "COMPLETED", file_exists: true,
    prompt: "p", negative_prompt: "", seed: 1, model_id: "animatediff-sd15",
    generation_mode: "native_long", route_label: null, duration_seconds: 8,
    width: 640, height: 360, fps: 8, size_bytes: 1234, codec: "h264",
    interpolated: false, upscaled: false, created_at: "2026-10-29T10:00:00",
    file_url: "/api/videos/v1/file", thumbnail_url: "/api/videos/v1/thumbnail",
    ...overrides,
  };
}

describe("UI primitives", () => {
  it("Button respects disabled and fires click", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    await user.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    render(<Button disabled>No</Button>);
    expect(screen.getByRole("button", { name: "No" })).toBeDisabled();
  });

  it("ProgressBar exposes value to assistive tech and clamps", () => {
    const { rerender } = render(<ProgressBar value={42} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
    rerender(<ProgressBar value={140} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("Badge renders its label", () => {
    render(<Badge tone="ok">validated</Badge>);
    expect(screen.getByText("validated")).toBeInTheDocument();
  });
});

describe("ProvenanceBadges — honest labels", () => {
  it("labels native 8 fps output as native", () => {
    render(<ProvenanceBadges v={makeVideo()} small />);
    expect(screen.getByText("8 fps native")).toBeInTheDocument();
    expect(screen.queryByText(/interpolated/)).not.toBeInTheDocument();
    expect(screen.queryByText(/upscaled/)).not.toBeInTheDocument();
  });

  it("labels interpolated + upscaled + multi-shot truthfully", () => {
    render(<ProvenanceBadges v={makeVideo({
      interpolated: true, fps: 16, upscaled: true,
      generation_mode: "multi_shot", route_label: "4 segments",
    })} small />);
    expect(screen.getByText("16 fps interpolated")).toBeInTheDocument();
    expect(screen.getByText("upscaled ×2")).toBeInTheDocument();
    expect(screen.getByText("multi-shot")).toBeInTheDocument();
  });
});

describe("EffectiveSummary", () => {
  it("renders the server-computed route, final size and estimates", () => {
    render(<EffectiveSummary effective={EFFECTIVE} preflight={null} />);
    expect(screen.getByText("1280×720 px (lanczos ×2)")).toBeInTheDocument();
    expect(screen.getByText("64 source frames")).toBeInTheDocument();
    expect(screen.getByText(/4 segments × 16f/)).toBeInTheDocument();
    expect(screen.getByText(EFFECTIVE.route_label)).toBeInTheDocument();
    expect(screen.getByText(/est\. 3\.2–8\.1 min/)).toBeInTheDocument();
  });

  it("shows preflight blockers prominently", () => {
    const pf: PreflightResult = {
      ok: false, level: "BLOCKED", checks: [], warnings: ["disk almost full"],
      blockers: ["Engine is offline."], effective: EFFECTIVE,
    };
    render(<EffectiveSummary effective={EFFECTIVE} preflight={pf} />);
    expect(screen.getByText("Engine is offline.")).toBeInTheDocument();
    expect(screen.getByText("disk almost full")).toBeInTheDocument();
  });

  it("shows guidance when nothing is selected", () => {
    render(<EffectiveSummary effective={null} preflight={null} />);
    expect(screen.getByText(/Select a model and settings/)).toBeInTheDocument();
  });
});

describe("ProgressPanel — stage rendering from real status", () => {
  const noop = { etaSeconds: null, wsConnected: true, cancelRequested: false, cancelling: false };

  it("marks passed stages completed and the current one running", () => {
    render(<ProgressPanel job={makeJob()} {...noop} />);
    expect(screen.getByText("Generating frames (AI inference)")).toBeInTheDocument();
    expect(screen.getByText("Pre-flight checks")).toBeInTheDocument();
    expect(screen.getByText("Initializing engine")).toBeInTheDocument();
    // live sampler detail from the backend is shown verbatim
    expect(screen.getByText("Sampling step 4/16 (segment 1/4)")).toBeInTheDocument();
    expect(screen.getByText("Generating")).toBeInTheDocument(); // status badge
  });

  it("skips INTERPOLATING when the export is native fps", () => {
    render(<ProgressPanel job={makeJob({ status: "ASSEMBLING", effective_settings: { interpolation: "none" } })} {...noop} />);
    expect(screen.getByText("(not needed — native fps)")).toBeInTheDocument();
  });

  it("shows the real error with recovery hint on FAILED", () => {
    render(<ProgressPanel job={makeJob({
      status: "FAILED",
      error: { code: "CUDA_OOM", summary: "GPU ran out of memory.", recovery: "Retry at 640×360.", retryable: true },
    })} {...noop} />);
    expect(screen.getByText(/CUDA_OOM/)).toBeInTheDocument();
    expect(screen.getByText("Retry at 640×360.")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("shows validated output facts on COMPLETED", () => {
    render(<ProgressPanel job={makeJob({
      status: "COMPLETED", progress: 1,
      output: makeVideo({ duration_seconds: 8, fps: 8 }),
    })} {...noop} />);
    expect(screen.getByText(/Validated:/)).toBeInTheDocument();
    expect(screen.getByText(/8\.000 s/)).toBeInTheDocument();
  });

  it("cancel button says 'requested' while cooperative cancellation is in flight", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ProgressPanel job={makeJob()} {...noop} cancelRequested onCancel={onCancel} />);
    expect(screen.getByText("Cancel requested")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cancel requested…/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Cancel requested…/ })).catch(() => {});
    expect(onCancel).not.toHaveBeenCalled();
  });
});

describe("PromptEditor enhance flow", () => {
  const base = {
    presets: {
      presets: [{ id: "cinematic", name: "Cinematic", description: "d", positive_suffix: "s, t", negative_extra: "n" }],
      examples: ["An example prompt."],
      default_negative_prompt: "blurry",
    },
    busy: false,
  };

  it("never applies enhancements silently — Apply/Discard are explicit", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(api, "enhance").mockResolvedValue({
      enhanced_prompt: "a wave, cinematic lighting",
      method: "template",
      explanation: "Appended cinematic tokens; your words were kept verbatim.",
      original_preserved: true,
    });
    const onChange = vi.fn();
    render(
      <ToastProvider>
        <PromptEditor
          state={{ prompt: "a wave", negativePrompt: "", stylePreset: null, seed: null, randomSeed: true }}
          onChange={onChange} presets={base.presets} busy={false} />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: /Enhance prompt/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("a wave", null));
    // preview visible, original untouched
    expect(screen.getByText("a wave, cinematic lighting")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ prompt: "a wave, cinematic lighting" }));
    // explicit apply
    await user.click(screen.getByRole("button", { name: /Apply enhanced prompt/ }));
    expect(onChange).toHaveBeenCalledWith({ prompt: "a wave, cinematic lighting" });
  });

  it("Discard throws the suggestion away", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "enhance").mockResolvedValue({
      enhanced_prompt: "x, y", method: "template", explanation: "e", original_preserved: true,
    });
    const onChange = vi.fn();
    render(
      <ToastProvider>
        <PromptEditor
          state={{ prompt: "x", negativePrompt: "", stylePreset: null, seed: null, randomSeed: true }}
          onChange={onChange} presets={base.presets} busy={false} />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: /Enhance prompt/ }));
    await screen.findByText("x, y");
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.queryByText("x, y")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("refuses to enhance an empty prompt with a visible warning toast", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(api, "enhance");
    render(
      <ToastProvider>
        <PromptEditor
          state={{ prompt: "  ", negativePrompt: "", stylePreset: null, seed: null, randomSeed: true }}
          onChange={vi.fn()} presets={base.presets} busy={false} />
        <Toaster />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: /Enhance prompt/ }));
    expect(spy).not.toHaveBeenCalled();
    expect(await screen.findByText(/Write a prompt first/)).toBeInTheDocument();
  });
});

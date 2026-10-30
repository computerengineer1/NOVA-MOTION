/** Typed API client. Same-origin only (the backend serves this SPA).
 *  No external endpoints exist in this file — by design. */

import type {
  AppSettings, DiagnosticReport, EnhanceResponse, GenerationJob,
  GenerationRequestPayload, InstallStatus, ModelProfile, PreflightResult,
  PresetsResponse, SystemReport, VideoOut, EngineStatus,
} from "./types";

export class ApiError extends Error {
  code: string;
  recovery?: string | null;
  retryable: boolean;
  status: number;

  constructor(status: number, code: string, summary: string,
              recovery?: string | null, retryable = false) {
    super(summary);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.recovery = recovery;
    this.retryable = retryable;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the NOVA MOTION backend. Is Start-Studio running?");
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try { body = JSON.parse(text); } catch { body = null; }
  }
  if (!response.ok) {
    const err = (body as { error?: { code?: string; summary?: string; recovery?: string; retryable?: boolean } } | null)?.error;
    throw new ApiError(
      response.status,
      err?.code ?? `HTTP_${response.status}`,
      err?.summary ?? `Request failed (HTTP ${response.status}).`,
      err?.recovery,
      err?.retryable ?? false,
    );
  }
  return body as T;
}

export const api = {
  // system
  health: () => request<{ status: string; version: string }>("/api/health"),
  system: () => request<SystemReport>("/api/system"),
  readiness: () => request<{ level: string; reasons: string[]; warnings: string[] }>("/api/system/readiness"),

  // engine
  engineStatus: (force = false) => request<EngineStatus>(`/api/engine/status?force=${force}`),
  engineRestart: () => request<EngineStatus>("/api/engine/restart", { method: "POST" }),
  engineFree: () => request<{ ok: boolean; detail?: string }>("/api/engine/free", { method: "POST" }),
  engineCapabilities: () =>
    request<{ engine_online: boolean; rife_available: boolean }>("/api/engine/capabilities"),

  // models
  models: () => request<ModelProfile[]>("/api/models"),
  installedModels: () => request<ModelProfile[]>("/api/models/installed"),
  installModel: (modelId: string, acceptLicense: boolean) =>
    request<InstallStatus>("/api/models/install", {
      method: "POST",
      body: JSON.stringify({ model_id: modelId, accept_license: acceptLicense }),
    }),
  installStatus: (modelId: string) =>
    request<InstallStatus>(`/api/models/install/${encodeURIComponent(modelId)}/status`),
  cancelInstall: (modelId: string) =>
    request<InstallStatus>(`/api/models/install/${encodeURIComponent(modelId)}/cancel`, { method: "POST" }),
  validateModel: (modelId: string) =>
    request<{ model_id: string; valid: boolean; files: unknown[]; note: string | null }>(
      `/api/models/validate?model_id=${encodeURIComponent(modelId)}`, { method: "POST" }),
  deleteModel: (modelId: string) =>
    request<{ model_id: string; deleted_files: string[] }>(
      `/api/models/${encodeURIComponent(modelId)}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm_model_id: modelId }),
      }),

  // generations
  submitGeneration: (payload: GenerationRequestPayload) =>
    request<GenerationJob>("/api/generations", { method: "POST", body: JSON.stringify(payload) }),
  generations: (limit = 50) => request<GenerationJob[]>(`/api/generations?limit=${limit}`),
  generation: (id: string) => request<GenerationJob>(`/api/generations/${encodeURIComponent(id)}`),
  cancelGeneration: (id: string) =>
    request<{ id: string; status: string; cancel_requested: boolean; detail: string }>(
      `/api/generations/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  preflight: (payload: GenerationRequestPayload) =>
    request<PreflightResult>("/api/generations/preflight", { method: "POST", body: JSON.stringify(payload) }),
  presets: () => request<PresetsResponse>("/api/generations/meta/presets"),
  enhance: (prompt: string, stylePreset: string | null) =>
    request<EnhanceResponse>("/api/generations/meta/enhance", {
      method: "POST",
      body: JSON.stringify({ prompt, style_preset: stylePreset }),
    }),

  // videos
  videos: (params?: { q?: string; modelId?: string; sort?: string }) => {
    const qs = new URLSearchParams();
    if (params?.q) qs.set("q", params.q);
    if (params?.modelId) qs.set("model_id", params.modelId);
    if (params?.sort) qs.set("sort", params.sort);
    const s = qs.toString();
    return request<VideoOut[]>(`/api/videos${s ? `?${s}` : ""}`);
  },
  video: (id: string) => request<VideoOut>(`/api/videos/${encodeURIComponent(id)}`),
  deleteVideo: (id: string) =>
    request<{ ok: boolean; detail?: string }>(`/api/videos/${encodeURIComponent(id)}`, { method: "DELETE" }),
  revealVideo: (id: string) =>
    request<{ ok: boolean; detail?: string }>(`/api/videos/${encodeURIComponent(id)}/reveal`, { method: "POST" }),
  openOutputsFolder: () =>
    request<{ ok: boolean; detail?: string }>("/api/videos/folder/open", { method: "POST" }),

  // settings
  getSettings: () => request<AppSettings>("/api/settings"),
  patchSettings: (values: AppSettings) =>
    request<AppSettings>("/api/settings", { method: "PATCH", body: JSON.stringify({ values }) }),

  // logs / diagnostics
  appLogs: (lines = 200) => request<{ path: string; lines: string[] }>(`/api/logs/app?lines=${lines}`),
  engineLogs: (lines = 200) => request<{ path: string; lines: string[] }>(`/api/logs/engine?lines=${lines}`),
  diagnostic: () => request<DiagnosticReport>("/api/logs/diagnostic"),
};

export function videoFileUrl(id: string): string {
  return `/api/videos/${encodeURIComponent(id)}/file`;
}
export function thumbnailUrl(id: string): string {
  return `/api/videos/${encodeURIComponent(id)}/thumbnail`;
}

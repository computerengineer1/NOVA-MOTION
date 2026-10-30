/** Typed API contracts — mirrors the backend Pydantic schemas exactly. */

export type ReadinessLevel = "READY" | "WARNING" | "NOT_READY";

export type JobStatus =
  | "QUEUED" | "PREFLIGHT" | "INITIALIZING" | "GENERATING" | "ASSEMBLING"
  | "INTERPOLATING" | "ENCODING" | "VALIDATING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface ErrorInfo {
  code: string;
  summary: string;
  recovery?: string | null;
  retryable?: boolean;
  log_reference?: string | null;
}

export interface OsInfo { system: string | null; release: string | null; version: string | null; machine: string | null; }
export interface CpuInfo { name: string | null; physical_cores: number | null; logical_cores: number | null; available: boolean; }
export interface MemoryInfo { total_gb: number | null; available_gb: number | null; used_percent: number | null; available: boolean; }
export interface GpuInfo {
  name: string | null; driver_version: string | null;
  vram_total_mb: number | null; vram_free_mb: number | null; vram_used_mb: number | null;
  utilization_percent: number | null; temperature_c: number | null;
  compute_capability: string | null; source: string | null;
  available: boolean; cuda_available: boolean | null;
}
export interface DiskInfo { path: string; total_gb: number | null; free_gb: number | null; available: boolean; }

export interface EngineStatus {
  online: boolean;
  managed_process_running: boolean;
  base_url: string | null;
  comfyui_version: string | null;
  torch_version: string | null;
  devices: Array<Record<string, unknown>>;
  queue_remaining: number | null;
  last_error: string | null;
  checked_at: string | null;
}

export interface ReadinessVerdict { level: ReadinessLevel; reasons: string[]; warnings: string[]; }

export interface QueueState { running_job_id: string | null; queued: number; max_queue_length: number; }

export interface SystemReport {
  generated_at: string;
  os: OsInfo;
  cpu: CpuInfo;
  memory: MemoryInfo;
  gpu: GpuInfo | null;
  gpus: GpuInfo[];
  disks: DiskInfo[];
  python_version: string;
  backend_version: string;
  engine: EngineStatus;
  ffmpeg: { available: boolean; ffmpeg_path: string | null; ffprobe_path: string | null; version: string | null; hint: string | null };
  installed_models: string[];
  queue: QueueState;
  readiness: ReadinessVerdict;
}

export interface ResolutionOption {
  id: string; width: number; height: number; aspect: string;
  default?: boolean; high_vram_risk?: boolean; note?: string;
}

export interface ModelFileState {
  id: string; dest: string; size_bytes: number; url: string;
  sha256: string | null; required: boolean;
  installed: boolean; actual_size_bytes: number | null; checksum_ok: boolean | null;
}

export interface CompatibilityCheck { name: string; ok: boolean | null; message: string; }

export interface ModelProfile {
  model_id: string;
  name: string;
  model_type: string;
  adapter: string;
  status: "recommended" | "supported" | "experimental" | "incompatible";
  license_id: string;
  license_url: string | null;
  source: string;
  version: string | null;
  total_download_bytes: number;
  installed: boolean;
  install_progress: number | null;
  validation_status: string;
  validation_note: string | null;
  compatibility: { installable: boolean; checks: CompatibilityCheck[] };
  capabilities: {
    resolutions?: ResolutionOption[];
    source_fps?: number;
    max_total_frames?: number;
    durations_s?: number[];
    modes?: string[];
    interpolation_methods?: string[];
    image_to_video?: boolean;
    memory_notes?: string | null;
    quality_notes?: string | null;
    incompatible_reason?: string | null;
    upscale_export_targets?: Array<Record<string, unknown>>;
  };
  memory_notes: string | null;
  files: ModelFileState[];
  last_validated_at: string | null;
}

export interface InstallStatus {
  model_id: string;
  state: "idle" | "starting" | "downloading" | "verifying" | "completed" | "failed" | "cancelled";
  current_file: string | null;
  file_index: number;
  file_count: number;
  bytes_done: number;
  bytes_total: number;
  percent: number;
  error: ErrorInfo | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface EffectiveSettings {
  width: number; height: number; resolution_id: string;
  source_fps: number; total_frames: number;
  segments: number; frames_per_segment: number; context_length: number;
  route: "native_long" | "multi_shot";
  route_label: string;
  export_fps: number;
  interpolation: string;
  upscale_export: boolean;
  upscale_factor: number;
  final_width: number; final_height: number;
  estimated_output_size_mb: number | null;
  estimated_minutes_low: number | null;
  estimated_minutes_high: number | null;
}

export interface VideoOut {
  video_id: string;
  generation_id: string;
  status: string;
  file_exists: boolean;
  prompt: string;
  negative_prompt: string;
  seed: number | null;
  model_id: string;
  generation_mode: string;
  route_label: string | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  size_bytes: number | null;
  codec: string | null;
  interpolated: boolean;
  upscaled: boolean;
  created_at: string | null;
  file_url: string | null;
  thumbnail_url: string | null;
}

export interface GenerationJob {
  id: string;
  status: JobStatus;
  stage_detail: string | null;
  progress: number;
  original_prompt: string;
  negative_prompt: string;
  seed: number | null;
  model_id: string;
  workflow_id: string;
  generation_mode: string;
  effective_settings: Partial<EffectiveSettings>;
  request?: Partial<GenerationRequestPayload>;
  error: ErrorInfo | null;
  output: VideoOut | null;
  metrics: Record<string, number | boolean | null>;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface GenerationRequestPayload {
  prompt: string;
  negative_prompt: string;
  model_id: string;
  duration_seconds: number;
  aspect_ratio: "16:9" | "9:16" | "1:1";
  resolution_id?: string | null;
  steps: number;
  cfg: number;
  sampler: string;
  scheduler: string;
  seed?: number | null;
  random_seed: boolean;
  generation_mode: "auto" | "native_long" | "multi_shot";
  export_fps: 8 | 16 | 24;
  interpolation: "none" | "minterpolate" | "rife";
  upscale_export: boolean;
}

export interface PreflightResult {
  ok: boolean;
  level: "READY" | "WARNING" | "BLOCKED";
  checks: Array<{ name: string; ok: boolean | null; blocking: boolean; message: string }>;
  warnings: string[];
  blockers: string[];
  effective?: EffectiveSettings | null;
}

export interface StylePreset {
  id: string; name: string; description: string;
  positive_suffix: string; negative_extra: string;
}

export interface PresetsResponse {
  presets: StylePreset[];
  examples: string[];
  default_negative_prompt: string;
}

export interface EnhanceResponse {
  enhanced_prompt: string;
  method: "template";
  explanation: string;
  original_preserved: boolean;
}

export type AppSettings = Record<string, string | number | boolean>;

export interface DiagnosticReport {
  generated_at: string;
  backend_version: string;
  system: SystemReport;
  recent_generations: Array<Record<string, unknown>>;
  app_log_tail: string[];
  engine_log_tail: string[];
  note: string;
}

/** WS event shapes published by the backend ProgressManager. */
export interface ProgressEvent {
  type: "hello" | "snapshot" | "job_stage" | "job_progress" | "job_queued"
      | "job_failed" | "job_cancelled" | "queue_update" | "install_progress"
      | "job_db_warning";
  ts?: number;
  job_id?: string;
  model_id?: string;
  status?: string;
  progress?: number;
  stage_detail?: string;
  eta_seconds?: number | null;
  error?: ErrorInfo;
  message?: string;
  queue?: QueueState;
  active_jobs?: Array<{ job_id: string; status: string; progress: number; stage_detail: string | null }>;
  recent?: ProgressEvent[];
  /* install_progress fields */
  state?: string;
  percent?: number;
  bytes_done?: number;
  bytes_total?: number;
  current_file?: string | null;
  file_index?: number;
  file_count?: number;
}

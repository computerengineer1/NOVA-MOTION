/** Shared hooks: system status polling, job progress (WS + REST merge),
 *  model install progress, notifications. */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { getProgressSocket } from "../lib/ws";
import { isTerminal } from "../lib/format";
import type { GenerationJob, ProgressEvent, SystemReport } from "../lib/types";

/** Polls /api/system. Degrades to null (UI shows "backend unreachable"). */
export function useSystemReport(intervalMs = 5000) {
  const [report, setReport] = useState<SystemReport | null>(null);
  const [backendOnline, setBackendOnline] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (force = false) => {
    try {
      const r = await api.system();
      setReport(r);
      setBackendOnline(true);
      setError(null);
    } catch (e) {
      setBackendOnline(false);
      setError(e instanceof ApiError ? e.message : String(e));
      if (force) setReport(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), intervalMs);
    return () => window.clearInterval(t);
  }, [refresh, intervalMs]);

  return { report, backendOnline, error, refresh: () => refresh(true) };
}

export interface JobProgressView {
  job: GenerationJob | null;
  loading: boolean;
  error: string | null;
  etaSeconds: number | null;
  wsConnected: boolean;
  refresh: () => Promise<void>;
}

/** Tracks one generation job. REST polling is the source of truth;
 *  WS events accelerate updates and provide step-level detail + honest ETA. */
export function useJobProgress(jobId: string | null, pollMs = 2000): JobProgressView {
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [liveDetail, setLiveDetail] = useState<{ detail?: string; progress?: number }>({});
  const jobRef = useRef(jobId);
  jobRef.current = jobId;

  const fetchJob = useCallback(async () => {
    if (!jobRef.current) return;
    setLoading(true);
    try {
      const g = await api.generation(jobRef.current);
      setJob(g);
      setError(null);
      if (isTerminal(g.status)) setEtaSeconds(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setJob(null);
        setError("This generation is not known to the backend (it may predate a database reset).");
      } else {
        setError(e instanceof ApiError ? e.message : String(e));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setJob(null);
    setEtaSeconds(null);
    setLiveDetail({});
    if (!jobId) return;
    void fetchJob();
  }, [jobId, fetchJob]);

  // REST polling — stops for terminal jobs
  useEffect(() => {
    if (!jobId) return;
    if (job && isTerminal(job.status)) return;
    const t = window.setInterval(() => void fetchJob(), pollMs);
    return () => window.clearInterval(t);
  }, [jobId, job?.status, pollMs, fetchJob]);

  // WS acceleration
  useEffect(() => {
    const socket = getProgressSocket();
    const offStatus = socket.onStatusChange(setWsConnected);
    const off = socket.subscribe((event: ProgressEvent) => {
      if (event.type === "snapshot") {
        const active = event.active_jobs?.find((j) => j.job_id === jobRef.current);
        if (active) {
          setLiveDetail({ detail: active.stage_detail ?? undefined, progress: active.progress });
        }
        return;
      }
      if (!event.job_id || event.job_id !== jobRef.current) return;
      if (event.type === "job_progress" || event.type === "job_stage") {
        setLiveDetail({ detail: event.stage_detail, progress: event.progress });
        if (typeof event.eta_seconds === "number") setEtaSeconds(event.eta_seconds);
      }
      if (event.type === "job_stage" && event.status && isTerminal(event.status)) {
        void fetchJob();
      }
      if (event.type === "job_failed" || event.type === "job_cancelled") {
        void fetchJob();
      }
    });
    return () => { off(); offStatus(); };
  }, [fetchJob]);

  // merge live detail into the job view (WS is fresher between polls)
  const merged: GenerationJob | null = job
    ? {
        ...job,
        stage_detail: isTerminal(job.status)
          ? job.stage_detail
          : (liveDetail.detail ?? job.stage_detail),
        progress: isTerminal(job.status)
          ? job.progress
          : Math.max(job.progress, liveDetail.progress ?? 0),
      }
    : null;

  return { job: merged, loading, error, etaSeconds, wsConnected, refresh: fetchJob };
}

/** Tracks install progress for one model via WS events + REST fallback. */
export function useInstallStatus(modelId: string | null, pollMs = 2500) {
  const [percent, setPercent] = useState<number | null>(null);
  const [state, setState] = useState<string>("idle");
  const [currentFile, setCurrentFile] = useState<string | null>(null);
  const idRef = useRef(modelId);
  idRef.current = modelId;

  const poll = useCallback(async () => {
    if (!idRef.current) return;
    try {
      const st = await api.installStatus(idRef.current);
      setState(st.state);
      setPercent(st.percent);
      setCurrentFile(st.current_file);
    } catch {
      /* engine offline etc — leave state as-is */
    }
  }, []);

  useEffect(() => {
    if (!modelId) return;
    void poll();
    const t = window.setInterval(() => void poll(), pollMs);
    const socket = getProgressSocket();
    const off = socket.subscribe((event: ProgressEvent) => {
      if (event.type === "install_progress" && event.model_id === idRef.current) {
        setState(event.state ?? "downloading");
        setPercent(event.percent ?? null);
        setCurrentFile(event.current_file ?? null);
      }
    });
    return () => { window.clearInterval(t); off(); };
  }, [modelId, pollMs, poll]);

  return { percent, state, currentFile, refresh: poll };
}

/** Elapsed timer that starts when `since` becomes non-null. */
export function useElapsedSeconds(since: number | null): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (since == null) return;
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, [since]);
  if (since == null) return 0;
  return Math.max(0, now - since);
}

/** Log viewer: tails backend/engine logs (server-side file reads — no direct
 *  filesystem access from the browser), plus one-click diagnostic bundle. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Cpu, Download, RefreshCw } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useToasts } from "../hooks/useToasts";
import { Badge, Button, Segmented } from "./ui";

export function LogsViewer() {
  const { push } = useToasts();
  const [source, setSource] = useState<"app" | "engine">("app");
  const [lines, setLines] = useState(300);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [content, setContent] = useState<{ path: string; lines: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = source === "app" ? await api.appLogs(lines) : await api.engineLogs(lines);
      setContent(r);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [source, lines]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(t);
  }, [autoRefresh, load]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [content]);

  const downloadDiagnostic = async () => {
    try {
      const report = await api.diagnostic();
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `nova-motion-diagnostic-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
      a.click();
      URL.revokeObjectURL(url);
      push("success", "Diagnostic bundle saved", "It contains system info + log tails — review before sharing; it never leaves your machine automatically.");
    } catch (e) {
      push("error", "Could not build diagnostic bundle", e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          ariaLabel="Log source"
          value={source}
          onChange={(v) => setSource(v)}
          options={[
            { value: "app", label: "Backend log" },
            { value: "engine", label: "ComfyUI engine log" },
          ]}
        />
        <select value={String(lines)} onChange={(e) => setLines(Number(e.target.value))}
          aria-label="Lines to show"
          className="focus-ring h-9 rounded-lg border border-line bg-ink-900 px-2 text-xs text-muted">
          {[100, 300, 1000].map((n) => <option key={n} value={String(n)}>{n} lines</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)}
            className="h-3.5 w-3.5 accent-[#4f8dff]" />
          Auto-refresh (5 s)
        </label>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
          </Button>
          <Button size="sm" variant="secondary" onClick={downloadDiagnostic}>
            <Download size={13} /> Diagnostic bundle
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-warn/30 bg-warn-soft px-3.5 py-2.5 text-xs text-warn" role="alert">
          {error}
        </div>
      )}

      <div className="relative h-[420px] overflow-hidden rounded-xl border border-line bg-ink-950">
        <div className="flex items-center gap-2 border-b border-line-soft px-3 py-2">
          {source === "app" ? <Activity size={12} className="text-accent" /> : <Cpu size={12} className="text-violet" />}
          <span className="truncate font-mono text-[10.5px] text-faint">{content?.path ?? "—"}</span>
          <Badge tone="neutral" className="ml-auto">{content?.lines.length ?? 0} lines</Badge>
        </div>
        <div className="h-[calc(100%-37px)] overflow-y-auto p-3">
          {content && content.lines.length === 0 && !error ? (
            <p className="text-xs text-faint">Log is empty so far.</p>
          ) : (
            <pre className="whitespace-pre-wrap break-all font-mono text-[10.5px] leading-relaxed text-muted">
              {content?.lines.join("\n")}
            </pre>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}

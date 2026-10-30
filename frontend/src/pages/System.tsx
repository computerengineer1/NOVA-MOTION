/** System — real hardware detection results, engine control, live logs.
 *  HTTP 200 ≠ ready: the readiness verdict runs model+workflow+runtime checks. */

import { useCallback, useEffect, useState } from "react";
import { Cpu, MemoryStick, Power, RefreshCw, RotateCw } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useSystemReport } from "../hooks/useBackend";
import { useToasts } from "../hooks/useToasts";
import { formatTimestamp } from "../lib/format";
import type { EngineStatus } from "../lib/types";
import { Badge, Button, Card } from "../components/ui";
import { HardwareTiles, OsLine, ReadinessBanner, ResourceBars } from "../components/SystemBits";
import { LogsViewer } from "../components/LogsViewer";
import { Header, PageTitle } from "../components/Layout";

export default function SystemPage() {
  const { push } = useToasts();
  const { report, backendOnline, error, refresh } = useSystemReport(4000);
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [engineBusy, setEngineBusy] = useState(false);

  const loadEngine = useCallback(async (force = true) => {
    try { setEngine(await api.engineStatus(force)); } catch { setEngine(null); }
  }, []);

  useEffect(() => { void loadEngine(false); }, [loadEngine]);
  useEffect(() => {
    const t = window.setInterval(() => void loadEngine(false), 8000);
    return () => window.clearInterval(t);
  }, [loadEngine]);

  const restartEngine = async () => {
    setEngineBusy(true);
    try {
      const r = await api.engineRestart();
      setEngine(r);
      push(r.online ? "success" : "warning", r.online ? "Engine restarted" : "Restart attempted",
        r.online ? `ComfyUI ${r.comfyui_version ?? ""} is online.` : "Engine did not come online — check the engine log below.");
    } catch (e) {
      push("error", "Engine restart failed", e instanceof ApiError ? e.message : String(e));
    } finally { setEngineBusy(false); }
  };

  const freeMemory = async () => {
    setEngineBusy(true);
    try {
      const r = await api.engineFree();
      push(r.ok ? "success" : "warning", r.ok ? "Engine memory freed" : "Free request not accepted", r.detail);
      await loadEngine();
    } catch (e) {
      push("error", "Could not free engine memory", e instanceof ApiError ? e.message : String(e));
    } finally { setEngineBusy(false); }
  };

  return (
    <>
      <Header right={
        <div className="flex items-center gap-2">
          {!backendOnline && <Badge tone="danger">backend offline</Badge>}
          <Button size="sm" variant="ghost" onClick={() => { refresh(); void loadEngine(); }}>
            <RefreshCw size={13} /> Refresh
          </Button>
        </div>
      }>
        <PageTitle title="System"
          subtitle={report ? `Detected at ${formatTimestamp(report.generated_at)} — values are measured live, not cached guesses` : undefined} />
      </Header>

      {!backendOnline && error && (
        <div className="mb-5 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-xs leading-relaxed text-danger" role="alert">
          <p className="font-semibold">The NOVA MOTION backend is not reachable.</p>
          <p className="mt-1 opacity-90">{error} — run <code className="font-mono">Start-Studio.bat</code> and reload this page.</p>
        </div>
      )}

      <div className="flex flex-col gap-5">
        <ReadinessBanner report={report} />
        {report && <OsLine report={report} />}
        <HardwareTiles report={report} />

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
          <ResourceBars report={report} />

          <Card title={<span className="flex items-center gap-2"><Cpu size={14} className="text-violet" /> Inference engine (ComfyUI)</span>}>
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={engine?.online ? "ok" : "danger"}>
                  <Power size={10} /> {engine?.online ? "online" : "offline"}
                </Badge>
                {engine?.online && (
                  <>
                    <Badge tone="neutral">v{engine.comfyui_version ?? "?"}</Badge>
                    <Badge tone="neutral">torch {engine.torch_version ?? "?"}</Badge>
                  </>
                )}
                {engine?.checked_at && (
                  <span className="font-mono text-[10px] text-faint">checked {formatTimestamp(engine.checked_at)}</span>
                )}
              </div>
              {engine?.online && (
                <p className="font-mono text-[10.5px] text-faint">{engine.base_url} — bound to loopback only</p>
              )}
              {engine?.last_error && (
                <p className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-[11px] leading-snug text-danger">
                  {engine.last_error}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" disabled={engineBusy} onClick={restartEngine}
                  title={engine?.online ? "Restart the managed ComfyUI process" : "Start the managed ComfyUI process"}>
                  <RotateCw size={13} /> {engine?.online ? "Restart engine" : "Start engine"}
                </Button>
                <Button size="sm" variant="ghost" disabled={engineBusy || !engine?.online} onClick={freeMemory}
                  title="Ask ComfyUI to unload models and free VRAM (POST /free)">
                  <MemoryStick size={13} /> Free VRAM now
                </Button>
              </div>
              <p className="text-[10.5px] leading-relaxed text-faint">
                The engine runs with <code className="font-mono">--lowvram --reserve-vram 0.6 --cache-none</code> on
                4 GB cards and listens on 127.0.0.1 only. After every job the backend asks it to
                release memory before anything else may run (sequential-only policy).
              </p>
            </div>
          </Card>
        </div>

        <Card title="Logs">
          <LogsViewer />
        </Card>
      </div>
    </>
  );
}

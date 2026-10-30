/** Models — registry browser + installer. Licenses are shown and must be
 *  accepted; sizes/checksums come from the registry; disk headroom is
 *  checked against the REAL free space of the outputs drive. */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Info, RefreshCw } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useSystemReport } from "../hooks/useBackend";
import { useToasts } from "../hooks/useToasts";
import { formatBytes } from "../lib/format";
import type { ModelProfile } from "../lib/types";
import { Button } from "../components/ui";
import { ModelCard } from "../components/ModelCard";
import { Header, PageTitle } from "../components/Layout";

export default function ModelsPage() {
  const { push } = useToasts();
  const { report } = useSystemReport();
  const [models, setModels] = useState<ModelProfile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setModels(await api.models());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // keep refreshing while any install is in flight (registry rescans disk state)
  const installing = (models ?? []).some((m) => m.install_progress != null && m.install_progress < 1);
  useEffect(() => {
    if (!installing) return;
    const t = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(t);
  }, [installing, load]);

  const diskFreeBytes = report?.disks[0]?.free_gb != null ? report.disks[0].free_gb * 1e9 : null;

  const onInstall = async (modelId: string) => {
    await api.installModel(modelId, true); // license acceptance happened in the card UI
    push("info", "Download started", `${modelId} — progress is real (resumable, SHA-256 verified per file).`);
  };
  const onCancelInstall = async (modelId: string) => {
    await api.cancelInstall(modelId);
    push("warning", "Install cancellation requested", "Partial files are kept so the download can resume later.");
  };
  const onValidate = async (modelId: string) => {
    const r = await api.validateModel(modelId);
    if (r.valid) push("success", "Validation passed", `All required files present with matching SHA-256 (${modelId}).`);
    else push("error", "Validation failed", r.note ?? "One or more files are missing or corrupted.");
  };
  const onDelete = async (modelId: string) => {
    await api.deleteModel(modelId);
  };

  const usable = (models ?? []).filter((m) => m.status !== "incompatible");
  const incompatible = (models ?? []).filter((m) => m.status === "incompatible");

  return (
    <>
      <Header right={
        <Button size="sm" variant="ghost" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Rescan
        </Button>
      }>
        <PageTitle title="Models"
          subtitle={diskFreeBytes != null ? `${formatBytes(diskFreeBytes)} free on the studio drive` : undefined} />
      </Header>

      <div className="mb-5 flex items-start gap-2 rounded-xl border border-line bg-ink-900 px-4 py-3 text-[11.5px] leading-relaxed text-muted">
        <Info size={14} className="mt-0.5 shrink-0 text-accent" />
        <p>
          Weights are downloaded once from their official sources (Hugging&nbsp;Face), verified
          with SHA-256, and stored locally — the app works offline afterwards. Models marked
          <strong className="text-danger"> incompatible</strong> are listed for transparency with
          the exact measured reason (VRAM/RAM), never hidden. Nothing is auto-deleted to make space.
          See <Link to="/help" className="text-accent hover:underline">MODEL_COMPATIBILITY notes in Help</Link>.
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-xs text-danger" role="alert">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {usable.map((m) => (
          <ModelCard key={m.model_id} model={m} diskFreeBytes={diskFreeBytes}
            onInstall={onInstall} onCancelInstall={onCancelInstall}
            onValidate={onValidate} onDelete={onDelete} onChanged={() => void load()} />
        ))}
      </div>

      {incompatible.length > 0 && (
        <>
          <h2 className="mb-3 mt-8 text-xs font-semibold uppercase tracking-wider text-faint">
            Not runnable on this hardware (listed for honesty)
          </h2>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {incompatible.map((m) => (
              <ModelCard key={m.model_id} model={m} diskFreeBytes={diskFreeBytes}
                onInstall={onInstall} onCancelInstall={onCancelInstall}
                onValidate={onValidate} onDelete={onDelete} onChanged={() => void load()} />
            ))}
          </div>
        </>
      )}
      {models == null && !error && <p className="text-sm text-faint">Loading registry…</p>}
    </>
  );
}

/** Model card: license, sizes, per-file install state, compatibility checks,
 *  live install progress, validate/remove. Nothing is invented — every
 *  number comes from the backend registry / disk scan. */

import { useState } from "react";
import {
  AlertTriangle, BadgeCheck, Check, Download, FileWarning, HardDrive,
  ShieldCheck, Trash2, X, XCircle,
} from "lucide-react";
import { useToasts } from "../hooks/useToasts";
import { formatBytes } from "../lib/format";
import type { ModelProfile } from "../lib/types";
import { Badge, Button, ConfirmDialog, ProgressBar } from "./ui";

const STATUS_BADGE: Record<string, { tone: "ok" | "accent" | "violet" | "warn" | "danger" | "neutral"; label: string }> = {
  recommended: { tone: "ok", label: "Recommended" },
  supported: { tone: "accent", label: "Supported" },
  experimental: { tone: "violet", label: "Experimental" },
  incompatible: { tone: "danger", label: "Incompatible" },
};

export function ModelCard({ model, diskFreeBytes, onInstall, onCancelInstall, onValidate, onDelete, onChanged }: {
  model: ModelProfile;
  diskFreeBytes: number | null;
  onInstall: (modelId: string) => Promise<void>;
  onCancelInstall: (modelId: string) => Promise<void>;
  onValidate: (modelId: string) => Promise<void>;
  onDelete: (modelId: string) => Promise<void>;
  onChanged: () => void;
}) {
  const { push } = useToasts();
  const [accepted, setAccepted] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const badge = STATUS_BADGE[model.status] ?? { tone: "neutral" as const, label: model.status };
  const installable = model.compatibility?.installable === true;
  const notEnoughDisk =
    diskFreeBytes != null && !model.installed && model.total_download_bytes > diskFreeBytes * 0.9;
  const canInstall = installable && !model.installed && (accepted || model.installed) && !notEnoughDisk;

  const installing = model.install_progress != null && model.install_progress < 1;
  const failedFiles = model.files.filter((f) => f.required && f.installed && f.checksum_ok === false);

  const doInstall = async () => {
    setBusy(true);
    try {
      await onInstall(model.model_id);
      onChanged();
    } catch (e) {
      push("error", "Install failed", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-line-soft bg-ink-900/70 p-5">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-txt">{model.name}</h3>
        <Badge tone={badge.tone}>{badge.label}</Badge>
        {model.installed ? (
          <Badge tone="ok"><BadgeCheck size={10} /> installed</Badge>
        ) : model.install_progress != null ? (
          <Badge tone="accent">installing…</Badge>
        ) : null}
        {model.validation_status === "valid" && <Badge tone="ok"><ShieldCheck size={10} /> validated</Badge>}
        {model.validation_status === "invalid" && <Badge tone="danger"><XCircle size={10} /> validation failed</Badge>}
      </div>

      <p className="mb-3 font-mono text-[10.5px] text-faint">
        {model.model_id} · {model.model_type} · {model.adapter}
        {model.version ? ` · ${model.version}` : ""}
      </p>

      {/* incompatible explanation */}
      {!installable && (
        <div className="mb-3 rounded-xl border border-danger/25 bg-danger-soft px-3.5 py-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-danger">
            <AlertTriangle size={13} /> Not installable on this machine
          </p>
          {model.compatibility?.checks?.map((c) => (
            <p key={c.name} className="flex items-start gap-1.5 py-0.5 text-[11.5px] leading-snug text-muted">
              {c.ok === false ? <X size={11} className="mt-0.5 shrink-0 text-danger" />
                : c.ok ? <Check size={11} className="mt-0.5 shrink-0 text-ok" />
                : <FileWarning size={11} className="mt-0.5 shrink-0 text-warn" />}
              <span><span className="text-txt">{c.name}:</span> {c.message}</span>
            </p>
          ))}
          {(model.capabilities?.incompatible_reason || model.memory_notes) && (
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted">
              {model.capabilities?.incompatible_reason ?? model.memory_notes}
            </p>
          )}
        </div>
      )}

      {/* memory / quality notes */}
      {(model.memory_notes || model.capabilities?.quality_notes) && (
        <div className="mb-3 rounded-xl border border-line bg-ink-950/60 px-3.5 py-2.5 text-[11.5px] leading-relaxed text-muted">
          {model.memory_notes && <p><span className="text-txt">VRAM:</span> {model.memory_notes}</p>}
          {model.capabilities?.quality_notes && (
            <p className="mt-1"><span className="text-txt">Quality:</span> {model.capabilities.quality_notes}</p>
          )}
        </div>
      )}

      {/* files */}
      <div className="mb-3">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-faint">
            Files ({model.files.filter((f) => f.installed).length}/{model.files.length})
          </span>
          <span className="flex items-center gap-1.5 font-mono text-[11px] text-muted">
            <HardDrive size={11} /> {formatBytes(model.total_download_bytes)}
            {diskFreeBytes != null && (
              <span className="text-faint">· {formatBytes(diskFreeBytes)} free</span>
            )}
          </span>
        </div>
        <ul className="flex flex-col gap-1">
          {model.files.map((f) => (
            <li key={f.id} className="flex items-center gap-2 rounded-lg bg-ink-950/60 px-2.5 py-1.5 font-mono text-[10.5px]">
              {f.installed && f.checksum_ok !== false ? (
                <Check size={11} className="shrink-0 text-ok" />
              ) : f.installed && f.checksum_ok === false ? (
                <XCircle size={11} className="shrink-0 text-danger" />
              ) : (
                <span className="grid size-[11px] shrink-0 place-items-center rounded-full border border-ink-600" />
              )}
              <span className="min-w-0 flex-1 truncate text-muted" title={f.dest}>{f.dest}</span>
              <span className="shrink-0 text-faint">
                {f.installed && f.actual_size_bytes != null ? formatBytes(f.actual_size_bytes) : formatBytes(f.size_bytes)}
              </span>
              {!f.required && <Badge tone="neutral" className="px-1 py-0 text-[9px]">optional</Badge>}
            </li>
          ))}
        </ul>
        {failedFiles.length > 0 && (
          <p className="mt-1.5 text-[11px] text-danger">
            Checksum mismatch — re-download via Repair-Studio or delete + install again.
          </p>
        )}
        {model.validation_note && (
          <p className="mt-1.5 text-[11px] text-faint">{model.validation_note}</p>
        )}
      </div>

      {/* live install progress */}
      {installing && (
        <div className="mb-3 rounded-xl border border-accent/25 bg-accent-soft/40 px-3.5 py-3">
          <div className="mb-2 flex items-center justify-between text-[11px]">
            <span className="flex items-center gap-1.5 font-medium text-accent-hi">
              <Download size={12} className="animate-pulse-slow" />
              Downloading {Math.round((model.install_progress ?? 0) * 100)}%
            </span>
            <Button size="sm" variant="ghost" onClick={() => void onCancelInstall(model.model_id).then(onChanged)}>
              Cancel
            </Button>
          </div>
          <ProgressBar value={Math.round((model.install_progress ?? 0) * 100)} />
          <p className="mt-1.5 text-[10.5px] text-faint">
            Downloads resume automatically if interrupted; SHA-256 is verified per file.
          </p>
        </div>
      )}

      {/* license */}
      {!model.installed && installable && (
        <label className="mb-3 flex cursor-pointer items-start gap-2 rounded-xl border border-line bg-ink-950/60 px-3 py-2.5 text-[11.5px] leading-snug text-muted">
          <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[#4f8dff]" />
          <span>
            I accept the <span className="text-txt">{model.license_id}</span> license for these
            weights{model.license_url && (
              <> (<a href={model.license_url} target="_blank" rel="noreferrer noopener"
                className="text-accent underline-offset-2 hover:underline"
                onClick={(e) => e.stopPropagation()}>read it</a>)</>
            )}. Source: <span className="font-mono text-[10.5px]">{model.source}</span>
          </span>
        </label>
      )}

      {notEnoughDisk && (
        <p className="mb-3 flex items-start gap-1.5 text-[11.5px] leading-snug text-danger">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          Not enough free disk space ({formatBytes(diskFreeBytes)} free, need{" "}
          {formatBytes(model.total_download_bytes)} + headroom). Free space first — NOVA MOTION
          never deletes your files automatically.
        </p>
      )}

      {/* actions */}
      <div className="flex flex-wrap gap-2">
        {!model.installed && installable && (
          <Button size="sm" variant="primary" disabled={!canInstall || busy || installing}
            onClick={doInstall}
            title={!accepted ? "Accept the license to enable installation" : undefined}>
            <Download size={14} /> {installing ? "Installing…" : `Install (${formatBytes(model.total_download_bytes)})`}
          </Button>
        )}
        {model.installed && (
          <Button size="sm" variant="secondary" disabled={busy}
            onClick={async () => { setBusy(true); try { await onValidate(model.model_id); onChanged(); } finally { setBusy(false); } }}>
            <ShieldCheck size={14} /> Validate files
          </Button>
        )}
        {model.installed && (
          <Button size="sm" variant="danger" disabled={busy} onClick={() => setConfirmDelete(true)}>
            <Trash2 size={14} /> Remove
          </Button>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title={`Remove ${model.name}?`}
        confirmLabel="Delete weight files"
        danger
        onClose={() => setConfirmDelete(false)}
        onConfirm={async () => {
          setBusy(true);
          try { await onDelete(model.model_id); onChanged(); push("success", "Model removed", "Weight files deleted from disk."); }
          catch (e) { push("error", "Remove failed", e instanceof Error ? e.message : String(e)); }
          finally { setBusy(false); }
        }}
        body={
          <p className="text-sm leading-relaxed text-muted">
            Deletes {formatBytes(model.total_download_bytes)} of downloaded weight files.
            Your generated videos are <strong className="text-txt">not</strong> touched.
            You can re-install later (re-downloads everything).
          </p>
        }
      />
    </div>
  );
}

/** Toast renderer bound to the ToastProvider context. */

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useToasts } from "../hooks/useToasts";
import type { ToastKind } from "../hooks/useToasts";

const ICONS: Record<ToastKind, typeof Info> = {
  info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle,
};
const TONES: Record<ToastKind, string> = {
  info: "border-accent/30 text-accent-hi",
  success: "border-ok/30 text-ok",
  warning: "border-warn/30 text-warn",
  error: "border-danger/40 text-danger",
};

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(92vw,380px)] flex-col gap-2"
      aria-live="polite" role="status">
      {toasts.map((t) => {
        const Icon = ICONS[t.kind];
        return (
          <div key={t.id}
            className={`glass surface-raised pointer-events-auto flex items-start gap-3 border-l-2 p-3.5 shadow-xl ${TONES[t.kind]}`}>
            <Icon size={17} className="mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-txt">{t.title}</div>
              {t.body && <div className="mt-0.5 text-xs leading-relaxed text-muted">{t.body}</div>}
              {t.recovery && (
                <div className="mt-1.5 text-xs leading-relaxed text-faint">
                  <span className="font-semibold text-muted">Recovery: </span>{t.recovery}
                </div>
              )}
            </div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification"
              className="focus-ring rounded p-1 text-faint hover:text-txt">
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

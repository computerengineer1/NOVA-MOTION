/** Shared UI primitives — consistent design tokens, accessible defaults. */

import { useEffect, useRef } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { X } from "lucide-react";

/* ------------------------------------------------------------------ Button */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "accent-soft";
type ButtonSize = "sm" | "md" | "lg";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white hover:bg-accent-hi active:translate-y-px shadow-[0_2px_12px_rgba(79,141,255,0.25)] disabled:bg-ink-700 disabled:text-faint disabled:shadow-none",
  secondary:
    "bg-ink-750 text-txt border border-line hover:bg-ink-700 hover:border-ink-600 active:translate-y-px disabled:text-faint disabled:hover:bg-ink-750",
  ghost:
    "bg-transparent text-muted hover:text-txt hover:bg-ink-800 active:translate-y-px disabled:text-faint",
  danger:
    "bg-danger-soft text-danger border border-danger/30 hover:bg-danger/20 active:translate-y-px disabled:text-faint",
  "accent-soft":
    "bg-accent-soft text-accent-hi border border-accent/25 hover:bg-accent/20 active:translate-y-px disabled:text-faint",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
  lg: "h-12 px-6 text-sm font-semibold gap-2 rounded-xl",
};

export function Button({
  variant = "secondary", size = "md", className = "", children, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      className={`focus-ring inline-flex items-center justify-center font-medium transition-all duration-150
        disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${BUTTON_SIZES[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------- Badge */

export type BadgeTone = "neutral" | "accent" | "violet" | "ok" | "warn" | "danger";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-ink-750 text-muted border-line",
  accent: "bg-accent-soft text-accent-hi border-accent/30",
  violet: "bg-violet-soft text-violet border-violet/30",
  ok: "bg-ok-soft text-ok border-ok/30",
  warn: "bg-warn-soft text-warn border-warn/30",
  danger: "bg-danger-soft text-danger border-danger/30",
};

export function Badge({ tone = "neutral", children, className = "", title }: {
  tone?: BadgeTone; children: ReactNode; className?: string; title?: string;
}) {
  return (
    <span title={title}
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider ${BADGE_TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------- Card */

export function Card({ children, className = "", title, actions }: {
  children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode;
}) {
  return (
    <section className={`surface-raised p-4 sm:p-5 ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-sm font-semibold tracking-wide text-txt">{title}</h2>}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ Fields */

export function Label({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 flex items-baseline justify-between gap-2">
      <span className="text-xs font-semibold uppercase tracking-wider text-muted">{children}</span>
      {hint && <span className="text-[11px] font-normal normal-case text-faint">{hint}</span>}
    </label>
  );
}

export function Input({ className = "", invalid, ...rest }: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }) {
  return (
    <input
      className={`focus-ring h-10 w-full rounded-lg border bg-ink-900 px-3 text-sm text-txt placeholder:text-faint
        ${invalid ? "border-danger/60" : "border-line"} ${className}`}
      {...rest}
    />
  );
}

export function Textarea({ className = "", ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`focus-ring w-full rounded-xl border border-line bg-ink-900 px-3.5 py-3 text-sm leading-relaxed text-txt
        placeholder:text-faint ${className}`}
      {...rest}
    />
  );
}

export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`focus-ring h-10 w-full appearance-none rounded-lg border border-line bg-ink-900 px-3 text-sm text-txt
        bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%2398a2b8%22 stroke-width=%222.5%22><path d=%22M6 9l6 6 6-6%22/></svg>')]
        bg-[length:12px] bg-[right_0.7rem_center] bg-no-repeat pr-8 ${className}`}
      {...rest}
    >
      {children}
    </select>
  );
}

export function Field({ label, htmlFor, hint, children, error }: {
  label: string; htmlFor?: string; hint?: string; children: ReactNode; error?: string | null;
}) {
  return (
    <div>
      <Label htmlFor={htmlFor} hint={hint}>{label}</Label>
      {children}
      {error && <p className="mt-1 text-xs text-danger" role="alert">{error}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ Toggle */

export function Toggle({ checked, onChange, label, description, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string;
  description?: string; disabled?: boolean;
}) {
  return (
    <button
      type="button" role="switch" aria-checked={checked} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`focus-ring flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors
        ${disabled ? "cursor-not-allowed border-line-soft opacity-50" : "border-line hover:border-ink-600"}
        ${checked ? "bg-accent-soft/60" : "bg-ink-900"}`}
    >
      <span>
        <span className="block text-sm font-medium text-txt">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-faint">{description}</span>}
      </span>
      <span className={`relative inline-flex h-5.5 w-10 shrink-0 items-center rounded-full transition-colors ${checked ? "bg-accent" : "bg-ink-600"}`}>
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? "translate-x-5" : "translate-x-1"}`} />
      </span>
    </button>
  );
}

/* ------------------------------------------------------- Segmented control */

export function Segmented<T extends string>({ value, onChange, options, ariaLabel }: {
  value: T; onChange: (v: T) => void; ariaLabel: string;
  options: Array<{ value: T; label: string; title?: string; disabled?: boolean }>;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel}
      className="inline-flex w-full rounded-xl border border-line bg-ink-900 p-1">
      {options.map((opt) => (
        <button
          key={opt.value} type="button" role="radio" title={opt.title}
          aria-checked={value === opt.value} disabled={opt.disabled}
          onClick={() => onChange(opt.value)}
          className={`focus-ring flex-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-all
            ${value === opt.value
              ? "bg-accent-soft text-accent-hi shadow-[inset_0_0_0_1px_rgba(79,141,255,0.35)]"
              : "text-muted hover:text-txt"}
            ${opt.disabled ? "cursor-not-allowed opacity-40" : ""}`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- Progress bar */

export function ProgressBar({ value, indeterminate, tone = "accent" }: {
  value?: number; indeterminate?: boolean; tone?: "accent" | "violet" | "ok";
}) {
  const toneClass = tone === "violet" ? "bg-violet" : tone === "ok" ? "bg-ok" : "bg-accent";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-750" role="progressbar"
      aria-valuenow={value != null ? Math.round(Math.min(100, Math.max(0, value))) : undefined}
      aria-valuemin={0} aria-valuemax={100}>
      {indeterminate ? (
        <div className="shimmer h-full w-full" />
      ) : (
        <div className={`h-full rounded-full transition-[width] duration-500 ease-out ${toneClass}`}
          style={{ width: `${Math.min(100, Math.max(0, value ?? 0))}%` }} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Spinner */

export function Spinner({ size = 16, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={`animate-spin ${className}`} aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" fill="none" opacity="0.2" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}

/* -------------------------------------------------------------- EmptyState */

export function EmptyState({ icon, title, body, action }: {
  icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line px-6 py-14 text-center">
      {icon && <div className="text-faint">{icon}</div>}
      <h3 className="text-base font-semibold text-txt">{title}</h3>
      {body && <div className="max-w-md text-sm text-muted">{body}</div>}
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------- Modal */

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/65" onClick={onClose} aria-hidden="true" />
      <div ref={ref} tabIndex={-1}
        className={`glass surface-raised relative z-10 max-h-[88vh] w-full overflow-y-auto p-5 sm:p-6 ${wide ? "max-w-4xl" : "max-w-lg"}`}>
        <header className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold text-txt">{title}</h2>
          <button onClick={onClose} aria-label="Close dialog"
            className="focus-ring rounded-lg p-1.5 text-muted hover:bg-ink-750 hover:text-txt">
            <X size={17} />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

/* --------------------------------------------------------- ConfirmDialog */

export function ConfirmDialog({ open, onClose, onConfirm, title, body, confirmLabel = "Confirm", danger }: {
  open: boolean; onClose: () => void; onConfirm: () => void;
  title: string; body: ReactNode; confirmLabel?: string; danger?: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="text-sm leading-relaxed text-muted">{body}</div>
      <footer className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant={danger ? "danger" : "primary"} onClick={() => { onConfirm(); onClose(); }}>
          {confirmLabel}
        </Button>
      </footer>
    </Modal>
  );
}

/* -------------------------------------------------------------- Stat tile */

export function StatTile({ label, value, sub, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "ok" | "warn" | "danger";
}) {
  const valueColor = tone === "warn" ? "text-warn" : tone === "danger" ? "text-danger" : tone === "ok" ? "text-ok" : "text-txt";
  return (
    <div className="surface rounded-xl px-4 py-3">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-faint">{label}</div>
      <div className={`mt-1 text-lg font-semibold leading-tight ${valueColor}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

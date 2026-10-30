/** App shell: sidebar navigation + header with live system status. */

import { NavLink } from "react-router-dom";
import {
  Activity, Clapperboard, Cpu, Film, HardDriveDownload, HelpCircle, Settings2,
} from "lucide-react";
import type { SystemReport } from "../lib/types";
import { Badge } from "./ui";

const NAV = [
  { to: "/", label: "Studio", icon: Clapperboard, end: true },
  { to: "/videos", label: "My Videos", icon: Film, end: false },
  { to: "/models", label: "Models", icon: HardDriveDownload, end: false },
  { to: "/system", label: "System", icon: Cpu, end: false },
  { to: "/settings", label: "Settings", icon: Settings2, end: false },
  { to: "/help", label: "Help & Diagnostics", icon: HelpCircle, end: false },
];

export function readinessTone(level: string | undefined): "ok" | "warn" | "danger" {
  if (level === "READY") return "ok";
  if (level === "WARNING") return "warn";
  return "danger";
}

export function SystemStatusPill({ report, backendOnline }: {
  report: SystemReport | null; backendOnline: boolean;
}) {
  if (!backendOnline || !report) {
    return (
      <Badge tone="danger" title="Backend unreachable">
        <Activity size={11} /> Offline
      </Badge>
    );
  }
  const level = report.readiness.level;
  const tone = readinessTone(level);
  const label = level === "READY" ? "Ready" : level === "WARNING" ? "Warning" : "Not ready";
  const detail = [
    ...report.readiness.reasons,
    ...report.readiness.warnings,
  ].join("\n");
  return (
    <Badge tone={tone} title={detail || `Generation readiness: ${level}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${tone === "ok" ? "bg-ok" : tone === "warn" ? "bg-warn animate-pulse-slow" : "bg-danger animate-pulse-slow"}`} />
      {label}
    </Badge>
  );
}

export function Sidebar({ queue }: { queue?: { running_job_id: string | null; queued: number } | null }) {
  return (
    <nav aria-label="Main navigation"
      className="flex h-full w-16 shrink-0 flex-col border-r border-line-soft bg-ink-900/70 py-4
                 lg:w-56 lg:px-3">
      <div className="mb-7 flex items-center gap-2.5 px-2 lg:px-2.5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-accent/30 bg-accent-soft">
          <svg width="18" height="18" viewBox="0 0 64 64" aria-hidden="true">
            <path d="M20 44V20l24 24V20" fill="none" stroke="#74a6ff" strokeWidth="6"
              strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="hidden leading-tight lg:block">
          <div className="text-[15px] font-bold tracking-wide text-txt">NOVA MOTION</div>
          <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-faint">
            Local AI Video Studio
          </div>
        </div>
      </div>
      <ul className="flex flex-1 flex-col gap-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink to={to} end={end} title={label}
              className={({ isActive }) =>
                `focus-ring group flex items-center gap-3 rounded-xl px-2.5 py-2.5 text-sm font-medium transition-colors
                 lg:px-3 ${isActive
                    ? "bg-accent-soft text-accent-hi shadow-[inset_0_0_0_1px_rgba(79,141,255,0.25)]"
                    : "text-muted hover:bg-ink-800 hover:text-txt"}`}
            >
              <Icon size={18} className="shrink-0" aria-hidden="true" />
              <span className="hidden lg:inline">{label}</span>
              {to === "/" && queue?.running_job_id && (
                <span className="ml-auto hidden h-2 w-2 rounded-full bg-accent animate-pulse-slow lg:inline"
                  title="Generation running" />
              )}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="mt-auto hidden px-3 pt-4 text-[10.5px] leading-relaxed text-faint lg:block">
        <div className="font-semibold text-muted">100% local · private</div>
        Prompts and videos never leave this PC.
      </div>
    </nav>
  );
}

export function Header({ children, right }: { children?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <header className="glass sticky top-0 z-40 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line-soft px-4 sm:px-6">
      <div className="min-w-0">{children}</div>
      <div className="flex shrink-0 items-center gap-2.5">{right}</div>
    </header>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="min-w-0">
      <h1 className="truncate text-[15px] font-bold tracking-wide text-txt">{title}</h1>
      {subtitle && <p className="truncate text-xs text-faint">{subtitle}</p>}
    </div>
  );
}

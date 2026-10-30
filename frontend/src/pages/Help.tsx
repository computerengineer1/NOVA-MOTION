/** Help & Diagnostics — beginner guide, honesty policy, compatibility notes,
 *  diagnostic bundle, troubleshooting quick hits. */

import { useState } from "react";
import {
  BookOpen, Bug, ChevronDown, Download, LifeBuoy, ShieldCheck, Terminal,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useSystemReport } from "../hooks/useBackend";
import { useToasts } from "../hooks/useToasts";
import { Button, Card } from "../components/ui";
import { ReadinessBanner } from "../components/SystemBits";
import { Header, PageTitle } from "../components/Layout";

function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-line-soft bg-ink-900/60">
      <button className="focus-ring flex w-full items-center gap-2 px-4 py-3 text-left text-xs font-medium text-txt"
        onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <ChevronDown size={14} className={`shrink-0 text-faint transition-transform ${open ? "rotate-180" : ""}`} />
        {q}
      </button>
      {open && (
        <div className="border-t border-line-soft px-4 py-3 text-[11.5px] leading-relaxed text-muted">
          {children}
        </div>
      )}
    </div>
  );
}

export default function HelpPage() {
  const { push } = useToasts();
  const { report } = useSystemReport();

  const downloadDiagnostic = async () => {
    try {
      const d = await api.diagnostic();
      const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `nova-motion-diagnostic-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
      a.click();
      URL.revokeObjectURL(url);
      push("success", "Diagnostic bundle downloaded", "Review it before sharing — it stays on your machine unless you choose otherwise.");
    } catch (e) {
      push("error", "Could not build diagnostic bundle", e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <>
      <Header right={
        <Button size="sm" variant="secondary" onClick={downloadDiagnostic}>
          <Download size={13} /> Diagnostic bundle
        </Button>
      }>
        <PageTitle title="Help & Diagnostics" subtitle="How NOVA MOTION works, what it promises, and how to fix it when it doesn't" />
      </Header>

      <div className="flex flex-col gap-5">
        <ReadinessBanner report={report} />

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Card title={<span className="flex items-center gap-2"><BookOpen size={14} className="text-accent" /> Quick start (Windows 11)</span>}>
            <ol className="flex list-decimal flex-col gap-2 pl-4 text-[11.5px] leading-relaxed text-muted marker:text-faint">
              <li>Run <code className="font-mono text-txt">scripts\Install-Studio.ps1</code> once (right-click → “Run with PowerShell”, or use <code className="font-mono text-txt">Install-Studio.bat</code>). It installs Python deps, ComfyUI v0.43.0, the AnimateDiff node pack and FFmpeg — all locally, no admin rights.</li>
              <li>Run <code className="font-mono text-txt">Start-Studio.bat</code>. A browser tab opens at <code className="font-mono text-txt">http://127.0.0.1:8317</code>.</li>
              <li>Open <strong className="text-txt">Models</strong>, accept the licenses and install the recommended pack (~4 GB, resumable, SHA-256 verified).</li>
              <li>Open <strong className="text-txt">Studio</strong>, write a prompt, press <strong className="text-txt">Generate</strong>. First run is slowest (model load); watch real progress.</li>
              <li>The finished, duration-validated MP4 lands in <strong className="text-txt">My Videos</strong> and <code className="font-mono text-txt">outputs/</code>.</li>
              <li>When done, run <code className="font-mono text-txt">Stop-Studio.bat</code> (or close the windows).</li>
            </ol>
          </Card>

          <Card title={<span className="flex items-center gap-2"><ShieldCheck size={14} className="text-ok" /> Honesty policy</span>}>
            <ul className="flex list-disc flex-col gap-2 pl-4 text-[11.5px] leading-relaxed text-muted">
              <li>Every progress number comes from real ComfyUI execution events or real FFmpeg runs — nothing is simulated, and there is no demo mode.</li>
              <li>“8 seconds” means the exported file measures 8.000 s ±1 frame with <code className="font-mono">ffprobe</code>, or the job is marked FAILED — never silently shipped short.</li>
              <li>Interpolated frames (16/24 fps) and Lanczos upscaling are labeled as such everywhere: they are post-processing, not newly generated content.</li>
              <li>Multi-shot videos are labeled: 4 independently sampled ~2 s segments joined together — motion continuity across cuts is not guaranteed.</li>
              <li>ETAs start only after the backend measures real sampler step rate on your machine. Before that you see stages, not invented percentages.</li>
              <li>Cancel is cooperative: ComfyUI stops between sampling steps. Until then the UI says “cancel requested”, and the final state is whatever truly happened.</li>
            </ul>
          </Card>

          <Card title={<span className="flex items-center gap-2"><Terminal size={14} className="text-violet" /> PowerShell scripts</span>}>
            <ul className="flex flex-col gap-2 font-mono text-[11px] text-muted">
              <li><span className="text-txt">Install-Studio.ps1</span> — one-time setup (deps, engine, FFmpeg)</li>
              <li><span className="text-txt">Start-Studio.bat</span> — backend + engine + browser</li>
              <li><span className="text-txt">Stop-Studio.bat</span> — graceful shutdown, frees VRAM</li>
              <li><span className="text-txt">Diagnose-Studio.ps1</span> — hardware/port/disk/dependency report</li>
              <li><span className="text-txt">Repair-Studio.ps1</span> — re-verify checksums, resume broken downloads</li>
            </ul>
            <p className="mt-2 text-[10.5px] leading-relaxed text-faint">
              None of them need admin rights, touch system settings, or require Docker/WSL.
            </p>
          </Card>

          <Card title={<span className="flex items-center gap-2"><Bug size={14} className="text-warn" /> Common problems</span>}>
            <div className="flex flex-col gap-2">
              <Faq q="CUDA out of memory during generation">
                Expected occasionally on 4 GB VRAM. The app automatically retries ONCE with a
                lower-memory route (multi-shot + smaller context). If it fails again, close
                browsers/games (they eat VRAM), pick 640×360, keep 8 fps, and retry. Never
                select the 768×432 preset on this GPU.
              </Faq>
              <Faq q="Engine shows offline on the System page">
                Press “Start engine”, then watch the engine log tab below in Logs. Most common
                causes: NVIDIA driver too old (update via GeForce Experience), or the first
                start is still importing torch (can take ~30 s).
              </Faq>
              <Faq q="Download stuck or checksum mismatch">
                Downloads resume where they left off. Run <code className="font-mono">Repair-Studio.ps1</code> or
                press “Validate files” on the Models page, then re-install the affected file.
              </Faq>
              <Faq q="Video is shorter/longer than 8 s">
                Cannot ship: the validator rejects any file outside 8.000 s ±1 frame and the job
                is marked FAILED with the measured duration in the error. Re-run the generation.
              </Faq>
              <Faq q="RIFE option is greyed out">
                The optional Fannovel16/ComfyUI-Frame-Interpolation node pack isn't installed in
                the engine folder. minterpolate (built into FFmpeg) needs nothing and works today.
              </Faq>
            </div>
          </Card>
        </div>

        <Card title={<span className="flex items-center gap-2"><LifeBuoy size={14} className="text-accent" /> Diagnostics</span>}>
          <div className="flex flex-col gap-3 text-[11.5px] leading-relaxed text-muted">
            <p>
              The diagnostic bundle (button top-right, or on the System page) contains: full
              hardware report, readiness verdict, engine status, recent generation records, and
              log tails. It is generated locally and saved to your Downloads — it is never sent
              anywhere automatically.
            </p>
            <p>
              Full written guides ship with the project: <code className="font-mono text-txt">README.md</code>,{" "}
              <code className="font-mono text-txt">MODEL_COMPATIBILITY.md</code> (why AnimateDiff+SD1.5 won and
              why LTX-2/Wan/Hunyuan were rejected with measured numbers),{" "}
              <code className="font-mono text-txt">TROUBLESHOOTING.md</code>,{" "}
              <code className="font-mono text-txt">LICENSES.md</code> and{" "}
              <code className="font-mono text-txt">CHANGELOG.md</code> in the <code className="font-mono text-txt">docs/</code> folder.
            </p>
          </div>
        </Card>
      </div>
    </>
  );
}

/** App shell: router + persistent sidebar + backend-offline awareness. */

import { useEffect, useRef } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useSystemReport } from "./hooks/useBackend";
import { ToastProvider, useToasts } from "./hooks/useToasts";
import { Sidebar } from "./components/Layout";
import { Toaster } from "./components/Toaster";
import StudioPage from "./pages/Studio";
import VideosPage from "./pages/Videos";
import ModelsPage from "./pages/Models";
import SystemPage from "./pages/System";
import SettingsPage from "./pages/Settings";
import HelpPage from "./pages/Help";

/** Notify once when the backend drops, once when it returns. */
function useBackendOfflineNotifier(online: boolean) {
  const { push } = useToasts();
  const prev = useRef(online);
  useEffect(() => {
    if (prev.current && !online) {
      push("error", "Backend unreachable",
        "The NOVA MOTION backend stopped answering. Running jobs (if any) live inside the backend process — check its console window or run Diagnose-Studio.");
    } else if (!prev.current && online) {
      push("success", "Backend reconnected", "Live status restored.");
    }
    prev.current = online;
  }, [online, push]);
}

function Shell() {
  const { report, backendOnline } = useSystemReport(5000);
  useBackendOfflineNotifier(backendOnline);

  return (
    <div className="flex min-h-screen">
      <Sidebar queue={report?.queue ?? null} />
      <main className="min-w-0 flex-1 px-5 py-6 sm:px-8">
        <Routes>
          <Route path="/" element={<Navigate to="/studio" replace />} />
          <Route path="/studio" element={<StudioPage />} />
          <Route path="/videos" element={<VideosPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="*" element={<Navigate to="/studio" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <Shell />
        <Toaster />
      </ToastProvider>
    </BrowserRouter>
  );
}

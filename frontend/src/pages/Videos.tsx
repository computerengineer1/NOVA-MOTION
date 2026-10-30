/** My Videos — the local library. Real files only, with filters and
 *  honest provenance. Nothing here was ever uploaded anywhere. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderOpen, Search } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useToasts } from "../hooks/useToasts";
import { formatBytes } from "../lib/format";
import type { VideoOut } from "../lib/types";
import { Button, Input, Select } from "../components/ui";
import { VideoGrid } from "../components/VideoCard";
import { Header, PageTitle } from "../components/Layout";

export default function VideosPage() {
  const { push } = useToasts();
  const [videos, setVideos] = useState<VideoOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [sort, setSort] = useState("newest");

  const load = useCallback(async () => {
    try {
      const r = await api.videos({ q: q || undefined, modelId: modelFilter || undefined, sort });
      setVideos(r);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [q, modelFilter, sort]);

  useEffect(() => {
    const t = window.setTimeout(() => void load(), q ? 300 : 0);
    return () => window.clearTimeout(t);
  }, [load, q]);

  const models = useMemo(
    () => Array.from(new Set((videos ?? []).map((v) => v.model_id))).sort(), [videos]);
  const totalBytes = useMemo(
    () => (videos ?? []).reduce((s, v) => s + (v.size_bytes ?? 0), 0), [videos]);

  const openFolder = async () => {
    try {
      await api.openOutputsFolder();
    } catch (e) {
      push("error", "Could not open the folder", e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <>
      <Header right={
        <Button size="sm" variant="secondary" onClick={openFolder} title="Opens the outputs folder in Windows Explorer">
          <FolderOpen size={14} /> Open outputs folder
        </Button>
      }>
        <PageTitle title="My Videos"
          subtitle={videos ? `${videos.length} validated clips · ${formatBytes(totalBytes)} on disk · stored locally in outputs/` : undefined} />
      </Header>

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input placeholder="Search prompts…" value={q} onChange={(e) => setQ(e.target.value)}
            className="pl-9" aria-label="Search videos by prompt" />
        </div>
        <Select value={modelFilter} onChange={(e) => setModelFilter(e.target.value)}
          aria-label="Filter by model" className="w-52">
          <option value="">All models</option>
          {models.map((m) => <option key={m} value={m}>{m}</option>)}
        </Select>
        <Select value={sort} onChange={(e) => setSort(e.target.value)}
          aria-label="Sort order" className="w-40">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </Select>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-xs text-danger" role="alert">
          {error}
        </div>
      )}
      {videos == null && !error && <p className="text-sm text-faint">Loading library…</p>}
      {videos != null && <VideoGrid videos={videos} onChange={() => void load()} />}
    </>
  );
}

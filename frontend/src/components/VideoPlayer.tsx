/** Professional video player with custom controls (play/pause, seek, volume,
 *  fullscreen, frame-accurate time display). Native <video> element inside —
 *  real playback of the real generated MP4, never a placeholder. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Maximize, Minimize, Pause, Play, Volume2, VolumeX } from "lucide-react";
import { formatClock } from "../lib/format";

export function VideoPlayer({ src, poster, className = "" }: {
  src: string; poster?: string; className?: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const toggle = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play(); else v.pause();
  }, []);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setCurrent(v.currentTime);
    const onMeta = () => setDuration(v.duration || 0);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnd = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onMeta);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("ended", onEnd);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onMeta);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("ended", onEnd);
    };
  }, [src]);

  const toggleFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      setFullscreen(false);
    } else {
      void el.requestFullscreen?.();
      setFullscreen(true);
    }
  }, []);

  const changeVolume = (value: number) => {
    setVolume(value);
    if (videoRef.current) videoRef.current.volume = value;
    setMuted(value === 0);
    if (videoRef.current) videoRef.current.muted = value === 0;
  };

  const seekTo = (fraction: number) => {
    const v = videoRef.current;
    if (!v || !duration) return;
    v.currentTime = Math.min(Math.max(0, fraction * duration), duration);
  };

  return (
    <div ref={containerRef} className={`group relative overflow-hidden rounded-xl border border-line bg-black ${className}`}>
      <video
        ref={videoRef} src={src} poster={poster} loop playsInline preload="metadata"
        className="block aspect-video w-full cursor-pointer bg-black object-contain"
        onClick={toggle} aria-label="Generated video preview"
      />
      <div className="flex items-center gap-3 border-t border-line bg-ink-900/95 px-3 py-2">
        <button onClick={toggle} aria-label={playing ? "Pause" : "Play"}
          className="focus-ring rounded-lg p-1.5 text-txt hover:bg-ink-750">
          {playing ? <Pause size={17} /> : <Play size={17} />}
        </button>
        <span className="font-mono text-[11px] tabular-nums text-muted" aria-live="off">
          {formatClock(current)} / {formatClock(duration)}
        </span>
        <div className="relative flex-1">
          <input
            type="range" min={0} max={duration || 0} step={0.01} value={current}
            onChange={(e) => { const v = videoRef.current; if (v) v.currentTime = Number(e.target.value); }}
            aria-label="Seek"
            className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-ink-700 accent-[#4f8dff]
              [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none
              [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent"
            style={{
              background: duration
                ? `linear-gradient(to right, #4f8dff ${(current / duration) * 100}%, #232b3b ${(current / duration) * 100}%)`
                : undefined,
            }}
          />
        </div>
        <div className="hidden items-center gap-1.5 sm:flex">
          <button onClick={() => { const v = videoRef.current; if (v) { v.muted = !v.muted; setMuted(v.muted); } }}
            aria-label={muted ? "Unmute" : "Mute"}
            className="focus-ring rounded-lg p-1.5 text-muted hover:bg-ink-750 hover:text-txt">
            {muted || volume === 0 ? <VolumeX size={16} /> : <Volume2 size={16} />}
          </button>
          <input type="range" min={0} max={1} step={0.05} value={muted ? 0 : volume}
            onChange={(e) => changeVolume(Number(e.target.value))}
            aria-label="Volume" className="h-1 w-16 cursor-pointer accent-[#4f8dff]" />
        </div>
        <button onClick={toggleFullscreen} aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen"}
          className="focus-ring rounded-lg p-1.5 text-muted hover:bg-ink-750 hover:text-txt">
          {fullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
        </button>
      </div>
      <button
        onClick={(e) => { e.preventDefault(); seekTo(0); }}
        className="hidden" aria-hidden="true" tabIndex={-1}
      />
    </div>
  );
}

import { useRef, useEffect } from "react";
import type { BeatMarker } from "../types";
import type { WaveformBands } from "../types";

type MiniWaveformProps = {
  samples: WaveformBands;
  durationSeconds: number;
  currentTime?: number;
  isPreviewing?: boolean;
  beatMarkers?: BeatMarker[];
  cueTimeSeconds?: number | null;
  onSeek?: (time: number) => void;
  fillWidth?: boolean;
  width?: number;
  height?: number;
};

export function MiniWaveform({
  samples,
  durationSeconds,
  currentTime = 0,
  isPreviewing = false,
  beatMarkers = [],
  cueTimeSeconds = null,
  onSeek,
  fillWidth = false,
  width = 160,
  height = 32
}: MiniWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const renderedWidth = fillWidth ? Math.max(1, wrapperRef.current?.clientWidth || width) : width;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = renderedWidth * ratio;
    canvas.height = height * ratio;
    ctx.scale(ratio, ratio);

    ctx.clearRect(0, 0, renderedWidth, height);

    if (samples.energy.length === 0 || durationSeconds <= 0) {
      ctx.fillStyle = "rgba(255,255,255,0.05)";
      ctx.fillRect(0, height / 2 - 1, renderedWidth, 2);
      return;
    }

    const { energy, low, mid, high } = samples;
    const centerY = height / 2;
    const barCount = renderedWidth; // 1 pixel per sample for simplicity in mini view

    for (let x = 0; x < barCount; x++) {
      const sampleIndex = Math.floor((x / renderedWidth) * energy.length);
      const e = energy[sampleIndex] || 0;
      const l = low[sampleIndex] || 0;
      const m = mid[sampleIndex] || 0;
      const h = high[sampleIndex] || 0;

      const amp = Math.max(1, e * (height / 2 - 2));
      
      // RGB Colors like Rekordbox 3-band
      const r = Math.round(l * 255);
      const g = Math.round(m * 255);
      const b = Math.round(h * 255);

      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.8)`;
      ctx.fillRect(x, centerY - amp, 1, amp * 2);
    }

    // Draw playhead if this track is being previewed
    if (isPreviewing) {
      const playheadX = (currentTime / durationSeconds) * renderedWidth;
      ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
      ctx.fillRect(Math.round(playheadX), 0, 2, height);
    }

    if (cueTimeSeconds !== null && Number.isFinite(cueTimeSeconds)) {
      const cueX = Math.round((cueTimeSeconds / durationSeconds) * renderedWidth);
      ctx.strokeStyle = "rgba(255, 176, 32, 1)";
      ctx.fillStyle = "rgba(255, 176, 32, 1)";
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 3]);
      ctx.beginPath();
      ctx.moveTo(cueX + 0.5, 0);
      ctx.lineTo(cueX + 0.5, height);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.strokeStyle = "rgba(0, 0, 0, 0.8)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cueX - 4.5, 2);
      ctx.lineTo(cueX + 4.5, 2);
      ctx.lineTo(cueX, 9);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(cueX - 4.5, height - 2);
      ctx.lineTo(cueX + 4.5, height - 2);
      ctx.lineTo(cueX, height - 9);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#111";
      ctx.fillRect(cueX - 12, 1, 24, 8);
      ctx.fillStyle = "rgba(255, 176, 32, 1)";
      ctx.font = "bold 8px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText("CUE", cueX, 2);
    }

    if (beatMarkers.length > 0) {
      for (const marker of beatMarkers) {
        const x = Math.round((marker.timelineSeconds / durationSeconds) * renderedWidth);
        ctx.fillStyle = marker.isBar ? "rgba(255, 48, 48, 0.95)" : "rgba(255, 255, 255, 0.48)";
        ctx.fillRect(x, 0, 1, height);
      }
    }

  }, [samples, durationSeconds, currentTime, isPreviewing, beatMarkers, cueTimeSeconds, fillWidth, width, height]);

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const effectiveWidth = fillWidth ? rect.width : width;
    const time = (x / Math.max(1, effectiveWidth)) * durationSeconds;
    onSeek(time);
  };

  return (
    <div ref={wrapperRef} style={{ width: fillWidth ? "100%" : `${width}px` }}>
      <canvas 
        ref={canvasRef} 
        width={width} 
        height={height} 
        onClick={handleClick}
        style={{ 
          width: fillWidth ? "100%" : `${width}px`, 
          height: `${height}px`, 
          display: 'block', 
          background: '#000',
          cursor: 'pointer',
          borderRadius: '2px',
          border: '1px solid rgba(255,255,255,0.1)'
        }}
      />
    </div>
  );
}

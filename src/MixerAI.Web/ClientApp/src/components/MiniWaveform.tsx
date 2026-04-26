import { useRef, useEffect } from "react";
import type { WaveformBands } from "../types";

type MiniWaveformProps = {
  samples: WaveformBands;
  durationSeconds: number;
  currentTime?: number;
  isPreviewing?: boolean;
  onSeek?: (time: number) => void;
  width?: number;
  height?: number;
};

export function MiniWaveform({
  samples,
  durationSeconds,
  currentTime = 0,
  isPreviewing = false,
  onSeek,
  width = 160,
  height = 32
}: MiniWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    ctx.scale(ratio, ratio);

    ctx.clearRect(0, 0, width, height);

    if (samples.energy.length === 0 || durationSeconds <= 0) {
      ctx.fillStyle = "rgba(255,255,255,0.05)";
      ctx.fillRect(0, height / 2 - 1, width, 2);
      return;
    }

    const { energy, low, mid, high } = samples;
    const centerY = height / 2;
    const barCount = width; // 1 pixel per sample for simplicity in mini view

    for (let x = 0; x < barCount; x++) {
      const sampleIndex = Math.floor((x / width) * energy.length);
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
      const playheadX = (currentTime / durationSeconds) * width;
      ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
      ctx.fillRect(Math.round(playheadX), 0, 2, height);
    }

  }, [samples, durationSeconds, currentTime, isPreviewing, width, height]);

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const time = (x / width) * durationSeconds;
    onSeek(time);
  };

  return (
    <canvas 
      ref={canvasRef} 
      width={width} 
      height={height} 
      onClick={handleClick}
      style={{ 
        width: `${width}px`, 
        height: `${height}px`, 
        display: 'block', 
        background: '#000',
        cursor: 'pointer',
        borderRadius: '2px',
        border: '1px solid rgba(255,255,255,0.1)'
      }}
    />
  );
}

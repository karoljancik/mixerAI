import { useEffect, useRef } from "react";
import type { BeatMarker } from "../types";

type WaveformCanvasProps = {
  samples: number[];
  accent: string;
  background?: string;
  beatMarkers?: BeatMarker[];
  durationSeconds?: number;
  className?: string;
};

export function WaveformCanvas({
  samples,
  accent,
  background = "rgba(255,255,255,0.03)",
  beatMarkers = [],
  durationSeconds,
  className,
}: WaveformCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const context = canvas.getContext("2d");
    if (!context) {
      return;
    }

    const redraw = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const ratio = window.devicePixelRatio || 1;

      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);

      context.clearRect(0, 0, width, height);
      context.fillStyle = background;
      context.fillRect(0, 0, width, height);

      context.strokeStyle = "rgba(255,255,255,0.08)";
      context.beginPath();
      context.moveTo(0, height / 2);
      context.lineTo(width, height / 2);
      context.stroke();

      if (samples.length > 0) {
        const center = height / 2;
        const step = width / Math.max(samples.length, 1);
        context.fillStyle = accent;

        samples.forEach((sample, index) => {
          const barHeight = Math.max(2, sample * height * 0.42);
          const x = index * step;
          context.fillRect(x, center - barHeight, Math.max(1.2, step * 0.7), barHeight * 2);
        });
      }

      if (beatMarkers.length > 0 && durationSeconds && durationSeconds > 0) {
        beatMarkers.forEach((marker) => {
          const x = (marker.timelineSeconds / durationSeconds) * width;
          context.strokeStyle = marker.isBar ? "rgba(255,255,255,0.48)" : "rgba(255,255,255,0.18)";
          context.lineWidth = marker.isBar ? 2 : 1;
          context.beginPath();
          context.moveTo(x, 8);
          context.lineTo(x, height - 8);
          context.stroke();
        });
      }
    };

    redraw();
    const observer = new ResizeObserver(redraw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [accent, background, beatMarkers, durationSeconds, samples]);

  return <canvas ref={canvasRef} className={className} />;
}

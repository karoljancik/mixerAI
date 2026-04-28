import React, { useEffect, useRef, useMemo } from "react";
import type { PointerEventHandler, RefObject } from "react";
import type { BeatMarker, WaveformBands } from "../types";



function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

function getPercentile(values: number[], percentile: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = clamp01(percentile) * (sorted.length - 1);
  const lower = Math.floor(pos);
  const upper = Math.ceil(pos);
  const blend = pos - lower;
  return (sorted[lower] ?? 0) * (1 - blend) + (sorted[upper] ?? 0) * blend;
}

function getSampleAtTime(samples: number[], timeSeconds: number, durationSeconds: number): number {
  if (samples.length === 0 || durationSeconds <= 0) return 0;
  if (timeSeconds <= 0) return clamp01(samples[0] ?? 0);
  if (timeSeconds >= durationSeconds) return clamp01(samples[samples.length - 1] ?? 0);

  const exactIndex = (timeSeconds / durationSeconds) * (samples.length - 1);
  const baseIndex = Math.floor(exactIndex);
  const blend = exactIndex - baseIndex;

  const left = samples[Math.max(0, baseIndex - 1)] ?? 0;
  const current = samples[baseIndex] ?? 0;
  const next = samples[Math.min(samples.length - 1, baseIndex + 1)] ?? current;
  const right = samples[Math.min(samples.length - 1, baseIndex + 2)] ?? next;

  const near = current * (1 - blend) + next * blend;
  const wide = left * 0.18 + current * 0.32 + next * 0.32 + right * 0.18;
  return clamp01(near * 0.7 + wide * 0.3);
}

function drawBeatMarker(context: CanvasRenderingContext2D, x: number, height: number, isBar: boolean) {
  const markerColor = isBar ? "#ff2222" : "rgba(255, 255, 255, 0.55)";
  const lineWidth = isBar ? 1.5 : 1.1;

  // Vertical line
  context.strokeStyle = markerColor;
  context.lineWidth = lineWidth;
  context.beginPath();
  context.moveTo(x + 0.5, 0);
  context.lineTo(x + 0.5, height);
  context.stroke();

  if (isBar) {
    // Red Triangles at top and bottom (Compact Rekordbox style)
    const triSize = 4;
    context.fillStyle = "#ff2222";
    
    // Top triangle
    context.beginPath();
    context.moveTo(x - triSize, 0);
    context.lineTo(x + triSize, 0);
    context.lineTo(x, triSize * 1.5);
    context.closePath();
    context.fill();

    // Bottom triangle
    context.beginPath();
    context.moveTo(x - triSize, height);
    context.lineTo(x + triSize, height);
    context.lineTo(x, height - triSize * 1.5);
    context.closePath();
    context.fill();
  }
}

type WaveformCanvasProps = {
  samples: WaveformBands;
  accent?: string;
  background?: string;
  beatMarkers?: BeatMarker[];
  cueTimeSeconds?: number | null;
  durationSeconds?: number;
  audioRef?: RefObject<HTMLAudioElement | null>;
  zoomPxPerSec?: number;
  className?: string;
  onPointerDown?: PointerEventHandler<HTMLCanvasElement>;
};

export const WaveformCanvas = React.memo(({
  samples,
  accent = "#f1c40f",
  background = "#000",
  beatMarkers = [],
  cueTimeSeconds = null,
  durationSeconds,
  audioRef,
  zoomPxPerSec = 112,
  className,
  onPointerDown,
}: WaveformCanvasProps) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const bounds = useMemo(() => {
    if (samples.energy.length === 0) return { low: 0, high: 1 };
    return {
      low: getPercentile(samples.energy, 0.08),
      high: getPercentile(samples.energy, 0.992),
    };
  }, [samples.energy]);

  const offscreenRef = useRef<HTMLCanvasElement[]>([]);
  const CACHE_PX_PER_SEC = 56; // Half res cache for huge memory savings and speed

  useEffect(() => {
    if (!samples.energy.length || !durationSeconds) return;

    const totalWidth = durationSeconds * CACHE_PX_PER_SEC;
    const height = 160; 
    const MAX_TILE_WIDTH = 8000;
    const numTiles = Math.ceil(totalWidth / MAX_TILE_WIDTH);
    const tiles: HTMLCanvasElement[] = [];

    // Removed unused global variables as they are redefined per tile in the loop

    for (let t = 0; t < numTiles; t++) {
      const tileCanvas = document.createElement("canvas");
      tileCanvas.width = Math.min(MAX_TILE_WIDTH, totalWidth - t * MAX_TILE_WIDTH);
      tileCanvas.height = height;
      const tCtx = tileCanvas.getContext("2d");
      if (!tCtx) continue;

      const tileStartSec = (t * MAX_TILE_WIDTH) / CACHE_PX_PER_SEC;
      const halfWaveHeight = height * 0.45;
      const center = height / 2;

      const layers = [
        { 
          // LAYER 1: SOLID BLUE (OVERALL ENVELOPE / BASS)
          // Rekordbox uses a high-res (fuzzy) edge for the blue envelope.
          color: "rgba(0, 71, 255, 1.0)", 
          getAmp: (l: number, m: number, h: number) => Math.max(l, m, h) * halfWaveHeight,
          smooth: 0 // No smoothing for that high-res/noisy look at the edges
        },
        { 
          // LAYER 2: SOLID AMBER (MIDS)
          color: "rgba(212, 137, 0, 1.0)",
          getAmp: (_l: number, m: number) => m * halfWaveHeight * 0.78,
          smooth: 3 // Smooth transitions for mids
        },
        { 
          // LAYER 3: PURE WHITE (HIGHS/TRANSIENTS)
          color: "rgba(250, 249, 246, 1.0)", 
          getAmp: (_l: number, _m: number, h: number, e: number, tr: number) => {
             const normE = clamp01((e - bounds.low) / Math.max(0.001, bounds.high - bounds.low));
             return (h * 0.45 + tr * 0.45 + normE * 0.1) * halfWaveHeight * 0.45;
          },
          smooth: 1 // Sharp but not aliased
        }
      ];

      layers.forEach(layer => {
        tCtx.beginPath();
        tCtx.fillStyle = layer.color;
        tCtx.lineJoin = "miter"; // Sharper spikes
        tCtx.lineCap = "butt";
        
        const smoothWindow = layer.smooth; 

        for (let x = 0; x < tileCanvas.width; x++) {
          let avgAmp = 0;
          let count = 0;
          for (let sw = -smoothWindow; sw <= smoothWindow; sw++) {
            const time = tileStartSec + ((x + sw) / CACHE_PX_PER_SEC);
            if (time < 0 || time > durationSeconds) continue;
            
            const low = getSampleAtTime(samples.low, time, durationSeconds);
            const mid = getSampleAtTime(samples.mid, time, durationSeconds);
            const high = getSampleAtTime(samples.high, time, durationSeconds);
            const energy = getSampleAtTime(samples.energy, time, durationSeconds);
            const prevE = getSampleAtTime(samples.energy, time - 0.05, durationSeconds);
            const nextE = getSampleAtTime(samples.energy, time + 0.05, durationSeconds);
            const transient = clamp01((energy - ((prevE + nextE) * 0.5)) * 4.8 + 0.1);

            avgAmp += (layer as any).getAmp(low, mid, high, energy, transient);
            count++;
          }
          const amp = avgAmp / (count || 1);
          if (x === 0) tCtx.moveTo(x, center - amp);
          else tCtx.lineTo(x, center - amp);
        }
        
        for (let x = tileCanvas.width - 1; x >= 0; x--) {
          let avgAmp = 0;
          let count = 0;
          const windowSize = smoothWindow;
          for (let sw = -windowSize; sw <= windowSize; sw++) {
            const time = tileStartSec + ((x + sw) / CACHE_PX_PER_SEC);
            if (time < 0 || time > durationSeconds) continue;

            const low = getSampleAtTime(samples.low, time, durationSeconds);
            const mid = getSampleAtTime(samples.mid, time, durationSeconds);
            const high = getSampleAtTime(samples.high, time, durationSeconds);
            const energy = getSampleAtTime(samples.energy, time, durationSeconds);
            const prevE = getSampleAtTime(samples.energy, time - 0.05, durationSeconds);
            const nextE = getSampleAtTime(samples.energy, time + 0.05, durationSeconds);
            const transient = clamp01((energy - ((prevE + nextE) * 0.5)) * 4.8 + 0.1);
            avgAmp += (layer as any).getAmp(low, mid, high, energy, transient);
            count++;
          }
          const amp = avgAmp / (count || 1);
          tCtx.lineTo(x, center + amp);
        }
        
        tCtx.closePath();
        tCtx.fill();
      });

      tiles.push(tileCanvas);
    }

    offscreenRef.current = tiles;
  }, [samples, bounds, durationSeconds]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let animFrame = 0;

    const redraw = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const ratio = window.devicePixelRatio || 1;

      if (canvas.width !== Math.floor(width * ratio)) canvas.width = Math.floor(width * ratio);
      if (canvas.height !== Math.floor(height * ratio)) canvas.height = Math.floor(height * ratio);

      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.fillStyle = background;
      context.fillRect(0, 0, width, height);

      const currentTime = audioRef?.current?.currentTime || 0;

      const tiles = offscreenRef.current;
      if (tiles.length > 0 && durationSeconds && durationSeconds > 0) {
        const visibleSeconds = width / zoomPxPerSec;
        const startTime = currentTime - visibleSeconds / 2;
        
        // Draw cached tiles
        const scaleX = zoomPxPerSec / CACHE_PX_PER_SEC;
        
        tiles.forEach((tile, i) => {
          const tileStartSec = (i * 8000) / CACHE_PX_PER_SEC;
          const tileEndSec = tileStartSec + tile.width / CACHE_PX_PER_SEC;
          
          if (tileEndSec < startTime || tileStartSec > startTime + visibleSeconds) return;

          const xOffset = (tileStartSec - startTime) * zoomPxPerSec;
          context.drawImage(
            tile,
            0, 0, tile.width, tile.height,
            xOffset, 0, tile.width * scaleX, height
          );
        });

        // Professional Grid
        context.strokeStyle = "rgba(255, 255, 255, 0.03)";
        context.lineWidth = 1;
        [0.25, 0.5, 0.75].forEach(pct => {
          const y = height * pct;
          context.beginPath();
          context.moveTo(0, y);
          context.lineTo(width, y);
          context.stroke();
        });

        if (beatMarkers.length > 0) {
          const visibleTimeStart = currentTime - (width / 2) / zoomPxPerSec;
          const visibleTimeEnd = currentTime + (width / 2) / zoomPxPerSec;
          
          for (let i = 0; i < beatMarkers.length; i++) {
            const m = beatMarkers[i];
            if (m.timelineSeconds < visibleTimeStart || m.timelineSeconds > visibleTimeEnd) continue;
            const x = Math.round((width / 2) + ((m.timelineSeconds - currentTime) * zoomPxPerSec));
            drawBeatMarker(context, x, height, m.isBar);
          }
        }

        if (cueTimeSeconds !== null && Number.isFinite(cueTimeSeconds)) {
          const cueX = Math.round((width / 2) + ((cueTimeSeconds - currentTime) * zoomPxPerSec));
          if (cueX >= -12 && cueX <= width + 12) {
            context.strokeStyle = "rgba(255, 176, 32, 0.95)";
            context.lineWidth = 1.5;
            context.setLineDash([5, 4]);
            context.beginPath();
            context.moveTo(cueX + 0.5, 0);
            context.lineTo(cueX + 0.5, height);
            context.stroke();
            context.setLineDash([]);

            context.fillStyle = "rgba(255, 176, 32, 0.95)";
            context.beginPath();
            context.moveTo(cueX - 4, 8);
            context.lineTo(cueX + 4, 8);
            context.lineTo(cueX, 2);
            context.closePath();
            context.fill();

            context.beginPath();
            context.moveTo(cueX - 4, height - 8);
            context.lineTo(cueX + 4, height - 8);
            context.lineTo(cueX, height - 2);
            context.closePath();
            context.fill();
          }
        }
      }

      context.strokeStyle = accent;
      context.lineWidth = 1.5;
      context.beginPath();
      context.moveTo(width / 2, 0);
      context.lineTo(width / 2, height);
      context.stroke();

      context.strokeStyle = "rgba(255,255,255,0.95)";
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(width / 2, 0);
      context.lineTo(width / 2, height);
      context.stroke();

      animFrame = requestAnimationFrame(redraw);
    };

    redraw();
    return () => cancelAnimationFrame(animFrame);
  }, [accent, audioRef, background, beatMarkers, cueTimeSeconds, durationSeconds, bounds, zoomPxPerSec]);


  return <canvas ref={canvasRef} className={className} style={{ cursor: "ew-resize" }} onPointerDown={onPointerDown} />;
});

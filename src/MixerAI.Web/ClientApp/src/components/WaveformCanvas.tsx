import type { PointerEventHandler, RefObject } from "react";
import { useEffect, useRef } from "react";
import type { BeatMarker, WaveformBands } from "../types";

const ZOOM_PX_PER_SEC = 112;
const BAR_WIDTH_PX = 2;
const BAR_GAP_PX = 1;
const WAVEFORM_VERTICAL_PADDING = 4;

function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

function getPercentile(values: number[], percentile: number): number {
  if (values.length === 0) {
    return 0;
  }

  const sorted = [...values].sort((left, right) => left - right);
  const position = clamp01(percentile) * (sorted.length - 1);
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.ceil(position);
  const blend = position - lowerIndex;

  return (sorted[lowerIndex] ?? 0) * (1 - blend) + (sorted[upperIndex] ?? 0) * blend;
}


function getSampleAtTime(samples: number[], timeSeconds: number, durationSeconds: number): number {
  if (samples.length === 0 || durationSeconds <= 0) {
    return 0;
  }

  if (timeSeconds <= 0) {
    return clamp01(samples[0] ?? 0);
  }

  if (timeSeconds >= durationSeconds) {
    return clamp01(samples[samples.length - 1] ?? 0);
  }

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

function drawMirroredBar(
  context: CanvasRenderingContext2D,
  x: number,
  centerY: number,
  width: number,
  amplitude: number,
  color: string,
) {
  const safeAmplitude = Math.max(1, amplitude);
  context.fillStyle = color;
  context.fillRect(x, centerY - safeAmplitude, width, safeAmplitude - 1);
  context.fillRect(x, centerY + 1, width, safeAmplitude - 1);
}

type WaveformCanvasProps = {
  samples: WaveformBands;
  accent?: string;
  background?: string;
  beatMarkers?: BeatMarker[];
  durationSeconds?: number;
  audioRef?: RefObject<HTMLAudioElement | null>;
  className?: string;
  onPointerDown?: PointerEventHandler<HTMLCanvasElement>;
};

export function WaveformCanvas({
  samples,
  accent = "#f1c40f",
  background = "#000",
  beatMarkers = [],
  durationSeconds,
  audioRef,
  className,
  onPointerDown,
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

    let animFrame = 0;

    const redraw = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const ratio = window.devicePixelRatio || 1;

      if (canvas.width !== Math.floor(width * ratio)) {
        canvas.width = Math.floor(width * ratio);
      }
      if (canvas.height !== Math.floor(height * ratio)) {
        canvas.height = Math.floor(height * ratio);
      }

      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.fillStyle = background;
      context.fillRect(0, 0, width, height);

      const currentTime = audioRef?.current?.currentTime || 0;
      const center = height / 2;
      const halfWaveHeight = Math.max(6, center - WAVEFORM_VERTICAL_PADDING);

      if (samples.energy.length > 0 && durationSeconds && durationSeconds > 0) {
        const step = BAR_WIDTH_PX + BAR_GAP_PX;
        const visibleSeconds = width / ZOOM_PX_PER_SEC;
        const sampleWindowSeconds = visibleSeconds / Math.max(1, width / step);
        const bars: Array<{ x: number; low: number; mid: number; high: number; energy: number; transient: number }> = [];

        for (let xPos = 0; xPos <= width; xPos += step) {
          const timeAtX = currentTime + (xPos - width / 2) / ZOOM_PX_PER_SEC;

          if (timeAtX < 0 || (durationSeconds && timeAtX > durationSeconds)) {
            continue;
          }

          const previousEnergy = getSampleAtTime(samples.energy, timeAtX - sampleWindowSeconds, durationSeconds);
          const currentEnergy = getSampleAtTime(samples.energy, timeAtX, durationSeconds);
          const nextEnergy = getSampleAtTime(samples.energy, timeAtX + sampleWindowSeconds, durationSeconds);

          bars.push({
            x: xPos,
            low: getSampleAtTime(samples.low, timeAtX, durationSeconds),
            mid: getSampleAtTime(samples.mid, timeAtX, durationSeconds),
            high: getSampleAtTime(samples.high, timeAtX, durationSeconds),
            energy: clamp01((previousEnergy * 0.24) + (currentEnergy * 0.52) + (nextEnergy * 0.24)),
            transient: clamp01((currentEnergy - ((previousEnergy + nextEnergy) * 0.5)) * 4.8 + 0.1),
          });
        }

        const energyValues = bars.map((bar) => bar.energy);
        const lowPercentile = getPercentile(energyValues, 0.08);
        const highPercentile = getPercentile(energyValues, 0.992);
        const visibleRange = Math.max(0.0001, highPercentile - lowPercentile);
        const neighborhoodRadius = 3;

        bars.forEach((bar, index) => {
          let neighborhoodTotal = 0;
          let neighborhoodCount = 0;

          for (let offset = -neighborhoodRadius; offset <= neighborhoodRadius; offset += 1) {
            const neighbor = bars[index + offset];
            if (!neighbor) {
              continue;
            }

            neighborhoodTotal += neighbor.energy;
            neighborhoodCount += 1;
          }

          const neighborhoodAverage = neighborhoodCount > 0 ? neighborhoodTotal / neighborhoodCount : bar.energy;
          const normalizedEnergy = clamp01((bar.energy - lowPercentile) / visibleRange);
          const contrastBoost = clamp01((bar.energy - neighborhoodAverage) * 6.2 + 0.42);
          const shapedEnergy = Math.pow(normalizedEnergy, 1.42);
          const combinedEnergy = clamp01((shapedEnergy * 0.8) + (contrastBoost * 0.22) + (bar.transient * 0.14));
          const r = clamp01((bar.low * 1.1) + (bar.transient * 0.2)) * 255;
          const g = clamp01((bar.mid * 1.1) + (bar.transient * 0.2)) * 255;
          const b = clamp01((bar.high * 1.2) + 0.1 + (bar.transient * 0.3)) * 255;

          const air = clamp01((bar.high * 0.8) + (bar.transient * 0.35));

          const outerAmplitude = Math.max(1, halfWaveHeight * (0.08 + combinedEnergy * 0.54));
          const warmAmplitude = Math.max(1, outerAmplitude * (0.4 + bar.low * 0.4));
          const midAmplitude = Math.max(1, outerAmplitude * (0.2 + bar.mid * 0.5));
          const airAmplitude = Math.max(1, outerAmplitude * (0.1 + air * 0.3));
          const coreAmplitude = Math.max(1, outerAmplitude * (0.04 + bar.transient * 0.14 + bar.high * 0.06));

          const bodyColor = `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, 0.85)`;
          const accentColor = `rgba(${Math.round(Math.min(255, r + 50))}, ${Math.round(Math.min(255, g + 50))}, ${Math.round(Math.min(255, b + 50))}, 0.95)`;

          drawMirroredBar(context, bar.x, center, BAR_WIDTH_PX, outerAmplitude, `rgba(${Math.round(r * 0.5)}, ${Math.round(g * 0.5)}, ${Math.round(b * 0.8)}, 0.6)`);
          drawMirroredBar(context, bar.x, center, BAR_WIDTH_PX, warmAmplitude, `rgba(${Math.round(r)}, ${Math.round(g * 0.3)}, ${Math.round(b * 0.3)}, 0.8)`);
          drawMirroredBar(context, bar.x, center, BAR_WIDTH_PX, midAmplitude, bodyColor);
          drawMirroredBar(context, bar.x, center, 1, Math.max(airAmplitude, coreAmplitude), accentColor);
          drawMirroredBar(context, bar.x, center, 1, coreAmplitude, "rgba(255, 255, 255, 0.94)");
        });

        context.strokeStyle = "rgba(255, 255, 255, 0.18)";
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(0, center);
        context.lineTo(width, center);
        context.stroke();

        const visibleTimeStart = currentTime - (width / 2) / ZOOM_PX_PER_SEC;
        const visibleTimeEnd = currentTime + (width / 2) / ZOOM_PX_PER_SEC;

        if (beatMarkers.length > 0) {
          for (let index = 0; index < beatMarkers.length; index += 1) {
            const marker = beatMarkers[index];
            if (marker.timelineSeconds < visibleTimeStart || marker.timelineSeconds > visibleTimeEnd) {
              continue;
            }

            const x = Math.round((width / 2) + ((marker.timelineSeconds - currentTime) * ZOOM_PX_PER_SEC));

            context.strokeStyle = marker.isBar ? "rgba(255, 50, 50, 0.95)" : "rgba(200, 200, 200, 0.7)";
            context.lineWidth = marker.isBar ? 3 : 1.5;
            context.beginPath();
            context.moveTo(x, 0);
            context.lineTo(x, height);
            context.stroke();

            context.fillStyle = marker.isBar ? "rgb(255, 78, 78)" : "rgb(200, 200, 200)";

            context.beginPath();
            context.moveTo(x, 0);
            context.lineTo(x - 4, 6);
            context.lineTo(x + 4, 6);
            context.fill();

            context.beginPath();
            context.moveTo(x, height);
            context.lineTo(x - 4, height - 6);
            context.lineTo(x + 4, height - 6);
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

    return () => {
      cancelAnimationFrame(animFrame);
    };
  }, [accent, audioRef, background, beatMarkers, durationSeconds, samples]);

  return <canvas ref={canvasRef} className={className} style={{ cursor: "ew-resize" }} onPointerDown={onPointerDown} />;
}

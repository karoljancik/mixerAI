// @ts-nocheck
import React, { startTransition, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { api } from "./api";
import { GainSlider } from "./components/GainSlider";
import { WaveformCanvas } from "./components/WaveformCanvas";
import { Knob } from "./components/Knob";
import type {
  BeatMarker,
  MixAnalysisResult,
  RenderMixRequest,
  SessionResponse,
  Track,
  TransitionRecommendation,
  TransitionRecommendationRequest,
  WaveformBands,
  WorkspaceSnapshot,
} from "./types";
import { MiniWaveform } from "./components/MiniWaveform";

type AuthMode = "login" | "register";

type AuthFormState = {
  email: string;
  password: string;
};

const studioPills = ["AI DJ copilot", "Explainable transition scoring", "Set journey planner", "Playable demo renders"];

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "--";
  }

  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "--";
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatPreciseSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "0.000";
  }

  return seconds.toFixed(3);
}

function formatPreciseClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "0:00.000";
  }

  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - (minutes * 60);
  return `${minutes}:${remainder.toFixed(3).padStart(6, "0")}`;
}

function parsePreciseSecondsInput(value: string): number | null {
  const normalized = value.replace(",", ".").trim();
  if (!normalized) {
    return null;
  }

  // Handle M:SS.mmm or H:M:S format
  if (normalized.includes(":")) {
    const parts = normalized.split(":");
    if (parts.length === 2) {
      const minutes = parseFloat(parts[0]);
      const seconds = parseFloat(parts[1]);
      if (Number.isFinite(minutes) && Number.isFinite(seconds)) {
        return (minutes * 60) + seconds;
      }
    } else if (parts.length === 3) {
      const hours = parseFloat(parts[0]);
      const minutes = parseFloat(parts[1]);
      const seconds = parseFloat(parts[2]);
      if (Number.isFinite(hours) && Number.isFinite(minutes) && Number.isFinite(seconds)) {
        return (hours * 3600) + (minutes * 60) + seconds;
      }
    }
  }

  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

const EMPTY_WAVEFORM: WaveformBands = {
  low: [],
  mid: [],
  high: [],
  energy: [],
  transient: [],
};

const TrackRow = React.memo(({ 
  track, 
  index, 
  isSelected, 
  previewTrackId, 
  previewCurrentTime, 
  isPreviewing,
  togglePreview,
  handlePreviewSeek,
  setSelectedDeckAId,
  setSelectedDeckBId,
  handleRetryTrack,
  handleDeleteTrack
}: {
  track: Track;
  index: number;
  isSelected: boolean;
  previewTrackId: string | null;
  previewCurrentTime: number;
  isPreviewing: boolean;
  togglePreview: (id: string) => void;
  handlePreviewSeek: (time: number) => void;
  setSelectedDeckAId: (id: string) => void;
  setSelectedDeckBId: (id: string) => void;
  handleRetryTrack: (t: Track) => void;
  handleDeleteTrack: (t: Track) => void;
}) => {
  const waveform = useMemo(() => parseWaveform(track), [track]);

  return (
    <tr 
      className={isSelected ? 'selected' : ''}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', track.id);
      }}
    >
      <td>{index + 1}</td>
      <td style={{ padding: '4px' }}>
        <MiniWaveform 
          samples={waveform} 
          durationSeconds={track.durationSeconds || 1} 
          currentTime={previewTrackId === track.id ? previewCurrentTime : 0}
          isPreviewing={previewTrackId === track.id}
          onSeek={(time) => {
            if (previewTrackId !== track.id) togglePreview(track.id);
            handlePreviewSeek(time);
          }}
          width={140}
          height={28}
        />
      </td>
      <td>
        <div className="flex-row">
          <button 
            className={`action-btn ${previewTrackId === track.id && isPreviewing ? 'active pulse' : ''}`}
            onClick={(e) => {
              e.stopPropagation();
              togglePreview(track.id);
            }}
            title="Preview track"
          >
            {previewTrackId === track.id && isPreviewing ? "⏹" : "▶"}
          </button>
          <span>{track.title}</span>
        </div>
      </td>
      <td className="small-text">{track.artist || "--"}</td>
      <td>{track.bpm ? track.bpm.toFixed(1) : "--"}</td>
      <td>{track.camelotKey || "--"}</td>
      <td>{formatDuration(track.durationSeconds)}</td>
      <td className="status-cell" title={track.lastAnalysisError || undefined}>
        <span style={{ color: track.status.toLowerCase() === "error" ? "var(--danger)" : "inherit" }}>
          {track.status}
          {track.status.toLowerCase() === "error" && " ⚠️"}
        </span>
      </td>
      <td>
        <div className="flex-row">
          <button className="action-btn deck-assign" disabled={track.status.toLowerCase() !== "ready"} onClick={() => setSelectedDeckAId(track.id)}>1</button>
          <button className="action-btn deck-assign" disabled={track.status.toLowerCase() !== "ready"} onClick={() => setSelectedDeckBId(track.id)}>2</button>
          <button className="action-btn" disabled={track.status.toLowerCase() === "analyzing"} onClick={() => handleRetryTrack(track)}>RETRY</button>
          <button className="action-btn danger" onClick={() => handleDeleteTrack(track)}>DEL</button>
        </div>
      </td>
    </tr>
  );
});

function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

function clampWaveformBands(waveform: Partial<WaveformBands>): WaveformBands {
  const lengths = [
    waveform.low?.length ?? 0,
    waveform.mid?.length ?? 0,
    waveform.high?.length ?? 0,
    waveform.energy?.length ?? 0,
    waveform.transient?.length ?? 0,
  ].filter((length) => length > 0);

  if (lengths.length === 0) {
    return EMPTY_WAVEFORM;
  }

  const size = Math.min(...lengths);
  return {
    low: (waveform.low ?? []).slice(0, size).map((value) => clamp01(Number(value) || 0)),
    mid: (waveform.mid ?? []).slice(0, size).map((value) => clamp01(Number(value) || 0)),
    high: (waveform.high ?? []).slice(0, size).map((value) => clamp01(Number(value) || 0)),
    energy: (waveform.energy ?? []).slice(0, size).map((value) => clamp01(Number(value) || 0)),
    transient: (waveform.transient ?? []).slice(0, size).map((value) => clamp01(Number(value) || 0)),
  };
}

function parseWaveform(track: Track | null): WaveformBands {
  if (!track?.waveformDataJson) {
    return EMPTY_WAVEFORM;
  }

  try {
    const parsed = JSON.parse(track.waveformDataJson) as
      | number[]
      | { bands?: Partial<WaveformBands> }
      | Partial<WaveformBands>;

    if (Array.isArray(parsed)) {
      const energy = parsed.map((value) => clamp01(Number(value) || 0));
      const transient = energy.map((value, index) => {
        const previous = energy[Math.max(0, index - 1)] ?? value;
        const next = energy[Math.min(energy.length - 1, index + 1)] ?? value;
        return clamp01(Math.abs(value - ((previous + next) * 0.5)) * 4.8);
      });

      return {
        low: energy.map((value, index) => clamp01(value * 0.82 + transient[index] * 0.08)),
        mid: energy.map((value) => clamp01(Math.pow(value, 1.08) * 0.64)),
        high: energy.map((value, index) => clamp01(Math.pow(value, 1.36) * 0.36 + transient[index] * 0.42)),
        energy,
        transient,
      };
    }

    if (parsed && typeof parsed === "object" && "bands" in parsed && parsed.bands) {
      return clampWaveformBands(parsed.bands);
    }

    if (parsed && typeof parsed === "object") {
      return clampWaveformBands(parsed);
    }

    return EMPTY_WAVEFORM;
  } catch {
    return EMPTY_WAVEFORM;
  }
}

function normalizeBpmForMatch(bpm: number, referenceBpm?: number | null): number {
  if (!Number.isFinite(bpm) || bpm <= 0) {
    return bpm;
  }

  const candidates = [bpm * 0.5, bpm, bpm * 2].filter((candidate) => Number.isFinite(candidate) && candidate > 0);
  if (!referenceBpm || !Number.isFinite(referenceBpm) || referenceBpm <= 0) {
    return bpm;
  }

  return candidates.reduce((best, candidate) => {
    const bestDelta = Math.abs(best - referenceBpm);
    const candidateDelta = Math.abs(candidate - referenceBpm);
    return candidateDelta < bestDelta ? candidate : best;
  }, bpm);
}

function buildBeatMarkers(track: Track | null, referenceBpm?: number | null): BeatMarker[] {
  const bpm = normalizeBpmForMatch(track?.bpm || 0, referenceBpm);
  if (!track?.bpm || !Number.isFinite(bpm) || bpm <= 0 || !Number.isFinite(track.durationSeconds) || track.durationSeconds <= 0) {
    return [];
  }

  const beatPeriodSeconds = 60 / bpm;
  if (!Number.isFinite(beatPeriodSeconds) || beatPeriodSeconds <= 0) {
    return [];
  }

  // Calculate the first beat index that ensures we start at or around 0s
  const offset = track.beatOffset || 0;
  const firstIndex = Math.ceil(-offset / beatPeriodSeconds);
  const markers: BeatMarker[] = [];

  for (let index = firstIndex; ; index += 1) {
    const timelineSeconds = Number((offset + index * beatPeriodSeconds).toFixed(3));
    if (timelineSeconds > track.durationSeconds) {
      break;
    }

    if (timelineSeconds >= 0) {
      markers.push({
        relativeSeconds: timelineSeconds,
        timelineSeconds,
        isBar: (index % 4 + 4) % 4 === 0,
      });
    }
  }

  return markers;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function normalizePhase(value: number): number {
  return ((value % 1) + 1) % 1;
}

function signedPhaseDelta(masterPhase: number, slavePhase: number): number {
  let delta = masterPhase - slavePhase;
  if (delta > 0.5) {
    delta -= 1;
  }
  if (delta < -0.5) {
    delta += 1;
  }
  return delta;
}

function getBeatTiming(track: Track | null) {
  if (!track?.bpm || !Number.isFinite(track.bpm) || track.bpm <= 0) {
    return null;
  }

  const period = 60 / track.bpm;
  if (!Number.isFinite(period) || period <= 0) {
    return null;
  }

  return {
    bpm: track.bpm,
    period,
    offset: track.beatOffset || 0,
    durationSeconds: track.durationSeconds || 0,
  };
}

function getSyncTiming(track: Track | null, referenceBpm?: number | null) {
  if (!track?.bpm || !Number.isFinite(track.bpm) || track.bpm <= 0) {
    return null;
  }

  const bpm = normalizeBpmForMatch(track.bpm, referenceBpm);
  const period = 60 / bpm;
  if (!Number.isFinite(period) || period <= 0) {
    return null;
  }

  return {
    bpm,
    period,
    offset: track.beatOffset || 0,
    durationSeconds: track.durationSeconds || 0,
  };
}

function computePhaseAlignedTargetTime(
  masterTime: number,
  masterTiming: { period: number; offset: number },
  slaveTiming: { period: number; offset: number },
  slaveTime: number,
) {
  const masterPhase = normalizePhase((masterTime - masterTiming.offset) / masterTiming.period);
  const nearestSlaveBeat = Math.round((slaveTime - slaveTiming.offset) / slaveTiming.period);
  return Math.max(0, slaveTiming.offset + (nearestSlaveBeat * slaveTiming.period) + (masterPhase * slaveTiming.period));
}

function computeBeatAlignedTargetTime(
  masterTime: number,
  masterTiming: { period: number; offset: number },
  slaveTiming: { period: number; offset: number },
) {
  const masterBeatIndex = Math.round((masterTime - masterTiming.offset) / masterTiming.period);
  return Math.max(0, slaveTiming.offset + (masterBeatIndex * slaveTiming.period));
}

const SYNC_PHASE_HARD_SNAP_SECONDS = 0.032;
const SYNC_PHASE_RATE_GAIN = 0.6;
const SYNC_PHASE_RATE_NUDGE_LIMIT = 0.03;
const SYNC_PLAYBACK_RATE_MIN = 0.94;
const SYNC_PLAYBACK_RATE_MAX = 1.06;

function clampMediaTime(time: number, durationSeconds: number): number {
  if (!Number.isFinite(time)) {
    return 0;
  }

  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    return Math.max(0, time);
  }

  return clamp(time, 0, Math.max(0, durationSeconds - 0.01));
}

function syncSlaveToMaster(
  masterAudio: HTMLAudioElement,
  slaveAudio: HTMLAudioElement,
  masterTrack: Track,
  slaveTrack: Track,
  setSlaveCurrentTime: (value: number) => void,
  _syncLeadSeconds: number,
) {
  const masterTiming = getSyncTiming(masterTrack, slaveTrack.bpm);
  const slaveTiming = getSyncTiming(slaveTrack, masterTrack.bpm);
  if (!masterTiming || !slaveTiming || !masterTrack.bpm || !slaveTrack.bpm) {
    slaveAudio.playbackRate = 1.0;
    return;
  }

  const baseRate = masterTiming.bpm / slaveTiming.bpm;
  const masterPhase = normalizePhase((masterAudio.currentTime - masterTiming.offset) / masterTiming.period);
  const slavePhase = normalizePhase((slaveAudio.currentTime - slaveTiming.offset) / slaveTiming.period);
  const phaseError = signedPhaseDelta(masterPhase, slavePhase);
  const phaseErrorRatio = phaseError * Math.max(masterTiming.period, slaveTiming.period) / Math.max(slaveTiming.period, 0.001);
  const rateNudge = clamp(phaseErrorRatio * SYNC_PHASE_RATE_GAIN, -SYNC_PHASE_RATE_NUDGE_LIMIT, SYNC_PHASE_RATE_NUDGE_LIMIT);
  slaveAudio.playbackRate = clamp(baseRate * (1 + rateNudge), SYNC_PLAYBACK_RATE_MIN, SYNC_PLAYBACK_RATE_MAX);
}

function snapSlaveToMaster(
  masterAudio: HTMLAudioElement,
  slaveAudio: HTMLAudioElement,
  masterTrack: Track,
  slaveTrack: Track,
  setSlaveCurrentTime: (value: number) => void,
  _syncLeadSeconds: number,
) {
  const masterTiming = getSyncTiming(masterTrack, slaveTrack.bpm);
  const slaveTiming = getSyncTiming(slaveTrack, masterTrack.bpm);
  if (!masterTiming || !slaveTiming || !masterTrack.bpm || !slaveTrack.bpm) {
    slaveAudio.playbackRate = 1.0;
    return;
  }

  const targetTime = clampMediaTime(
    computeBeatAlignedTargetTime(
      masterAudio.currentTime,
      masterTiming,
      slaveTiming,
    ),
    slaveTiming.durationSeconds,
  );

  slaveAudio.currentTime = targetTime;
  setSlaveCurrentTime(targetTime);
  slaveAudio.playbackRate = masterTiming.bpm / slaveTiming.bpm;
}

function trackStatusTone(status: string): string {
  switch (status.toLowerCase()) {
    case "ready":
      return "success";
    case "analyzing":
      return "warning";
    case "error":
      return "danger";
    default:
      return "neutral";
  }
}

function trackStatusLabel(status: string): string {
  switch (status.toLowerCase()) {
    case "ready":
      return "Ready";
    case "analyzing":
      return "Analyzing";
    case "error":
      return "Needs attention";
    default:
      return "Queued";
  }
}

function buildPairAssessment(trackA: Track | null, trackB: Track | null): { tone: string; title: string; summary: string } {
  if (!trackA || !trackB) {
    return {
      tone: "neutral",
      title: "Select a pair",
      summary: "Choose two ready tracks to unlock the render preview, cue planner, and studio guidance.",
    };
  }

  const bpmDelta = trackA.bpm && trackB.bpm ? Math.abs(trackA.bpm - trackB.bpm) : null;
  const harmonicMatch = trackA.camelotKey && trackB.camelotKey && trackA.camelotKey === trackB.camelotKey;

  if (bpmDelta !== null && bpmDelta <= 3 && harmonicMatch) {
    return {
      tone: "success",
      title: "Showcase-ready pairing",
      summary: "Tempo and harmonic fit are both strong. This pair is a good candidate for a clean interview demo render.",
    };
  }

  if (bpmDelta !== null && bpmDelta <= 6) {
    return {
      tone: "warning",
      title: "Playable with light correction",
      summary: "The blend should still work, but you will want to listen closely to phrasing and timing on the transition.",
    };
  }

  return {
    tone: "danger",
    title: "Advanced pairing",
    summary: "The BPM gap is wider, so keep this as a second-pass demo after you prepare an easier headline example.",
  };
}

function buildPracticeNotes(trackA: Track | null, trackB: Track | null): string[] {
  if (!trackA || !trackB) {
    return [
      "Lead with two tracks that sit close in BPM so your first demo feels controlled.",
      "Use the analyzer first when you want quick confidence before pushing tracks into the library.",
      "Render one strong export and keep it ready to play during the interview.",
    ];
  }

  const notes: string[] = [];
  const bpmDelta = trackA.bpm && trackB.bpm ? Math.abs(trackA.bpm - trackB.bpm) : null;

  if (bpmDelta !== null) {
    notes.push(
      bpmDelta <= 4
        ? `Tempo gap is only ${bpmDelta.toFixed(1)} BPM, so this pair is forgiving and interview-friendly.`
        : `Tempo gap is ${bpmDelta.toFixed(1)} BPM, so set a clean entry point and avoid rushing the handover.`,
    );
  }

  if (trackA.camelotKey && trackB.camelotKey) {
    notes.push(
      trackA.camelotKey === trackB.camelotKey
        ? `Both tracks land in ${trackA.camelotKey}, which lets you focus on phrasing, energy, and fade shape.`
        : `Keys move from ${trackA.camelotKey} to ${trackB.camelotKey}; listen for pad and vocal clashes before exporting.`,
    );
  }

  notes.push("Aim to bring Track B in on a fresh phrase, not mid-vocal or mid-drop.");
  notes.push("Keep one polished render as the hero output and use the cue planner as supporting proof of the AI workflow.");

  return notes;
}

function average(values: number[]): number {
  if (values.length === 0) {
    return 0;
  }

  return values.reduce((total, value) => total + value, 0) / values.length;
}

function averageRange(values: number[], startRatio: number, endRatio: number): number {
  if (values.length === 0) {
    return 0;
  }

  const start = clamp(Math.floor(values.length * startRatio), 0, Math.max(0, values.length - 1));
  const end = clamp(Math.ceil(values.length * endRatio), start + 1, values.length);
  return average(values.slice(start, end));
}

function parseCamelot(value: string | null): { number: number; mode: string } | null {
  if (!value) {
    return null;
  }

  const match = value.trim().toUpperCase().match(/^(\d{1,2})([AB])$/);
  if (!match) {
    return null;
  }

  const number = Number(match[1]);
  if (!Number.isFinite(number) || number < 1 || number > 12) {
    return null;
  }

  return { number, mode: match[2] };
}

function camelotCompatibility(left: string | null, right: string | null): { score: number; label: string } {
  const a = parseCamelot(left);
  const b = parseCamelot(right);
  if (!a || !b) {
    return { score: 0.55, label: "Key confidence is limited" };
  }

  const wheelDistance = Math.min(Math.abs(a.number - b.number), 12 - Math.abs(a.number - b.number));
  if (a.number === b.number && a.mode === b.mode) {
    return { score: 1, label: "Same Camelot key" };
  }

  if (a.number === b.number && a.mode !== b.mode) {
    return { score: 0.88, label: "Relative major/minor move" };
  }

  if (wheelDistance === 1 && a.mode === b.mode) {
    return { score: 0.82, label: "Adjacent harmonic move" };
  }

  if (wheelDistance <= 2) {
    return { score: 0.62, label: "Playable harmonic tension" };
  }

  return { score: 0.34, label: "Key clash risk" };
}

function trackEnergy(track: Track | null): number {
  return average(parseWaveform(track).energy);
}

function trackIntroEnergy(track: Track | null): number {
  return averageRange(parseWaveform(track).energy, 0, 0.18);
}

function trackOutroEnergy(track: Track | null): number {
  return averageRange(parseWaveform(track).energy, 0.72, 0.96);
}

function trackLowEnd(track: Track | null): number {
  return average(parseWaveform(track).low);
}

function classifyEnergy(track: Track | null): string {
  const energy = trackEnergy(track);
  if (energy >= 0.62) return "peak";
  if (energy >= 0.48) return "drive";
  if (energy >= 0.34) return "roll";
  return "warmup";
}

function cueSeconds(track: Track | null, role: "out" | "in"): number {
  if (!track?.durationSeconds || track.durationSeconds <= 0) {
    return role === "out" ? 24 : 32;
  }

  const phrase = track.bpm && track.bpm > 0 ? (60 / track.bpm) * 16 : 32;
  if (role === "out") {
    return clamp(track.durationSeconds - (phrase * 2), 16, Math.max(16, track.durationSeconds - 8));
  }

  return clamp(phrase, 8, Math.max(8, Math.min(track.durationSeconds - 12, 64)));
}

function buildTransitionCopilot(trackA: Track | null, trackB: Track | null) {
  const hasPair = Boolean(trackA && trackB);
  const bpmDelta = trackA?.bpm && trackB?.bpm ? Math.abs(trackA.bpm - trackB.bpm) : null;
  const tempoScore = bpmDelta === null ? 0.56 : clamp(1 - (bpmDelta / 14), 0.12, 1);
  const harmonic = camelotCompatibility(trackA?.camelotKey ?? null, trackB?.camelotKey ?? null);
  const energyA = trackEnergy(trackA);
  const energyB = trackEnergy(trackB);
  const energyDelta = Math.abs(energyA - energyB);
  const energyScore = clamp(1 - (energyDelta * 1.45), 0.16, 1);
  const phraseScore = hasPair ? 0.78 : 0.4;
  const lowClash = trackLowEnd(trackA) > 0.58 && trackLowEnd(trackB) > 0.58;
  const vocalRisk = averageRange(parseWaveform(trackA).mid, 0.66, 0.92) > 0.64 && averageRange(parseWaveform(trackB).mid, 0.05, 0.28) > 0.64;
  const overall = hasPair
    ? Math.round(((tempoScore * 0.3) + (harmonic.score * 0.28) + (energyScore * 0.24) + (phraseScore * 0.18)) * 100)
    : 0;
  const mixOut = cueSeconds(trackA, "out");
  const mixIn = cueSeconds(trackB, "in");
  const fadeBars = bpmDelta !== null && bpmDelta > 6 ? 8 : 16;
  const transitionStyle = lowClash
    ? "EQ swap with low-end handoff"
    : energyB > energyA + 0.12
      ? "energy lift into next drop"
      : energyA > energyB + 0.12
        ? "controlled cooldown blend"
        : "smooth phrase blend";

  const reasons = hasPair
    ? [
        bpmDelta === null ? "Tempo confidence is estimated from available metadata." : `Tempo gap is ${bpmDelta.toFixed(1)} BPM.`,
        harmonic.label,
        `Energy move: ${classifyEnergy(trackA)} to ${classifyEnergy(trackB)}.`,
        `Suggested style: ${transitionStyle}.`,
      ]
    : ["Load two analyzed tracks to unlock the copilot plan."];

  const risks = [
    lowClash ? "Bass clash risk: keep Deck B low EQ down until the handoff." : "Low-end handoff looks manageable.",
    vocalRisk ? "Midrange overlap risk: avoid a long vocal-on-vocal blend." : "No obvious midrange clash in the proposed window.",
    bpmDelta !== null && bpmDelta > 8 ? "Wide tempo gap: use this as an advanced demo only." : "Tempo range is interview-friendly.",
  ];

  return {
    overall,
    tempoScore,
    harmonicScore: harmonic.score,
    energyScore,
    phraseScore,
    mixOut,
    mixIn,
    fadeBars,
    transitionStyle,
    reasons,
    risks,
  };
}

function buildSetJourney(tracks: Track[]): Track[] {
  return [...tracks]
    .sort((a, b) => {
      const energyDelta = trackEnergy(a) - trackEnergy(b);
      if (Math.abs(energyDelta) > 0.04) {
        return energyDelta;
      }

      return (a.bpm ?? 0) - (b.bpm ?? 0);
    })
    .slice(0, 8);
}

function downloadBlob(blobUrl: string, fileName: string) {
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = fileName;
  link.click();
}

const PhaseMeter = React.memo(({ audioRef, bpm, beatOffset, isMaster, isSynced }: { audioRef: React.RefObject<HTMLAudioElement | null>, bpm: number, beatOffset: number, isMaster: boolean, isSynced: boolean }) => {
  const [currentBlock, setCurrentBlock] = useState(0);

  useEffect(() => {
    if (!audioRef) return;
    let animFrame: number;
    const update = () => {
      const audio = audioRef.current;
      if (audio) {
        const period = 60 / (bpm || 120);
        const phase = normalizePhase((audio.currentTime - beatOffset) / period);
        const block = Math.floor(phase * 4);
        setCurrentBlock(block);
      }
      animFrame = requestAnimationFrame(update);
    };
    update();
    return () => cancelAnimationFrame(animFrame);
  }, [audioRef, bpm, beatOffset]);

  return (
    <div className="phase-meter">
      {[0, 1, 2, 3].map(i => (
        <div 
          key={i} 
          className={`phase-block ${i === currentBlock ? 'active' : ''} ${i === currentBlock && isMaster ? 'master' : ''} ${i === currentBlock && isSynced ? 'synced' : ''}`} 
        />
      ))}
    </div>
  );
});

const TimeDisplay = React.memo(({ audioRef }: { audioRef: React.RefObject<HTMLAudioElement | null> }) => {
  const [time, setTime] = useState(0);

  useEffect(() => {
    let animFrame: number;
    const update = () => {
      const audio = audioRef.current;
      if (audio) {
        setTime(audio.currentTime);
      }
      animFrame = requestAnimationFrame(update);
    };
    update();
    return () => cancelAnimationFrame(animFrame);
  }, [audioRef]);

  return <strong className="precision-readout">{formatPreciseClock(time)}</strong>;
});


export default function App() {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authForm, setAuthForm] = useState<AuthFormState>({ email: "", password: "" });
  const [authPending, setAuthPending] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const [workspace, setWorkspace] = useState<WorkspaceSnapshot | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [libraryQuery, setLibraryQuery] = useState("");
  const [uploadPending, setUploadPending] = useState(false);
  const [uploadDragOver, setUploadDragOver] = useState(false);

  const [selectedDeckAId, setSelectedDeckAId] = useState("");
  const [dragOverA, setDragOverA] = useState(false);
  const [dragOverB, setDragOverB] = useState(false);
  const [selectedDeckBId, setSelectedDeckBId] = useState("");

  const libraryTracks = workspace?.tracks ?? [];
  const selectedTrackA = useMemo(() => libraryTracks.find((track) => track.id === selectedDeckAId) ?? null, [libraryTracks, selectedDeckAId]);
  const selectedTrackB = useMemo(() => libraryTracks.find((track) => track.id === selectedDeckBId) ?? null, [libraryTracks, selectedDeckBId]);
  const readyTracks = useMemo(() => libraryTracks.filter((track) => track.status.toLowerCase() === "ready"), [libraryTracks]);

  const [masterDeck, setMasterDeck] = useState<'A' | 'B' | null>(null);
  const [isSyncA, setIsSyncA] = useState(false);
  const [isSyncB, setIsSyncB] = useState(false);
  const [renderStyle, setRenderStyle] = useState("bass_swap");
  const [renderQuality, setRenderQuality] = useState<RenderQualityResult | null>(null);


  const effectiveBPMA = isSyncA && masterDeck === 'B' && selectedTrackB?.bpm
    ? normalizeBpmForMatch(selectedTrackA?.bpm ?? 0, selectedTrackB.bpm)
    : (selectedTrackA?.bpm ?? null);

  const effectiveBPMB = isSyncB && masterDeck === 'A' && selectedTrackA?.bpm
    ? normalizeBpmForMatch(selectedTrackB?.bpm ?? 0, selectedTrackA.bpm)
    : (selectedTrackB?.bpm ?? null);

  const [crossfader, setCrossfader] = useState(50);
  const [isPlayingA, setIsPlayingA] = useState(false);
  const [eqA, setEqA] = useState({ high: 0, mid: 0, low: 0, gain: 1 });
  const [eqB, setEqB] = useState({ high: 0, mid: 0, low: 0, gain: 1 });
  const audioNodesA = useRef<any>(null);
  const audioNodesB = useRef<any>(null);
  function getSyncLeadSeconds(): number {
    const latencies = [
      audioNodesA.current?.ctx?.baseLatency,
      audioNodesA.current?.ctx?.outputLatency,
      audioNodesB.current?.ctx?.baseLatency,
      audioNodesB.current?.ctx?.outputLatency,
    ]
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value > 0);

    const measuredLatency = latencies.length > 0 ? Math.max(...latencies) : 0.018;
    return clamp(measuredLatency + 0.008, 0.008, 0.05);
  }

  const initAudioContextNode = (audioElem: HTMLAudioElement, refStorage: any) => {
    if (!audioElem || refStorage.current) return;
    
    // We only create this ONCE per audio element
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    const source = ctx.createMediaElementSource(audioElem);
    
    const highFilter = ctx.createBiquadFilter();
    highFilter.type = "highshelf";
    highFilter.frequency.value = 3200;

    const midFilter = ctx.createBiquadFilter();
    midFilter.type = "peaking";
    midFilter.frequency.value = 1000;
    midFilter.Q.value = 0.5;

    const lowFilter = ctx.createBiquadFilter();
    lowFilter.type = "lowshelf";
    lowFilter.frequency.value = 320;

    const gainNode = ctx.createGain();

    source.connect(highFilter);
    highFilter.connect(midFilter);
    midFilter.connect(lowFilter);
    lowFilter.connect(gainNode);
    gainNode.connect(ctx.destination);

    refStorage.current = { ctx, highFilter, midFilter, lowFilter, gainNode };
  };

  useEffect(() => {
    if (audioNodesA.current) {
        audioNodesA.current.highFilter.gain.value = eqA.high;
        audioNodesA.current.midFilter.gain.value = eqA.mid;
        audioNodesA.current.lowFilter.gain.value = eqA.low;
        audioNodesA.current.gainNode.gain.value = eqA.gain;
    }
  }, [eqA]);

  useEffect(() => {
    if (audioNodesB.current) {
        audioNodesB.current.highFilter.gain.value = eqB.high;
        audioNodesB.current.midFilter.gain.value = eqB.mid;
        audioNodesB.current.lowFilter.gain.value = eqB.low;
        audioNodesB.current.gainNode.gain.value = eqB.gain;
    }
  }, [eqB]);

  const setEqAHigh = useCallback((v: number) => React.startTransition(() => setEqA(prev => ({ ...prev, high: v }))), []);
  const setEqAMid = useCallback((v: number) => React.startTransition(() => setEqA(prev => ({ ...prev, mid: v }))), []);
  const setEqALow = useCallback((v: number) => React.startTransition(() => setEqA(prev => ({ ...prev, low: v }))), []);
  const setEqAGain = useCallback((v: number) => React.startTransition(() => setEqA(prev => ({ ...prev, gain: v }))), []);

  const setEqBHigh = useCallback((v: number) => React.startTransition(() => setEqB(prev => ({ ...prev, high: v }))), []);
  const setEqBMid = useCallback((v: number) => React.startTransition(() => setEqB(prev => ({ ...prev, mid: v }))), []);
  const setEqBLow = useCallback((v: number) => React.startTransition(() => setEqB(prev => ({ ...prev, low: v }))), []);
  const setEqBGain = useCallback((v: number) => React.startTransition(() => setEqB(prev => ({ ...prev, gain: v }))), []);


  const [isPlayingB, setIsPlayingB] = useState(false);

  const startScrubbing = useCallback((e, audioRef, durationSeconds, zoomPxPerSec = 112) => {
    const audio = audioRef.current;
    if (!audio) return;

    e.preventDefault();
    e.stopPropagation();

    const target = e.currentTarget;
    const pointerId = e.pointerId;
    target.setPointerCapture?.(pointerId);

    // Use durationSeconds from metadata as a strong fallback
    const resolvedDuration = (durationSeconds && durationSeconds > 0)
      ? durationSeconds
      : (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0);

    const clampTime = (value) => {
      if (resolvedDuration <= 0) return Math.max(0, value);
      return Math.max(0, Math.min(value, resolvedDuration));
    };

    const startX = e.clientX;
    const rect = target.getBoundingClientRect();
    const initialTime = clampTime(
      audio.currentTime + (((e.clientX - rect.left) - (rect.width / 2)) / zoomPxPerSec),
    );

    const updateScrubPosition = (clientX) => {
      const deltaX = clientX - startX;
      const targetTime = clampTime(initialTime - (deltaX / zoomPxPerSec));
      if (Number.isFinite(targetTime)) {
        audio.currentTime = targetTime;
      }
    };

    updateScrubPosition(e.clientX);

    const onPointerMove = (ev) => {
      updateScrubPosition(ev.clientX);
    };

    const onPointerUp = () => {
      target.releasePointerCapture?.(pointerId);
      target.removeEventListener("pointermove", onPointerMove);
      target.removeEventListener("pointerup", onPointerUp);
      target.removeEventListener("pointercancel", onPointerUp);
    };

    target.addEventListener("pointermove", onPointerMove);
    target.addEventListener("pointerup", onPointerUp);
    target.addEventListener("pointercancel", onPointerUp);
  }, []);

  const zoomA = isSyncA && masterDeck === 'B' && selectedTrackA?.bpm && selectedTrackB?.bpm
    ? 112 * (selectedTrackA.bpm / selectedTrackB.bpm)
    : 112;

  const zoomB = isSyncB && masterDeck === 'A' && selectedTrackA?.bpm && selectedTrackB?.bpm
    ? 112 * (selectedTrackB.bpm / selectedTrackA.bpm)
    : 112;

  const handleScrubA = useCallback((e) => {
    startScrubbing(e, deckAAudioRef, selectedTrackA?.durationSeconds, zoomA);
  }, [startScrubbing, selectedTrackA?.durationSeconds, zoomA]);

  const handleScrubB = useCallback((e) => {
    startScrubbing(e, deckBAudioRef, selectedTrackB?.durationSeconds, zoomB);
  }, [startScrubbing, selectedTrackB?.durationSeconds, zoomB]);

  const [useManualRenderPlan, setUseManualRenderPlan] = useState(false);
  const [manualOverlayStartSeconds, setManualOverlayStartSeconds] = useState(24);
  const [manualRightStartSeconds, setManualRightStartSeconds] = useState(32);
  const [manualOverlayStartInput, setManualOverlayStartInput] = useState("0:24.000");
  const [manualRightStartInput, setManualRightStartInput] = useState("0:32.000");
  const [renderPending, setRenderPending] = useState(false);
  const [renderedMixUrl, setRenderedMixUrl] = useState<string | null>(null);
  const [renderedMixName, setRenderedMixName] = useState("mixerai-transition-reference.mp3");

  const [recommendationForm, setRecommendationForm] = useState<TransitionRecommendationRequest>({
    leftSetId: "",
    rightSetId: "",
    topK: 5,
  });


  const [recommendationPending, setRecommendationPending] = useState(false);
  const [recommendationError, setRecommendationError] = useState<string | null>(null);
  const [recommendationResults, setRecommendationResults] = useState<TransitionRecommendation[]>([]);

  const [analysisTrackA, setAnalysisTrackA] = useState<File | null>(null);
  const [analysisTrackB, setAnalysisTrackB] = useState<File | null>(null);
  const [analysisPending, setAnalysisPending] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<MixAnalysisResult | null>(null);
  const [deckACurrentTime, setDeckACurrentTime] = useState(0);
  const [deckBCurrentTime, setDeckBCurrentTime] = useState(0);
  const [deckACueTime, setDeckACueTime] = useState<number | null>(null);
  const [deckBCueTime, setDeckBCueTime] = useState<number | null>(null);
  const [deckASeekInput, setDeckASeekInput] = useState("0:00.000");
  const [deckBSeekInput, setDeckBSeekInput] = useState("0:00.000");
  const [previewTrackId, setPreviewTrackId] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewCurrentTime, setPreviewCurrentTime] = useState(0);

  const deckAAudioRef = useRef<HTMLAudioElement | null>(null);
  const deckBAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let active = true;

    const loadSession = async () => {
      try {
        const currentSession = await api.getSession();
        if (active) {
          setSession(currentSession);
        }
      } catch {
        if (active) {
          setSession({ isAuthenticated: false, displayName: null, email: null });
        }
      } finally {
        if (active) {
          setSessionLoading(false);
        }
      }
    };

    void loadSession();
    return () => {
      active = false;
    };
  }, []);

  // Beat lock sync keeps the slave locked to the master's beat grid while playing.
  useEffect(() => {
    let intervalId: number | undefined;

    const syncProcessor = () => {
      const audioA = deckAAudioRef.current;
      const audioB = deckBAudioRef.current;
      const syncReady = selectedTrackA && selectedTrackB && audioA && audioB;
      const leadSeconds = getSyncLeadSeconds();

      if (isSyncA && masterDeck === 'B' && syncReady) {
        syncSlaveToMaster(audioB, audioA, selectedTrackB, selectedTrackA, setDeckACurrentTime, leadSeconds);
      } else if (audioA) {
        audioA.playbackRate = 1.0;
      }

      if (isSyncB && masterDeck === 'A' && syncReady) {
        syncSlaveToMaster(audioA, audioB, selectedTrackA, selectedTrackB, setDeckBCurrentTime, leadSeconds);
      } else if (audioB) {
        audioB.playbackRate = 1.0;
      }
    };

    if (isSyncA || isSyncB) {
      syncProcessor();
      intervalId = window.setInterval(syncProcessor, 16);
    } else {
      const audioA = deckAAudioRef.current;
      const audioB = deckBAudioRef.current;
      if (audioA) {
        audioA.playbackRate = 1.0;
      }
      if (audioB) {
        audioB.playbackRate = 1.0;
      }
    }

    return () => {
      if (intervalId !== undefined) {
        window.clearInterval(intervalId);
      }
    };
  }, [isSyncA, isSyncB, masterDeck, selectedTrackA, selectedTrackB]);


  useEffect(() => {
    if (!session?.isAuthenticated) {
      setWorkspace(null);
      return;
    }

    void refreshWorkspace();
  }, [session?.isAuthenticated]);

  useEffect(() => {
    if (!workspace) {
      return;
    }

    const readyTracks = workspace.tracks.filter((track) => track.status.toLowerCase() === "ready");
    if (!selectedDeckAId && readyTracks[0]) {
      setSelectedDeckAId(readyTracks[0].id);
    }

    if (!selectedDeckBId && readyTracks[1]) {
      setSelectedDeckBId(readyTracks[1].id);
    }

    if (!recommendationForm.leftSetId && workspace.availableSetIds[0]) {
      setRecommendationForm({
        leftSetId: workspace.availableSetIds[0],
        rightSetId: workspace.availableSetIds[1] ?? workspace.availableSetIds[0],
        topK: 5,
      });
    }
  }, [workspace, selectedDeckAId, selectedDeckBId, recommendationForm.leftSetId]);

  useEffect(() => {
    if (deckAAudioRef.current) {
      deckAAudioRef.current.volume = (100 - crossfader) / 100;
    }

    if (deckBAudioRef.current) {
      deckBAudioRef.current.volume = crossfader / 100;
    }
  }, [crossfader, selectedDeckAId, selectedDeckBId]);

  useEffect(() => {
    if (!deckAAudioRef.current) {
      return;
    }

    deckAAudioRef.current.load();
    deckAAudioRef.current.currentTime = 0;
    setDeckACueTime(null);
    setIsPlayingA(false);
  }, [selectedDeckAId]);

  useEffect(() => {
    if (!deckBAudioRef.current) {
      return;
    }

    deckBAudioRef.current.load();
    deckBAudioRef.current.currentTime = 0;
    setDeckBCueTime(null);
    setIsPlayingB(false);
  }, [selectedDeckBId]);

  useEffect(() => {
    if (!notice) {
      return;
    }

    const timeout = window.setTimeout(() => setNotice(null), 5000);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  useEffect(() => {
    return () => {
      if (renderedMixUrl) {
        URL.revokeObjectURL(renderedMixUrl);
      }
    };
  }, [renderedMixUrl]);

  useEffect(() => {
    if (previewTrackId && previewAudioRef.current) {
      previewAudioRef.current.play().catch(() => {
        // Browser might block, that's okay
      });
    }
  }, [previewTrackId]);

  useEffect(() => {
    if (!session?.isAuthenticated) {
      return;
    }

    const hasActiveTracks = workspace?.tracks.some((track) => {
      const status = track.status.toLowerCase();
      return status === "pending" || status === "analyzing";
    });

    if (!hasActiveTracks) {
      return;
    }

    const interval = window.setInterval(() => {
      void refreshWorkspace(false);
    }, 3000);

    return () => window.clearInterval(interval);
  }, [session?.isAuthenticated, workspace]);

  async function refreshWorkspace(showSpinner = true) {
    if (showSpinner) {
      setWorkspaceLoading(true);
    }
    setWorkspaceError(null);

    try {
      const snapshot = await api.getWorkspace();
      startTransition(() => setWorkspace(snapshot));
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Workspace could not be loaded.");
    } finally {
      if (showSpinner) {
        setWorkspaceLoading(false);
      }
    }
  }

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthPending(true);
    setAuthError(null);

    try {
      const nextSession = authMode === "login"
        ? await api.login(authForm.email, authForm.password)
        : await api.register(authForm.email, authForm.password);

      setSession(nextSession);
      setNotice(authMode === "login" ? "Studio session unlocked." : "Account created. The studio is ready.");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Authentication failed.");
    } finally {
      setAuthPending(false);
    }
  }

  async function handleLogout() {
    await api.logout();
    setSession({ isAuthenticated: false, displayName: null, email: null });
    setWorkspace(null);
    setRecommendationResults([]);
    setAnalysisResult(null);
    setNotice("Signed out.");
  }

  async function handleUploadTrack(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }

    try {
      await uploadTracks(files);
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      event.target.value = "";
    }
  }

  async function uploadTracks(files: File[]) {
    const validFiles = files.filter((file) => file.size > 0);
    if (validFiles.length === 0) {
      setWorkspaceError("Choose one or more non-empty audio files before uploading.");
      return;
    }

    setUploadPending(true);
    setWorkspaceError(null);
    try {
      const uploadedNames: string[] = [];
      const failedUploads: string[] = [];

      for (const file of validFiles) {
        try {
          await api.uploadTrack(file);
          uploadedNames.push(file.name);
        } catch (error) {
          const reason = error instanceof Error ? error.message : "Upload failed.";
          failedUploads.push(`${file.name}: ${reason}`);
        }
      }

      if (uploadedNames.length > 0) {
        await refreshWorkspace(false);
        setNotice(
          uploadedNames.length === 1
            ? `Uploaded ${uploadedNames[0]}. Analysis has been queued.`
            : `Uploaded ${uploadedNames.length} tracks. Analysis has been queued.`,
        );
      }

      if (failedUploads.length > 0) {
        setWorkspaceError(
          failedUploads.length === 1
            ? failedUploads[0]
            : `${failedUploads.length} uploads failed. First issue: ${failedUploads[0]}`,
        );
      }
    } finally {
      setUploadPending(false);
    }
  }

  async function handleDroppedLibraryFiles(fileList: FileList | null) {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) {
      return;
    }

    await uploadTracks(files);
  }

  async function handleDeleteTrack(track: Track) {
    if (!window.confirm(`Delete "${track.title}" from the library?`)) {
      return;
    }

    try {
      await api.deleteTrack(track.id);
      setNotice(`Deleted ${track.title}.`);
      await refreshWorkspace(false);
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Delete failed.");
    }
  }

  async function handleRetryTrack(track: Track) {
    try {
      await api.retryTrackAnalysis(track.id);
      setNotice(`Re-queued analysis for ${track.title}.`);
      await refreshWorkspace(false);
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Retry failed.");
    }
  }

  async function handleRetryLibraryTracks() {
    setUploadPending(true); // Reuse spinner or just mark as busy
    try {
      await api.retryLibraryTracks();
      setNotice("Bulk re-analysis started for the entire library.");
      await refreshWorkspace(false);
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Bulk re-analysis failed.");
    } finally {
      setUploadPending(false);
    }
  }

  async function handleClearLibrary() {
    if (!window.confirm("ARE YOU SURE? This will DELETE ALL TRACKS from your library permanently!")) {
      return;
    }

    setUploadPending(true);
    try {
      await api.clearLibrary();
      setNotice("Library cleared successfully.");
      await refreshWorkspace(false);
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Failed to clear library.");
    } finally {
      setUploadPending(false);
    }
  }

  async function handleRenderMix() {
    if (!selectedDeckAId || !selectedDeckBId) {
      setWorkspaceError("Select a ready track on both decks before rendering.");
      return;
    }

    setRenderPending(true);
    setWorkspaceError(null);

    try {
      const request: RenderMixRequest = {
        trackAId: selectedDeckAId,
        trackBId: selectedDeckBId,
        overlayStartSeconds: useManualRenderPlan ? manualOverlayStartSeconds : null,
        rightStartSeconds: useManualRenderPlan ? manualRightStartSeconds : null,
        transitionStyle: renderStyle,
      };

      const response = await api.renderMix(request);
      
      // Convert base64 back to blob for playback
      const audioData = atob(response.base64Audio);
      const arrayBuffer = new ArrayBuffer(audioData.length);
      const view = new Uint8Array(arrayBuffer);
      for (let i = 0; i < audioData.length; i++) {
        view[i] = audioData.charCodeAt(i);
      }
      const blob = new Blob([arrayBuffer], { type: "audio/mpeg" });

      if (renderedMixUrl) {
        URL.revokeObjectURL(renderedMixUrl);
      }

      const blobUrl = URL.createObjectURL(blob);
      setRenderedMixUrl(blobUrl);
      setRenderedMixName(response.fileName);
      setRenderQuality(response.quality);

      setNotice("Mix rendered and verified. Analysis complete.");
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Mix render failed.");
    } finally {
      setRenderPending(false);
    }
  }

  async function handleRecommendationSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRecommendationPending(true);
    setRecommendationError(null);

    try {
      setRecommendationResults(await api.recommendTransitions(recommendationForm));
    } catch (error) {
      setRecommendationError(error instanceof Error ? error.message : "Recommendations failed.");
    } finally {
      setRecommendationPending(false);
    }
  }

  async function handleAnalyzeMix(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!analysisTrackA || !analysisTrackB) {
      setAnalysisError("Choose both source tracks before running the analyzer.");
      return;
    }

    setAnalysisPending(true);
    setAnalysisError(null);

    try {
      const result = await api.analyzeMix(analysisTrackA, analysisTrackB);
      setAnalysisResult(result);
      setNotice("Transition analysis completed. You can now preview the cue timings and apply them to the render plan.");
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "Analysis failed.");
    } finally {
      setAnalysisPending(false);
    }
  }

  function handleApplyAnalysisPlan() {
    if (!analysisResult) {
      return;
    }

    setUseManualRenderPlan(true);
    setManualOverlayStartSeconds(analysisResult.recommendation.overlayStartSeconds);
    setManualRightStartSeconds(analysisResult.recommendation.rightStartSeconds);
    setManualOverlayStartInput(formatPreciseClock(analysisResult.recommendation.overlayStartSeconds));
    setManualRightStartInput(formatPreciseClock(analysisResult.recommendation.rightStartSeconds));
    setNotice("Analyzer timings loaded into the manual render controls.");
  }

  const [colWidths, setColWidths] = useState({
    idx: 40,
    wave: 100,
    title: 250,
    artist: 150,
    bpm: 55,
    key: 55,
    time: 65,
    status: 75,
    act: 140
  });
  const [resizingCol, setResizingCol] = useState(null);

  useEffect(() => {
    if (!resizingCol) return;
    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - resizingCol.startX;
      // ONLY ALLOW RESIZING FOR TITLE, and with a safety limit
      if (resizingCol.col === 'title') {
        const newWidth = Math.max(resizingCol.startWidth + delta, 100);
        const maxWidth = 800; // Cap to prevent pushing others too far
        setColWidths(prev => ({ ...prev, title: Math.min(newWidth, maxWidth) }));
      }
    };
    const handleMouseUp = () => setResizingCol(null);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [resizingCol]);

  const startResizing = (col, e) => {
    e.preventDefault();
    setResizingCol({ col, startX: e.clientX, startWidth: colWidths[col] });
  };

  const filteredTracks = useMemo(() => {
    return libraryTracks.filter((track) => {
      const query = libraryQuery.trim().toLowerCase();
      if (!query) {
        return true;
      }

      return [
        track.title,
        track.artist ?? "",
        track.camelotKey ?? "",
        track.status,
      ].some((value) => value.toLowerCase().includes(query));
    });
  }, [libraryTracks, libraryQuery]);

  const deckAWaveform = useMemo(() => parseWaveform(selectedTrackA), [selectedTrackA]);
  const deckBWaveform = useMemo(() => parseWaveform(selectedTrackB), [selectedTrackB]);
  const deckABeatMarkers = useMemo(() => buildBeatMarkers(
    selectedTrackA,
    isSyncA && masterDeck === 'B' ? selectedTrackB?.bpm ?? null : null,
  ), [selectedTrackA, selectedTrackB?.bpm, isSyncA, masterDeck]);
  const deckBBeatMarkers = useMemo(() => buildBeatMarkers(
    selectedTrackB,
    isSyncB && masterDeck === 'A' ? selectedTrackA?.bpm ?? null : null,
  ), [selectedTrackB, selectedTrackA?.bpm, isSyncB, masterDeck]);
  const pairAssessment = useMemo(() => buildPairAssessment(selectedTrackA, selectedTrackB), [selectedTrackA, selectedTrackB]);
  const transitionCopilot = useMemo(() => buildTransitionCopilot(selectedTrackA, selectedTrackB), [selectedTrackA, selectedTrackB]);
  const setJourney = useMemo(() => buildSetJourney(readyTracks), [readyTracks]);

  const overlayMax = Math.max(0, Math.min((selectedTrackA?.durationSeconds ?? 90) - 8, 96));
  const rightStartMax = Math.max(0, Math.min((selectedTrackB?.durationSeconds ?? 90) - 12, 120));
  const profileName = workspace?.displayName ?? session?.displayName ?? session?.email ?? "MixerAI";
  const bpmDelta = selectedTrackA?.bpm && selectedTrackB?.bpm
    ? Math.abs(selectedTrackA.bpm - selectedTrackB.bpm)
    : null;

  useEffect(() => {
    const nextOverlay = clamp(manualOverlayStartSeconds, 0, overlayMax);
    const nextRight = clamp(manualRightStartSeconds, 0, rightStartMax);

    setManualOverlayStartSeconds(nextOverlay);
    setManualRightStartSeconds(nextRight);
    setManualOverlayStartInput(formatPreciseClock(nextOverlay));
    setManualRightStartInput(formatPreciseClock(nextRight));
  }, [overlayMax, rightStartMax]);

  useEffect(() => {
    setDeckACurrentTime(0);
    setDeckASeekInput("0:00.000");
  }, [selectedDeckAId]);

  useEffect(() => {
    setDeckBCurrentTime(0);
    setDeckBSeekInput("0:00.000");
  }, [selectedDeckBId]);

  function commitManualOverlayStartInput() {
    setUseManualRenderPlan(true);
    const parsed = parsePreciseSecondsInput(manualOverlayStartInput);
    const nextValue = clamp(parsed ?? manualOverlayStartSeconds, 0, overlayMax);
    setManualOverlayStartSeconds(nextValue);
    setManualOverlayStartInput(formatPreciseClock(nextValue));
  }

  function commitManualRightStartInput() {
    setUseManualRenderPlan(true);
    const parsed = parsePreciseSecondsInput(manualRightStartInput);
    const nextValue = clamp(parsed ?? manualRightStartSeconds, 0, rightStartMax);
    setManualRightStartSeconds(nextValue);
    setManualRightStartInput(formatPreciseClock(nextValue));
  }

  function applyDeckSeekPosition(
    audioRef: React.RefObject<HTMLAudioElement | null>,
    inputValue: string,
    fallbackDuration: number | undefined,
    setCurrentTime: (value: number) => void,
    setInputValue: (value: string) => void,
  ) {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }

    const parsed = parsePreciseSecondsInput(inputValue);
    const candidate = parsed ?? 0;
    const durationLimit = Number.isFinite(audio.duration) && audio.duration > 0
      ? audio.duration
      : (fallbackDuration ?? 0);
    const nextValue = durationLimit > 0 ? clamp(candidate, 0, durationLimit) : Math.max(0, candidate);

    audio.currentTime = nextValue;
    setCurrentTime(nextValue);
    setInputValue(formatPreciseClock(nextValue));
  }

  function handleSetCuePoint(
    audioRef: React.RefObject<HTMLAudioElement | null>,
    setPlaying: (value: boolean) => void,
    setCurrentTime: (value: number) => void,
    setInputValue: (value: string) => void,
    setCueTime: (value: number | null) => void,
  ) {
    const audio = audioRef.current;
    const nextCueTime = audio?.currentTime ?? 0;
    if (audio) {
      audio.pause();
      audio.currentTime = nextCueTime;
    }

    setPlaying(false);
    setCueTime(nextCueTime);
    setCurrentTime(nextCueTime);
    setInputValue(formatPreciseClock(nextCueTime));
  }

  function handleUseCurrentDeckTimesForRender() {
    const nextOverlay = clamp(deckACurrentTime, 0, overlayMax);
    const nextRight = clamp(deckBCurrentTime, 0, rightStartMax);

    setUseManualRenderPlan(true);
    setManualOverlayStartSeconds(nextOverlay);
    setManualRightStartSeconds(nextRight);
    setManualOverlayStartInput(formatPreciseClock(nextOverlay));
    setManualRightStartInput(formatPreciseClock(nextRight));
  }

  function handleApplyCopilotPlan() {
    const nextOverlay = clamp(transitionCopilot.mixOut, 0, overlayMax);
    const nextRight = clamp(transitionCopilot.mixIn, 0, rightStartMax);

    setUseManualRenderPlan(true);
    setManualOverlayStartSeconds(nextOverlay);
    setManualRightStartSeconds(nextRight);
    setManualOverlayStartInput(formatPreciseClock(nextOverlay));
    setManualRightStartInput(formatPreciseClock(nextRight));
    setNotice("Copilot cue plan loaded into the render controls.");
  }

  function togglePreview(trackId: string) {
    if (previewTrackId === trackId) {
      if (isPreviewing) {
        previewAudioRef.current?.pause();
        setIsPreviewing(false);
      } else {
        previewAudioRef.current?.play().catch(() => {});
        setIsPreviewing(true);
      }
    } else {
      setPreviewTrackId(trackId);
      setIsPreviewing(true);
      // We need to wait for src update, but autoPlay should handle it. 
      // To be safe, we can trigger play in a timeout or effect.
    }
  }

  function handlePreviewSeek(time: number) {
    if (previewAudioRef.current) {
      previewAudioRef.current.currentTime = time;
      setPreviewCurrentTime(time);
    }
  }

  function handleBuildInterviewDemo() {
    const candidates = readyTracks
      .flatMap((left, leftIndex) => readyTracks.slice(leftIndex + 1).map((right) => ({
        left,
        right,
        plan: buildTransitionCopilot(left, right),
      })))
      .sort((a, b) => b.plan.overall - a.plan.overall);

    const best = candidates[0];
    if (!best) {
      setWorkspaceError("Upload and analyze at least two tracks before building a demo.");
      return;
    }

    setSelectedDeckAId(best.left.id);
    setSelectedDeckBId(best.right.id);
    setUseManualRenderPlan(true);
    setManualOverlayStartSeconds(best.plan.mixOut);
    setManualRightStartSeconds(best.plan.mixIn);
    setManualOverlayStartInput(formatPreciseSeconds(best.plan.mixOut));
    setManualRightStartInput(formatPreciseSeconds(best.plan.mixIn));
    setNotice(`Demo pair selected: ${best.left.title} into ${best.right.title}. Render it when ready.`);
  }

  const activeTrackCount = libraryTracks.filter((track) => {
    const status = track.status.toLowerCase();
    return status === "pending" || status === "analyzing";
  }).length;

  if (sessionLoading) {
    return (
      <div className="app-state-screen">
        <div className="state-card">
          <p className="eyebrow">MixerAI</p>
          <h1>Loading studio</h1>
          <p>Checking your session and warming up the workspace.</p>
        </div>
      </div>
    );
  }

  if (!session?.isAuthenticated) {
    return (
      <div className="app-shell landing-shell">
        <main className="landing-grid">
          <section className="landing-copy">
            <p className="eyebrow">AI transition studio</p>
            <h1 className="brand-title">MixerAI</h1>
            <p className="hero-copy">
              A polished DJ workflow demo for interviews: prep your library, audition transitions, inspect cue timing, and export one clean showcase mix.
            </p>
            <div className="pill-row">
              {studioPills.map((pill) => (
                <span key={pill} className="pill">
                  {pill}
                </span>
              ))}
            </div>
            <div className="landing-panel-grid">
              <article className="surface mini-surface">
                <strong>Professional look</strong>
                <p>Dark studio styling, structured dashboards, and a product tone that reads better on a hiring panel.</p>
              </article>
              <article className="surface mini-surface">
                <strong>Real workflow</strong>
                <p>Track upload, analysis, deck pairing, cue planning, manual overrides, and MP3 export all sit in one flow.</p>
              </article>
              <article className="surface mini-surface">
                <strong>Demo output</strong>
                <p>Generate one render you can play instantly inside the app and export as your interview artifact.</p>
              </article>
            </div>
          </section>

          <section className="auth-surface surface">
            <div className="section-heading">
              <p className="eyebrow">Access</p>
              <h2>Open the studio</h2>
              <p>Use a simple demo account flow to get straight into the product experience.</p>
            </div>

            <div className="segmented-row">
              <button
                type="button"
                className={authMode === "login" ? "segmented-button active" : "segmented-button"}
                onClick={() => setAuthMode("login")}
              >
                Sign in
              </button>
              <button
                type="button"
                className={authMode === "register" ? "segmented-button active" : "segmented-button"}
                onClick={() => setAuthMode("register")}
              >
                Create account
              </button>
            </div>

            <form className="stack-form" onSubmit={handleAuthSubmit}>
              <label className="field">
                <span>Email</span>
                <input
                  value={authForm.email}
                  onChange={(event) => setAuthForm((current) => ({ ...current, email: event.target.value }))}
                  type="email"
                  placeholder="dj@example.com"
                  required
                />
              </label>
              <label className="field">
                <span>Password</span>
                <input
                  value={authForm.password}
                  onChange={(event) => setAuthForm((current) => ({ ...current, password: event.target.value }))}
                  type="password"
                  placeholder="At least 6 characters"
                  required
                />
              </label>
              {authError ? <div className="inline-message danger">{authError}</div> : null}
              <button type="submit" className="primary-button" disabled={authPending}>
                {authPending ? "Working..." : authMode === "login" ? "Enter workspace" : "Create demo account"}
              </button>
            </form>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="studio-topbar">
        <div className="brand-block">
          <span className="topbar-brand">MIXER AI</span>
          <span className="small-text">{profileName}</span>
        </div>
        <div className="topbar-actions flex-row">
          <button type="button" className="action-btn" onClick={() => refreshWorkspace()} disabled={workspaceLoading}>
            {workspaceLoading ? "REFRESHING" : "REFRESH"}
          </button>
          <button type="button" className="action-btn deck-assign" onClick={() => handleBuildInterviewDemo()}>
            BUILD DEMO
          </button>
          <button type="button" className="action-btn warn" onClick={() => handleLogout()}>
            LOGOUT
          </button>
        </div>
      </header>

      <main className="dashboard-shell">
        <section className="global-waveforms">
          <div className={`global-waveform-row ${dragOverA ? 'drag-over' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOverA(true); }}
            onDragLeave={() => setDragOverA(false)}
            onDrop={(e) => {
               e.preventDefault();
               setDragOverA(false);
               const trackId = e.dataTransfer.getData('text/plain');
               if (trackId) setSelectedDeckAId(trackId);
            }}
          >
            <WaveformCanvas 
              className="waveform-canvas" 
              samples={deckAWaveform} 
              beatMarkers={deckABeatMarkers}
              cueTimeSeconds={deckACueTime}
              accent="#EF233C" 
              background="transparent" 
              audioRef={deckAAudioRef}
              zoomPxPerSec={zoomA}
              durationSeconds={selectedTrackA?.durationSeconds}
              onPointerDown={handleScrubA}
            />
          </div>
          <div className={`global-waveform-row ${dragOverB ? 'drag-over' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOverB(true); }}
            onDragLeave={() => setDragOverB(false)}
            onDrop={(e) => {
               e.preventDefault();
               setDragOverB(false);
               const trackId = e.dataTransfer.getData('text/plain');
               if (trackId) setSelectedDeckBId(trackId);
            }}
          >
            <WaveformCanvas 
              className="waveform-canvas" 
              samples={deckBWaveform} 
              beatMarkers={deckBBeatMarkers}
              cueTimeSeconds={deckBCueTime}
              accent="#08B2E3" 
              background="transparent" 
              audioRef={deckBAudioRef}
              zoomPxPerSec={zoomB}
              durationSeconds={selectedTrackB?.durationSeconds}
              onPointerDown={handleScrubB}
            />
          </div>
        </section>

        <section className="decks-area">
          <article className="deck deck-a">
            <div className="deck-header">
              <span className="deck-id" style={{ color: 'var(--blue)' }}>1</span>
              <select value={selectedDeckAId} onChange={(e) => setSelectedDeckAId(e.target.value)}>
                <option value="">EMPTY</option>
                {readyTracks.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
              </select>
            </div>
            <div className="deck-body">
              <div className="deck-info">
                <h2 className="deck-title">{selectedTrackA?.title || "NO TRACK"}</h2>
                <span className="deck-artist">{selectedTrackA?.artist || "Artist Info"}</span>
                <div className="deck-control-strip">
                  <div className="deck-controls-row">
                    <div className="deck-controls-wrapper deck-controls-wrapper-mirrored">
                      <div className="transport-controls-group transport-controls-group-mirrored">
                        <button className={`cdj-btn cue ${deckACueTime !== null ? 'active' : ''}`} onClick={() => handleSetCuePoint(deckAAudioRef, setIsPlayingA, setDeckACurrentTime, setDeckASeekInput, setDeckACueTime)}>CUE</button>
                        <button className="cdj-btn play" onClick={() => { 
                          if(deckAAudioRef.current) { 
                            initAudioContextNode(deckAAudioRef.current, audioNodesA);

                            if (deckAAudioRef.current.paused) {
                              const nextStartTime = deckACueTime ?? deckAAudioRef.current.currentTime;
                              deckAAudioRef.current.currentTime = nextStartTime;
                              setDeckACurrentTime(nextStartTime);
                              setDeckASeekInput(formatPreciseClock(nextStartTime));

                              if (isSyncA && masterDeck === 'B' && deckBAudioRef.current && selectedTrackA?.bpm && selectedTrackB?.bpm) {
                               snapSlaveToMaster(deckBAudioRef.current, deckAAudioRef.current, selectedTrackB, selectedTrackA, setDeckACurrentTime, getSyncLeadSeconds());
                             }
                            }

                            deckAAudioRef.current.paused ? deckAAudioRef.current.play() : deckAAudioRef.current.pause(); 
                            if (audioNodesA.current?.ctx.state === 'suspended') audioNodesA.current.ctx.resume();
                          }
                        }}>
                          {isPlayingA ? "⏸" : "▶"}
                        </button>
                        <div className="sync-controls-group">
                          <button className={`master-btn ${masterDeck === 'A' ? 'active' : ''}`} onClick={() => {
                            const nextMaster = masterDeck === 'A' ? null : 'A';
                            setMasterDeck(nextMaster);
                            if (nextMaster === 'A' && isSyncB && deckAAudioRef.current && deckBAudioRef.current && selectedTrackA?.bpm && selectedTrackB?.bpm) {
                              snapSlaveToMaster(deckAAudioRef.current, deckBAudioRef.current, selectedTrackA, selectedTrackB, setDeckBCurrentTime, getSyncLeadSeconds());
                            }
                          }}>MASTER</button>
                          <button className={`sync-btn ${isSyncA ? 'active' : ''}`} onClick={() => {
                            const nextSync = !isSyncA;
                            setIsSyncA(nextSync);
                            if (nextSync && masterDeck === 'B' && deckAAudioRef.current && deckBAudioRef.current && selectedTrackA?.bpm && selectedTrackB?.bpm) {
                              snapSlaveToMaster(deckBAudioRef.current, deckAAudioRef.current, selectedTrackB, selectedTrackA, setDeckACurrentTime, getSyncLeadSeconds());
                            }
                          }}>SYNC</button>
                        </div>
                      </div>
                      <div className="eq-controls-group eq-controls-group-mirrored">
                        <Knob label="HIGH" min={-26} max={6} centerValue={0} value={eqA.high} onChange={setEqAHigh} />
                        <Knob label="MID" min={-26} max={6} centerValue={0} value={eqA.mid} onChange={setEqAMid} />
                        <Knob label="LOW" min={-26} max={6} centerValue={0} value={eqA.low} onChange={setEqALow} />
                        <GainSlider label="GAIN" min={0} max={2} value={eqA.gain} onChange={setEqAGain} />
                      </div>
                    </div>
                    <div className="deck-position-panel">
                      <div className="precision-row">
                        <span className="precision-label">Live</span>
                        <TimeDisplay audioRef={deckAAudioRef} />
                        <button type="button" className="action-btn" onClick={() => setDeckASeekInput(formatPreciseClock(deckAAudioRef.current?.currentTime || 0))}>NOW</button>
                      </div>
                      <div className="precision-row">
                        <span className="precision-label">Jump To</span>
                        <input
                          className="precision-input"
                          type="text"
                          inputMode="decimal"
                          value={deckASeekInput}
                          onChange={(e) => setDeckASeekInput(e.target.value)}
                          onBlur={() => applyDeckSeekPosition(deckAAudioRef, deckASeekInput, selectedTrackA?.durationSeconds, setDeckACurrentTime, setDeckASeekInput)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              applyDeckSeekPosition(deckAAudioRef, deckASeekInput, selectedTrackA?.durationSeconds, setDeckACurrentTime, setDeckASeekInput);
                            }
                          }}
                        />
                        <button type="button" className="action-btn" onClick={() => applyDeckSeekPosition(deckAAudioRef, deckASeekInput, selectedTrackA?.durationSeconds, setDeckACurrentTime, setDeckASeekInput)}>SET</button>
                      </div>
                    </div>
                  </div>
                </div>
                <audio
                  ref={deckAAudioRef}
                  src={selectedTrackA ? `/api/bff/library/audio/${selectedTrackA.id}` : undefined}
                  preload="auto"
                  style={{display: 'none'}}
                  onPlay={() => setIsPlayingA(true)}
                  onPause={() => setIsPlayingA(false)}
                  onSeeked={() => {
                    const nextTime = deckAAudioRef.current?.currentTime ?? 0;
                    setDeckACurrentTime(nextTime);
                  }}
                />
              </div>
              <div className="deck-stats deck-stats-mirrored">
                <div className="deck-overview-panel">
                  <div className="deck-overview-header">
                    <span>Overview</span>
                    <span>{deckACueTime !== null ? `Cue @ ${formatPreciseClock(deckACueTime)}` : "No cue set"}</span>
                  </div>
                  <MiniWaveform
                    samples={deckAWaveform}
                    durationSeconds={selectedTrackA?.durationSeconds || 0}
                    currentTime={deckACurrentTime}
                    isPreviewing={true}
                    beatMarkers={deckABeatMarkers}
                    cueTimeSeconds={deckACueTime}
                    fillWidth={true}
                    height={48}
                    onSeek={(time) => {
                      if (!deckAAudioRef.current) return;
                      deckAAudioRef.current.currentTime = time;
                      setDeckACurrentTime(time);
                      setDeckASeekInput(formatPreciseClock(time));
                    }}
                  />
                </div>
                <div className="deck-stat-box bpm">
                  <span>BPM</span>
                  <div className="stat-value">
                    <strong>{effectiveBPMA ? effectiveBPMA.toFixed(2) : "--"}</strong>
                    <PhaseMeter 
                      audioRef={deckAAudioRef}
                      bpm={selectedTrackA?.bpm || 120}
                      beatOffset={selectedTrackA?.beatOffset || 0}
                      isMaster={masterDeck === 'A'} 
                      isSynced={isSyncA} 
                    />
                  </div>
                </div>
                <div className="deck-stat-box">
                  <span>KEY</span>
                  <strong>{selectedTrackA?.camelotKey || "--"}</strong>
                </div>
              </div>
            </div>
          </article>

          <article className="mixer">
            <div className="mixer-section">
              <span className="mixer-title">CROSSFADER MIN / MAX</span>
              <div className="crossfader-container">
                <input 
                  className="crossfader-input" 
                  type="range" 
                  min="0" 
                  max="100" 
                  value={crossfader} 
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    React.startTransition(() => setCrossfader(val));
                  }} 
                />
              </div>
            </div>
            <div className="mixer-section">
              <span className="mixer-title">RENDER AI MIX</span>
               <label className="toggle-row">
                <span>Manual timing</span>
                <input 
                  type="checkbox" 
                  checked={useManualRenderPlan} 
                  onChange={(e) => {
                    const val = e.target.checked;
                    React.startTransition(() => setUseManualRenderPlan(val));
                  }} 
                />
              </label>

              <div className="precision-row" style={{ marginTop: '4px', marginBottom: '8px' }}>
                <span className="precision-label">Style</span>
                <select 
                  className="precision-input" 
                  value={renderStyle} 
                  onChange={(e) => {
                    const val = e.target.value;
                    React.startTransition(() => setRenderStyle(val));
                  }}
                  style={{ background: '#111', color: 'var(--blue)', border: '1px solid #333', fontSize: '10px', height: '22px' }}
                >
                  <option value="bass_swap">BASS SWAP (Club-style EQ)</option>
                  <option value="double_drop">DOUBLE DROP (Energy lift)</option>
                  <option value="echo_out">ECHO OUT (Wash-out exit)</option>
                  <option value="blend">SMOOTH BLEND</option>
                </select>
              </div>

              {useManualRenderPlan && (
                <div className="precision-panel">
                  <div className="precision-row">
                    <span className="precision-label">B into A</span>
                    <input
                      className="precision-input"
                      type="text"
                      inputMode="decimal"
                      value={manualOverlayStartInput}
                      onChange={(e) => setManualOverlayStartInput(e.target.value)}
                      onBlur={() => commitManualOverlayStartInput()}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          commitManualOverlayStartInput();
                        }
                      }}
                    />
                    <button type="button" className="action-btn" onClick={() => {
                      const nextValue = clamp(deckACurrentTime, 0, overlayMax);
                      setManualOverlayStartSeconds(nextValue);
                      setManualOverlayStartInput(formatPreciseClock(nextValue));
                    }}>A NOW</button>
                  </div>
                  <div className="precision-row">
                    <span className="precision-label">B start</span>
                    <input
                      className="precision-input"
                      type="text"
                      inputMode="decimal"
                      value={manualRightStartInput}
                      onChange={(e) => setManualRightStartInput(e.target.value)}
                      onBlur={() => commitManualRightStartInput()}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          commitManualRightStartInput();
                        }
                      }}
                    />
                    <button type="button" className="action-btn" onClick={() => {
                      const nextValue = clamp(deckBCurrentTime, 0, rightStartMax);
                      setManualRightStartSeconds(nextValue);
                      setManualRightStartInput(formatPreciseClock(nextValue));
                    }}>B NOW</button>
                  </div>
                  <div className="precision-row">
                    <span className="precision-hint">Presnosť: 0.001 s. Podporuje formát M:SS.mmm alebo sekundy.</span>
                  </div>
                  <div className="precision-row">
                    <button type="button" className="secondary-button" onClick={() => handleUseCurrentDeckTimesForRender()}>
                      USE DECK TIMES
                    </button>
                  </div>
                </div>
              )}
              <button 
                type="button" 
                className="primary-button" 
                onClick={() => {
                  setRenderQuality(null);
                  handleRenderMix();
                }} 
                disabled={renderPending || !selectedDeckAId || !selectedDeckBId}
                style={{ width: '100%', marginBottom: '0.5rem' }}
              >
                {renderPending ? "RENDERING & VERIFYING..." : "RENDER"}
              </button>

              {renderQuality && (
                <div className="quality-card" style={{ 
                  background: '#111', 
                  borderLeft: `3px solid ${renderQuality.score >= 75 ? 'var(--green)' : renderQuality.score >= 50 ? 'var(--gold)' : 'var(--red)'}`,
                  padding: '8px',
                  marginBottom: '10px',
                  fontSize: '11px'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <span style={{ color: 'var(--gray)' }}>QUALITY ASSESSMENT</span>
                    <strong style={{ color: renderQuality.score >= 75 ? 'var(--green)' : 'var(--gold)' }}>{renderQuality.score}/100 - {renderQuality.quality}</strong>
                  </div>
                  <p style={{ margin: '0 0 6px 0', color: '#fff' }}>{renderQuality.summary}</p>
                  {renderQuality.feedback.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: '15px', color: 'rgba(255,100,100,0.9)' }}>
                      {renderQuality.feedback.map((f, i) => <li key={i}>{f}</li>)}
                    </ul>
                  )}
                </div>
              )}

              {renderedMixUrl && renderQuality && (
                <div className="flex-row" style={{ width: '100%' }}>
                  <audio controls src={renderedMixUrl} style={{ width: '100%', height: '30px' }} />
                  <button className="action-btn" onClick={() => downloadBlob(renderedMixUrl, renderedMixName)}>EXPORT</button>
                </div>
              )}
            </div>
          </article>

          <article className="deck deck-b">
            <div className="deck-header">
              <span className="deck-id" style={{ color: 'var(--blue)' }}>2</span>
              <select value={selectedDeckBId} onChange={(e) => setSelectedDeckBId(e.target.value)}>
                <option value="">EMPTY</option>
                {readyTracks.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
              </select>
            </div>
            <div className="deck-body">
              <div className="deck-info">
                <h2 className="deck-title">{selectedTrackB?.title || "NO TRACK"}</h2>
                <span className="deck-artist">{selectedTrackB?.artist || "Artist Info"}</span>
                <div className="deck-control-strip">
                  <div className="deck-controls-row">
                    <div className="deck-controls-wrapper">
                      <div className="transport-controls-group">
                        <button className={`cdj-btn cue ${deckBCueTime !== null ? 'active' : ''}`} onClick={() => handleSetCuePoint(deckBAudioRef, setIsPlayingB, setDeckBCurrentTime, setDeckBSeekInput, setDeckBCueTime)}>CUE</button>
                        <button className="cdj-btn play" onClick={() => { 
                          if(deckBAudioRef.current) { 
                            initAudioContextNode(deckBAudioRef.current, audioNodesB);

                            if (deckBAudioRef.current.paused) {
                              const nextStartTime = deckBCueTime ?? deckBAudioRef.current.currentTime;
                              deckBAudioRef.current.currentTime = nextStartTime;
                              setDeckBCurrentTime(nextStartTime);
                              setDeckBSeekInput(formatPreciseClock(nextStartTime));

                              if (isSyncB && masterDeck === 'A' && deckAAudioRef.current && selectedTrackA?.bpm && selectedTrackB?.bpm) {
                               snapSlaveToMaster(deckAAudioRef.current, deckBAudioRef.current, selectedTrackA, selectedTrackB, setDeckBCurrentTime, getSyncLeadSeconds());
                             }
                            }

                            deckBAudioRef.current.paused ? deckBAudioRef.current.play() : deckBAudioRef.current.pause(); 
                            if (audioNodesB.current?.ctx.state === 'suspended') audioNodesB.current.ctx.resume();
                          }
                        }}>
                          {isPlayingB ? "⏸" : "▶"}
                        </button>
                        <div className="sync-controls-group">
                          <button className={`master-btn ${masterDeck === 'B' ? 'active' : ''}`} onClick={() => {
                            const nextMaster = masterDeck === 'B' ? null : 'B';
                            setMasterDeck(nextMaster);
                            if (nextMaster === 'B' && isSyncA && deckAAudioRef.current && deckBAudioRef.current && selectedTrackA?.bpm && selectedTrackB?.bpm) {
                              snapSlaveToMaster(deckBAudioRef.current, deckAAudioRef.current, selectedTrackB, selectedTrackA, setDeckACurrentTime, getSyncLeadSeconds());
                            }
                          }}>MASTER</button>
                          <button className={`sync-btn ${isSyncB ? 'active' : ''}`} onClick={() => {
                            const nextSync = !isSyncB;
                            setIsSyncB(nextSync);
                            if (nextSync && masterDeck === 'A' && deckAAudioRef.current && deckBAudioRef.current && selectedTrackA?.bpm && selectedTrackB?.bpm) {
                              snapSlaveToMaster(deckAAudioRef.current, deckBAudioRef.current, selectedTrackA, selectedTrackB, setDeckBCurrentTime, getSyncLeadSeconds());
                            }
                          }}>SYNC</button>
                        </div>
                      </div>
                      <div className="eq-controls-group">
                        <Knob label="HIGH" min={-26} max={6} centerValue={0} value={eqB.high} onChange={setEqBHigh} />
                        <Knob label="MID" min={-26} max={6} centerValue={0} value={eqB.mid} onChange={setEqBMid} />
                        <Knob label="LOW" min={-26} max={6} centerValue={0} value={eqB.low} onChange={setEqBLow} />
                        <GainSlider label="GAIN" min={0} max={2} value={eqB.gain} onChange={setEqBGain} />
                      </div>
                    </div>
                    <div className="deck-position-panel">
                      <div className="precision-row">
                        <span className="precision-label">Live</span>
                        <TimeDisplay audioRef={deckBAudioRef} />
                        <button type="button" className="action-btn" onClick={() => setDeckBSeekInput(formatPreciseClock(deckBAudioRef.current?.currentTime || 0))}>NOW</button>
                      </div>
                      <div className="precision-row">
                        <span className="precision-label">Jump To</span>
                        <input
                          className="precision-input"
                          type="text"
                          inputMode="decimal"
                          value={deckBSeekInput}
                          onChange={(e) => setDeckBSeekInput(e.target.value)}
                          onBlur={() => applyDeckSeekPosition(deckBAudioRef, deckBSeekInput, selectedTrackB?.durationSeconds, setDeckBCurrentTime, setDeckBSeekInput)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              applyDeckSeekPosition(deckBAudioRef, deckBSeekInput, selectedTrackB?.durationSeconds, setDeckBCurrentTime, setDeckBSeekInput);
                            }
                          }}
                        />
                        <button type="button" className="action-btn" onClick={() => applyDeckSeekPosition(deckBAudioRef, deckBSeekInput, selectedTrackB?.durationSeconds, setDeckBCurrentTime, setDeckBSeekInput)}>SET</button>
                      </div>
                    </div>
                  </div>
                </div>
                <audio
                  ref={deckBAudioRef}
                  src={selectedTrackB ? `/api/bff/library/audio/${selectedTrackB.id}` : undefined}
                  preload="auto"
                  style={{display: 'none'}}
                  onPlay={() => setIsPlayingB(true)}
                  onPause={() => setIsPlayingB(false)}
                  onSeeked={() => {
                    const nextTime = deckBAudioRef.current?.currentTime ?? 0;
                    setDeckBCurrentTime(nextTime);
                  }}
                />
              </div>
              <div className="deck-stats">
                <div className="deck-stat-box bpm">
                  <span>BPM</span>
                  <div className="stat-value">
                    <strong>{effectiveBPMB ? effectiveBPMB.toFixed(2) : "--"}</strong>
                    <PhaseMeter 
                      audioRef={deckBAudioRef}
                      bpm={selectedTrackB?.bpm || 120} 
                      beatOffset={selectedTrackB?.beatOffset || 0}
                      isMaster={masterDeck === 'B'} 
                      isSynced={isSyncB} 
                    />
                  </div>
                </div>
                <div className="deck-stat-box">
                  <span>KEY</span>
                  <strong>{selectedTrackB?.camelotKey || "--"}</strong>
                </div>
                <div className="deck-overview-panel">
                  <div className="deck-overview-header">
                    <span>Overview</span>
                    <span>{deckBCueTime !== null ? `Cue @ ${formatPreciseClock(deckBCueTime)}` : "No cue set"}</span>
                  </div>
                  <MiniWaveform
                    samples={deckBWaveform}
                    durationSeconds={selectedTrackB?.durationSeconds || 0}
                    currentTime={deckBCurrentTime}
                    isPreviewing={true}
                    beatMarkers={deckBBeatMarkers}
                    cueTimeSeconds={deckBCueTime}
                    fillWidth={true}
                    height={48}
                    onSeek={(time) => {
                      if (!deckBAudioRef.current) return;
                      deckBAudioRef.current.currentTime = time;
                      setDeckBCurrentTime(time);
                      setDeckBSeekInput(formatPreciseClock(time));
                    }}
                  />
                </div>
              </div>
            </div>
          </article>
        </section>

        <section className="browser-area">
          <aside className="browser-tree">
            <div className="tree-header">COLLECTION</div>
            <div className="tree-content">
              <div className="tree-item">Audio Library ({workspace?.readyTrackCount || 0})</div>
              <div className="tree-item">Analyzer Queue ({activeTrackCount})</div>
              <div className="tree-item" style={{ marginTop: '1rem', color: 'var(--gold)' }}>AI Reference Sets</div>
              {workspace?.availableSetIds.map(setId => (
                <div className="tree-item" key={setId} style={{ paddingLeft: '1rem' }}>- {setId}</div>
              ))}
            </div>
            <div className="tree-header" style={{ borderTop: '1px solid var(--panel-border)' }}>UPLOAD</div>
            <div
              className={`tree-content upload-dropzone ${uploadDragOver ? "drag-over" : ""}`}
              style={{ flex: 'none', padding: '1rem', background: 'var(--panel-strong)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}
              onDragOver={(e) => {
                e.preventDefault();
                setUploadDragOver(true);
              }}
              onDragLeave={(e) => {
                if (e.currentTarget.contains(e.relatedTarget as Node | null)) {
                  return;
                }
                setUploadDragOver(false);
              }}
              onDrop={async (e) => {
                e.preventDefault();
                setUploadDragOver(false);
                await handleDroppedLibraryFiles(e.dataTransfer.files);
              }}
            >
               <label className="upload-button" style={{ width: '100%', textAlign: 'center', justifyContent: 'center' }}>
                 {uploadPending ? "UPLOADING..." : "CHOOSE FILES"}
                 <input type="file" accept=".mp3,.wav,.flac,.m4a" multiple onChange={handleUploadTrack} disabled={uploadPending} />
               </label>
               <div className="upload-dropzone-hint">
                 Drag & drop audio files sem z Prieskumnika.
               </div>
                <button type="button" className="action-btn" style={{ width: '100%' }} onClick={() => handleRetryLibraryTracks()} disabled={uploadPending}>
                  REANALYZE LIBRARY
                </button>
                <button type="button" className="action-btn danger-btn" style={{ width: '100%', marginTop: '0.25rem' }} onClick={() => handleClearLibrary()} disabled={uploadPending}>
                  CLEAR LIBRARY
                </button>
            </div>
          </aside>

          <aside className="copilot-panel">
            <div className="copilot-header">
              <div>
                <span className="mixer-title">AI DJ COPILOT</span>
                <h2>{transitionCopilot.overall || "--"}%</h2>
              </div>
              <span className={`copilot-badge ${transitionCopilot.overall >= 78 ? "success" : transitionCopilot.overall >= 55 ? "warning" : "danger"}`}>
                {transitionCopilot.overall >= 78 ? "showcase" : transitionCopilot.overall >= 55 ? "workable" : "risky"}
              </span>
            </div>

            <div className="score-grid">
              <div>
                <span>Tempo</span>
                <strong>{Math.round(transitionCopilot.tempoScore * 100)}%</strong>
              </div>
              <div>
                <span>Key</span>
                <strong>{Math.round(transitionCopilot.harmonicScore * 100)}%</strong>
              </div>
              <div>
                <span>Energy</span>
                <strong>{Math.round(transitionCopilot.energyScore * 100)}%</strong>
              </div>
              <div>
                <span>Phrase</span>
                <strong>{Math.round(transitionCopilot.phraseScore * 100)}%</strong>
              </div>
            </div>

            <section className="copilot-section">
              <div className="tree-header">SMART MIX POINTS</div>
              <div className="cue-grid">
                <div>
                  <span>Mix out A</span>
                  <strong>{formatPreciseClock(transitionCopilot.mixOut)}</strong>
                </div>
                <div>
                  <span>Mix in B</span>
                  <strong>{formatPreciseClock(transitionCopilot.mixIn)}</strong>
                </div>
                <div>
                  <span>Fade</span>
                  <strong>{transitionCopilot.fadeBars} bars</strong>
                </div>
                <div>
                  <span>Style</span>
                  <strong>{transitionCopilot.transitionStyle}</strong>
                </div>
              </div>
              <button type="button" className="primary-button" onClick={() => handleApplyCopilotPlan()} disabled={!selectedTrackA || !selectedTrackB}>
                APPLY CUE PLAN
              </button>
            </section>

            <section className="copilot-section">
              <div className="tree-header">WHY IT WORKS</div>
              {transitionCopilot.reasons.map((reason) => (
                <div className="copilot-line" key={reason}>{reason}</div>
              ))}
            </section>

            <section className="copilot-section">
              <div className="tree-header">CLASH RADAR</div>
              {transitionCopilot.risks.map((risk) => (
                <div className="copilot-line risk" key={risk}>{risk}</div>
              ))}
            </section>

            <section className="copilot-section">
              <div className="tree-header">CORPUS RADAR</div>
              <form className="compact-form" onSubmit={handleRecommendationSubmit}>
                <select
                  value={recommendationForm.leftSetId}
                  onChange={(event) => setRecommendationForm((current) => ({ ...current, leftSetId: event.target.value }))}
                >
                  {workspace?.availableSetIds.map((setId) => <option key={setId} value={setId}>{setId}</option>)}
                </select>
                <select
                  value={recommendationForm.rightSetId}
                  onChange={(event) => setRecommendationForm((current) => ({ ...current, rightSetId: event.target.value }))}
                >
                  {workspace?.availableSetIds.map((setId) => <option key={setId} value={setId}>{setId}</option>)}
                </select>
                <button type="submit" className="secondary-button" disabled={recommendationPending || !recommendationForm.leftSetId || !recommendationForm.rightSetId}>
                  {recommendationPending ? "SCORING" : "FIND TRANSITIONS"}
                </button>
              </form>
              {recommendationError && <div className="copilot-line danger">{recommendationError}</div>}
              {recommendationResults.slice(0, 3).map((item) => (
                <div className="radar-result" key={`${item.leftSetId}-${item.leftSegmentIndex}-${item.rightSetId}-${item.rightSegmentIndex}`}>
                  <strong>{Math.round(item.probability * 100)}%</strong>
                  <span>A {formatPreciseClock(item.leftStartSeconds)} to B {formatPreciseClock(item.rightStartSeconds)}</span>
                </div>
              ))}
            </section>

            <section className="copilot-section">
              <div className="tree-header">SET JOURNEY</div>
              {setJourney.length === 0 && <div className="copilot-line">Analyze tracks to generate a warmup-to-peak running order.</div>}
              {setJourney.map((track, index) => (
                <button
                  type="button"
                  className="journey-row"
                  key={track.id}
                  onClick={() => {
                    setSelectedDeckAId(track.id);
                    const next = setJourney[index + 1] ?? setJourney[index - 1];
                    if (next) setSelectedDeckBId(next.id);
                  }}
                >
                  <span>{index + 1}</span>
                  <strong>{track.title}</strong>
                  <em>{classifyEnergy(track)}</em>
                </button>
              ))}
            </section>

            <section className="copilot-section">
              <div className="tree-header">DEEP ANALYZER</div>
              <form className="compact-form" onSubmit={handleAnalyzeMix}>
                <label className="mini-upload">
                  A source
                  <input type="file" accept=".mp3,.wav,.flac,.m4a" onChange={(event) => setAnalysisTrackA(event.target.files?.[0] ?? null)} />
                </label>
                <label className="mini-upload">
                  B source
                  <input type="file" accept=".mp3,.wav,.flac,.m4a" onChange={(event) => setAnalysisTrackB(event.target.files?.[0] ?? null)} />
                </label>
                <button type="submit" className="secondary-button" disabled={analysisPending}>
                  {analysisPending ? "ANALYZING" : "RUN FILE ANALYSIS"}
                </button>
                {analysisResult && (
                  <button type="button" className="action-btn deck-assign" onClick={() => handleApplyAnalysisPlan()}>
                    APPLY ANALYSIS
                  </button>
                )}
              </form>
              {analysisError && <div className="copilot-line danger">{analysisError}</div>}
            </section>
          </aside>

          <section
            className={`browser-list ${uploadDragOver ? 'upload-drag-over' : ''}`}
            onDragOver={(e) => {
              if (e.dataTransfer.files.length === 0) {
                return;
              }
              e.preventDefault();
              setUploadDragOver(true);
            }}
            onDragLeave={(e) => {
              if (e.currentTarget.contains(e.relatedTarget as Node | null)) {
                return;
              }
              setUploadDragOver(false);
            }}
            onDrop={async (e) => {
              if (e.dataTransfer.files.length === 0) {
                return;
              }
              e.preventDefault();
              setUploadDragOver(false);
              await handleDroppedLibraryFiles(e.dataTransfer.files);
            }}
          >
            <div className="list-toolbar">
              <input type="search" placeholder="Search Tracks..." value={libraryQuery} onChange={(e) => setLibraryQuery(e.target.value)} />
              <div>
                {notice && <span className="small-text" style={{ color: 'var(--success)', marginRight: '1rem' }}>{notice}</span>}
                {workspaceError && <span className="small-text" style={{ color: 'var(--danger)', marginRight: '1rem' }}>{workspaceError}</span>}
              </div>
            </div>
            <div className="table-wrapper">
              <table className="rb-table">
                <thead>
                  <tr>
                    <th style={{ width: colWidths.idx }}>#</th>
                    <th style={{ width: colWidths.wave }}>NAHLAD</th>
                    <th style={{ width: colWidths.title }}>
                      TRACK TITLE
                      <div className="resizer" onMouseDown={(e) => startResizing('title', e)} />
                    </th>
                    <th style={{ width: colWidths.artist }}>ARTIST</th>
                    <th style={{ width: colWidths.bpm }}>BPM</th>
                    <th style={{ width: colWidths.key }}>KEY</th>
                    <th style={{ width: colWidths.time }}>TIME</th>
                    <th style={{ width: colWidths.status }}>STATUS</th>
                    <th style={{ width: colWidths.act }}>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTracks.map((track, i) => (
                    <TrackRow 
                      key={track.id}
                      track={track}
                      index={i}
                      isSelected={track.id === selectedDeckAId || track.id === selectedDeckBId}
                      previewTrackId={previewTrackId}
                      previewCurrentTime={previewCurrentTime}
                      isPreviewing={isPreviewing}
                      togglePreview={togglePreview}
                      handlePreviewSeek={handlePreviewSeek}
                      setSelectedDeckAId={setSelectedDeckAId}
                      setSelectedDeckBId={setSelectedDeckBId}
                      handleRetryTrack={handleRetryTrack}
                      handleDeleteTrack={handleDeleteTrack}
                    />
                  ))}
                  {filteredTracks.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ textAlign: 'center', padding: '2rem', color: 'var(--muted)' }}>NO TRACKS FOUND</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </section>
      </main>

      {/* Hidden Preview Engine */}
      <audio 
        ref={previewAudioRef} 
        src={previewTrackId ? `/api/bff/library/audio/${previewTrackId}` : undefined}
        autoPlay
        onPlay={() => setIsPreviewing(true)}
        onPause={() => setIsPreviewing(false)}
        onTimeUpdate={() => setPreviewCurrentTime(previewAudioRef.current?.currentTime ?? 0)}
        onEnded={() => {
          setIsPreviewing(false);
          setPreviewTrackId(null);
          setPreviewCurrentTime(0);
        }}
      />
    </div>
  );
}

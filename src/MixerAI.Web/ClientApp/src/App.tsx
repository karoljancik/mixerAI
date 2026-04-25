// @ts-nocheck
import { startTransition, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
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

type AuthMode = "login" | "register";

type AuthFormState = {
  email: string;
  password: string;
};

const studioPills = ["ASP.NET Core BFF", "React + TypeScript", "Python audio engine", "Portfolio-ready demo"];

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

function buildBeatMarkers(track: Track | null): BeatMarker[] {
  if (!track?.bpm || !Number.isFinite(track.bpm) || track.bpm <= 0 || !Number.isFinite(track.durationSeconds) || track.durationSeconds <= 0) {
    return [];
  }

  const beatPeriodSeconds = 60 / track.bpm;
  if (!Number.isFinite(beatPeriodSeconds) || beatPeriodSeconds <= 0) {
    return [];
  }

  const totalBeats = Math.ceil(track.durationSeconds / beatPeriodSeconds) + 1;
  const markers: BeatMarker[] = [];

  for (let index = 0; index < totalBeats; index += 1) {
    const timelineSeconds = Number((index * beatPeriodSeconds).toFixed(3));
    if (timelineSeconds > track.durationSeconds) {
      break;
    }

    markers.push({
      relativeSeconds: timelineSeconds,
      timelineSeconds,
      isBar: index % 4 === 0,
    });
  }

  return markers;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
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

function downloadBlob(blobUrl: string, fileName: string) {
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = fileName;
  anchor.click();
}

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
  const [crossfader, setCrossfader] = useState(50);
  const [isPlayingA, setIsPlayingA] = useState(false);
  const [eqA, setEqA] = useState({ high: 0, mid: 0, low: 0, gain: 1 });
  const [eqB, setEqB] = useState({ high: 0, mid: 0, low: 0, gain: 1 });
  const audioNodesA = useRef<any>(null);
  const audioNodesB = useRef<any>(null);

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

  const [isPlayingB, setIsPlayingB] = useState(false);

  const startScrubbing = (e, audioRef, durationSeconds) => {
    const audio = audioRef.current;
    if (!audio) return;

    e.preventDefault();
    e.stopPropagation();

    const target = e.currentTarget;
    const pointerId = e.pointerId;
    target.setPointerCapture?.(pointerId);

    const startX = e.clientX;
    const startTime = audio.currentTime;
    const ZOOM_PX_PER_SEC = 112;
    const resolvedDuration = Number.isFinite(audio.duration) && audio.duration > 0
      ? audio.duration
      : (durationSeconds ?? 0);

    const clampTime = (value) => {
      if (resolvedDuration > 0) {
        return Math.max(0, Math.min(value, resolvedDuration));
      }

      return Math.max(0, value);
    };

    const updateScrubPosition = (clientX) => {
      const deltaX = clientX - startX;
      audio.currentTime = clampTime(startTime - (deltaX / ZOOM_PX_PER_SEC));
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
  };

  const [useManualRenderPlan, setUseManualRenderPlan] = useState(false);
  const [manualOverlayStartSeconds, setManualOverlayStartSeconds] = useState(24);
  const [manualRightStartSeconds, setManualRightStartSeconds] = useState(32);
  const [manualOverlayStartInput, setManualOverlayStartInput] = useState("24.000");
  const [manualRightStartInput, setManualRightStartInput] = useState("32.000");
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
  const [deckASeekInput, setDeckASeekInput] = useState("0.000");
  const [deckBSeekInput, setDeckBSeekInput] = useState("0.000");

  const deckAAudioRef = useRef<HTMLAudioElement | null>(null);
  const deckBAudioRef = useRef<HTMLAudioElement | null>(null);

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
    setIsPlayingA(false);
  }, [selectedDeckAId]);

  useEffect(() => {
    if (!deckBAudioRef.current) {
      return;
    }

    deckBAudioRef.current.load();
    deckBAudioRef.current.currentTime = 0;
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
    }, 7000);

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
    const retryableTracks = libraryTracks.filter((track) => track.status.toLowerCase() !== "analyzing");
    if (retryableTracks.length === 0) {
      setNotice("No tracks are available for re-analysis right now.");
      return;
    }

    try {
      await Promise.all(retryableTracks.map((track) => api.retryTrackAnalysis(track.id)));
      setNotice(`Queued re-analysis for ${retryableTracks.length} track(s).`);
      await refreshWorkspace(false);
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Bulk re-analysis failed.");
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
      };

      const blob = await api.renderMix(request);
      if (renderedMixUrl) {
        URL.revokeObjectURL(renderedMixUrl);
      }

      const blobUrl = URL.createObjectURL(blob);
      setRenderedMixUrl(blobUrl);
      setRenderedMixName(
        `${selectedTrackA?.title ?? "deck-a"}-to-${selectedTrackB?.title ?? "deck-b"}-showcase-mix.mp3`
          .toLowerCase()
          .replace(/[^a-z0-9.-]+/g, "-"),
      );
      setNotice("Mix preview rendered. You can audition it in-app and export the MP3.");
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
    setManualOverlayStartInput(formatPreciseSeconds(analysisResult.recommendation.overlayStartSeconds));
    setManualRightStartInput(formatPreciseSeconds(analysisResult.recommendation.rightStartSeconds));
    setNotice("Analyzer timings loaded into the manual render controls.");
  }

  const readyTracks = workspace?.tracks.filter((track) => track.status.toLowerCase() === "ready") ?? [];
  const libraryTracks = workspace?.tracks ?? [];
  const filteredTracks = libraryTracks.filter((track) => {
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

  const selectedTrackA = libraryTracks.find((track) => track.id === selectedDeckAId) ?? null;
  const selectedTrackB = libraryTracks.find((track) => track.id === selectedDeckBId) ?? null;
  const deckAWaveform = parseWaveform(selectedTrackA);
  const deckBWaveform = parseWaveform(selectedTrackB);
  const deckABeatMarkers = buildBeatMarkers(selectedTrackA);
  const deckBBeatMarkers = buildBeatMarkers(selectedTrackB);
  const pairAssessment = buildPairAssessment(selectedTrackA, selectedTrackB);
  const practiceNotes = buildPracticeNotes(selectedTrackA, selectedTrackB);

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
    setManualOverlayStartInput(formatPreciseSeconds(nextOverlay));
    setManualRightStartInput(formatPreciseSeconds(nextRight));
  }, [overlayMax, rightStartMax]);

  useEffect(() => {
    setDeckACurrentTime(0);
    setDeckASeekInput("0.000");
  }, [selectedDeckAId]);

  useEffect(() => {
    setDeckBCurrentTime(0);
    setDeckBSeekInput("0.000");
  }, [selectedDeckBId]);

  function commitManualOverlayStartInput() {
    setUseManualRenderPlan(true);
    const parsed = parsePreciseSecondsInput(manualOverlayStartInput);
    const nextValue = clamp(parsed ?? manualOverlayStartSeconds, 0, overlayMax);
    setManualOverlayStartSeconds(nextValue);
    setManualOverlayStartInput(formatPreciseSeconds(nextValue));
  }

  function commitManualRightStartInput() {
    setUseManualRenderPlan(true);
    const parsed = parsePreciseSecondsInput(manualRightStartInput);
    const nextValue = clamp(parsed ?? manualRightStartSeconds, 0, rightStartMax);
    setManualRightStartSeconds(nextValue);
    setManualRightStartInput(formatPreciseSeconds(nextValue));
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
    setInputValue(formatPreciseSeconds(nextValue));
  }

  function handleResetDeck(
    audioRef: React.RefObject<HTMLAudioElement | null>,
    setPlaying: (value: boolean) => void,
    setCurrentTime: (value: number) => void,
    setInputValue: (value: string) => void,
  ) {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }

    setPlaying(false);
    setCurrentTime(0);
    setInputValue("0.000");
  }

  function handleUseCurrentDeckTimesForRender() {
    const nextOverlay = clamp(deckACurrentTime, 0, overlayMax);
    const nextRight = clamp(deckBCurrentTime, 0, rightStartMax);

    setUseManualRenderPlan(true);
    setManualOverlayStartSeconds(nextOverlay);
    setManualRightStartSeconds(nextRight);
    setManualOverlayStartInput(formatPreciseSeconds(nextOverlay));
    setManualRightStartInput(formatPreciseSeconds(nextRight));
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
              accent="#08B2E3" 
              background="transparent" 
              audioRef={deckAAudioRef}
              durationSeconds={selectedTrackA?.durationSeconds}
              onPointerDown={(e) => startScrubbing(e, deckAAudioRef, selectedTrackA?.durationSeconds)}
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
              accent="#08B2E3" 
              background="transparent" 
              audioRef={deckBAudioRef}
              durationSeconds={selectedTrackB?.durationSeconds}
              onPointerDown={(e) => startScrubbing(e, deckBAudioRef, selectedTrackB?.durationSeconds)}
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
                        <button className="cdj-btn cue" onClick={() => handleResetDeck(deckAAudioRef, setIsPlayingA, setDeckACurrentTime, setDeckASeekInput)}>CUE</button>
                        <button className="cdj-btn play" onClick={() => { 
                          if(deckAAudioRef.current) { 
                            initAudioContextNode(deckAAudioRef.current, audioNodesA);
                            deckAAudioRef.current.paused ? deckAAudioRef.current.play() : deckAAudioRef.current.pause(); 
                            if (audioNodesA.current?.ctx.state === 'suspended') audioNodesA.current.ctx.resume();
                          }
                        }}>
                          {isPlayingA ? "⏸" : "▶"}
                        </button>
                      </div>
                      <div className="eq-controls-group eq-controls-group-mirrored">
                        <Knob label="HIGH" min={-26} max={6} centerValue={0} value={eqA.high} onChange={(v) => setEqA({...eqA, high: v})} />
                        <Knob label="MID" min={-26} max={6} centerValue={0} value={eqA.mid} onChange={(v) => setEqA({...eqA, mid: v})} />
                        <Knob label="LOW" min={-26} max={6} centerValue={0} value={eqA.low} onChange={(v) => setEqA({...eqA, low: v})} />
                        <GainSlider label="GAIN" min={0} max={2} value={eqA.gain} onChange={(v) => setEqA({...eqA, gain: v})} />
                      </div>
                    </div>
                    <div className="deck-position-panel">
                      <div className="precision-row">
                        <span className="precision-label">Live</span>
                        <strong className="precision-readout">{formatPreciseClock(deckACurrentTime)}</strong>
                        <button type="button" className="action-btn" onClick={() => setDeckASeekInput(formatPreciseSeconds(deckACurrentTime))}>NOW</button>
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
                  onTimeUpdate={() => setDeckACurrentTime(deckAAudioRef.current?.currentTime ?? 0)}
                  onSeeked={() => setDeckACurrentTime(deckAAudioRef.current?.currentTime ?? 0)}
                  onLoadedMetadata={() => setDeckACurrentTime(deckAAudioRef.current?.currentTime ?? 0)}
                />
              </div>
              <div className="deck-stats deck-stats-mirrored">
                <div className="deck-stat-box bpm">
                  <span>BPM</span>
                  <strong>{selectedTrackA?.bpm ? selectedTrackA.bpm.toFixed(2) : "--"}</strong>
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
                <input type="range" min="0" max="100" value={crossfader} onChange={(e) => setCrossfader(Number(e.target.value))} />
              </div>
            </div>
            <div className="mixer-section">
              <span className="mixer-title">RENDER AI MIX</span>
              <label className="toggle-row">
                <span>Manual timing</span>
                <input type="checkbox" checked={useManualRenderPlan} onChange={(e) => setUseManualRenderPlan(e.target.checked)} />
              </label>
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
                      setManualOverlayStartInput(formatPreciseSeconds(nextValue));
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
                      setManualRightStartInput(formatPreciseSeconds(nextValue));
                    }}>B NOW</button>
                  </div>
                  <div className="precision-row">
                    <span className="precision-hint">Presnost: 0.001 s. Hodnoty sa pri rendere posielaju ako desatinne sekundy.</span>
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
                onClick={() => handleRenderMix()} 
                disabled={renderPending || !selectedDeckAId || !selectedDeckBId}
                style={{ width: '100%', marginBottom: '0.5rem' }}
              >
                {renderPending ? "RENDERING..." : "RENDER"}
              </button>
              {renderedMixUrl && (
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
                        <button className="cdj-btn cue" onClick={() => handleResetDeck(deckBAudioRef, setIsPlayingB, setDeckBCurrentTime, setDeckBSeekInput)}>CUE</button>
                        <button className="cdj-btn play" onClick={() => { 
                          if(deckBAudioRef.current) { 
                            initAudioContextNode(deckBAudioRef.current, audioNodesB);
                            deckBAudioRef.current.paused ? deckBAudioRef.current.play() : deckBAudioRef.current.pause(); 
                            if (audioNodesB.current?.ctx.state === 'suspended') audioNodesB.current.ctx.resume();
                          }
                        }}>
                          {isPlayingB ? "⏸" : "▶"}
                        </button>
                      </div>
                      <div className="eq-controls-group">
                        <Knob label="HIGH" min={-26} max={6} centerValue={0} value={eqB.high} onChange={(v) => setEqB({...eqB, high: v})} />
                        <Knob label="MID" min={-26} max={6} centerValue={0} value={eqB.mid} onChange={(v) => setEqB({...eqB, mid: v})} />
                        <Knob label="LOW" min={-26} max={6} centerValue={0} value={eqB.low} onChange={(v) => setEqB({...eqB, low: v})} />
                        <GainSlider label="GAIN" min={0} max={2} value={eqB.gain} onChange={(v) => setEqB({...eqB, gain: v})} />
                      </div>
                    </div>
                    <div className="deck-position-panel">
                      <div className="precision-row">
                        <span className="precision-label">Live</span>
                        <strong className="precision-readout">{formatPreciseClock(deckBCurrentTime)}</strong>
                        <button type="button" className="action-btn" onClick={() => setDeckBSeekInput(formatPreciseSeconds(deckBCurrentTime))}>NOW</button>
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
                  onTimeUpdate={() => setDeckBCurrentTime(deckBAudioRef.current?.currentTime ?? 0)}
                  onSeeked={() => setDeckBCurrentTime(deckBAudioRef.current?.currentTime ?? 0)}
                  onLoadedMetadata={() => setDeckBCurrentTime(deckBAudioRef.current?.currentTime ?? 0)}
                />
              </div>
              <div className="deck-stats">
                <div className="deck-stat-box bpm">
                  <span>BPM</span>
                  <strong>{selectedTrackB?.bpm ? selectedTrackB.bpm.toFixed(2) : "--"}</strong>
                </div>
                <div className="deck-stat-box">
                  <span>KEY</span>
                  <strong>{selectedTrackB?.camelotKey || "--"}</strong>
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
            </div>
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
                    <th style={{ width: '30px' }}>#</th>
                    <th>TRACK TITLE</th>
                    <th>ARTIST</th>
                    <th style={{ width: '60px' }}>BPM</th>
                    <th style={{ width: '60px' }}>KEY</th>
                    <th style={{ width: '70px' }}>TIME</th>
                    <th style={{ width: '80px' }}>STATUS</th>
                    <th style={{ width: '150px' }}>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTracks.map((track, i) => (
                    <tr 
                      key={track.id} 
                      className={(track.id === selectedDeckAId || track.id === selectedDeckBId) ? 'selected' : ''}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData('text/plain', track.id);
                      }}
                    >
                      <td>{i + 1}</td>
                      <td>{track.title}</td>
                      <td className="small-text">{track.artist || "--"}</td>
                      <td>{track.bpm ? track.bpm.toFixed(1) : "--"}</td>
                      <td>{track.camelotKey || "--"}</td>
                      <td>{formatDuration(track.durationSeconds)}</td>
                      <td className="status-cell">{track.status}</td>
                      <td>
                        <div className="flex-row">
                          <button className="action-btn deck-assign" disabled={track.status.toLowerCase() !== "ready"} onClick={() => setSelectedDeckAId(track.id)}>1</button>
                          <button className="action-btn deck-assign" disabled={track.status.toLowerCase() !== "ready"} onClick={() => setSelectedDeckBId(track.id)}>2</button>
                          <button className="action-btn" disabled={track.status.toLowerCase() === "analyzing"} onClick={() => handleRetryTrack(track)}>RETRY</button>
                          <button className="action-btn danger" onClick={() => handleDeleteTrack(track)}>DEL</button>
                        </div>
                      </td>
                    </tr>
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
    </div>
  );
}

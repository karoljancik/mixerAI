export type SessionResponse = {
  isAuthenticated: boolean;
  displayName: string | null;
  email: string | null;
};

export type Track = {
  id: string;
  title: string;
  artist: string | null;
  bpm: number | null;
  beatOffset: number | null;
  camelotKey: string | null;
  durationSeconds: number;
  waveformDataJson: string | null;
  status: string;
  analysisAttempts: number;
  lastAnalysisError: string | null;
  lastAnalysisStartedAtUtc: string | null;
  lastAnalysisCompletedAtUtc: string | null;
  createdAtUtc: string;
};

export type WorkspaceSnapshot = {
  displayName: string;
  tracks: Track[];
  availableSetIds: string[];
  readyTrackCount: number;
  failedTrackCount: number;
  hasReadyLibrary: boolean;
};

export type TransitionRecommendation = {
  leftSetId: string;
  leftSegmentIndex: number;
  leftStartSeconds: number;
  rightSetId: string;
  rightSegmentIndex: number;
  rightStartSeconds: number;
  probability: number;
};

export type TransitionRecommendationRequest = {
  leftSetId: string;
  rightSetId: string;
  topK: number;
};

export type RenderQualityResult = {
  score: number;
  quality: string;
  summary: string;
  feedback: string[];
  metrics: Record<string, number>;
};

export type RenderMixRequest = {
  trackAId: string;
  trackBId: string;
  overlayStartSeconds?: number | null;
  rightStartSeconds?: number | null;
  transitionStyle?: string;
};

export type MixStudioRequest = {
  generatedTrackStyle: string;
  generatedTrackDurationSeconds: number;
  generatedTrackSeed: number | null;
};

export type BeatMarker = {
  relativeSeconds: number;
  timelineSeconds: number;
  isBar: boolean;
};

export type WaveformBands = {
  low: number[];
  mid: number[];
  high: number[];
  energy: number[];
  transient: number[];
};

export type MixTrackPreview = {
  label: string;
  durationSeconds: number;
  previewStartSeconds: number;
  previewDurationSeconds: number;
  bpm: number;
  beatPeriodSeconds: number;
  timelineOffsetSeconds: number;
  waveform: number[];
  beatMarkers: BeatMarker[];
};

export type MixRecommendationPreview = {
  overlayStartSeconds: number;
  transitionCueSeconds: number;
  rightStartSeconds: number;
  transitionStyle: string;
  leftBpm: number;
  rightBpm: number;
  tempoRatio: number;
  modelProbability: number;
  probability: number;
};

export type MixAnalysisResult = {
  recommendation: MixRecommendationPreview;
  trackA: MixTrackPreview;
  trackB: MixTrackPreview;
};

export type ApiError = {
  error?: string;
  title?: string;
  detail?: string;
};

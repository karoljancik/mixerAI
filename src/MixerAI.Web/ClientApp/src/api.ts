import type {
  ApiError,
  MixAnalysisResult,
  MixStudioRequest,
  SessionResponse,
  Track,
  TransitionRecommendation,
  TransitionRecommendationRequest,
  WorkspaceSnapshot,
} from "./types";

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as ApiError;
    return payload.error ?? payload.detail ?? payload.title ?? `Request failed with ${response.status}.`;
  } catch {
    return `Request failed with ${response.status}.`;
  }
}

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    credentials: "same-origin",
    ...init,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as T;
}

async function requestBlob(input: RequestInfo, init?: RequestInit): Promise<Blob> {
  const response = await fetch(input, {
    credentials: "same-origin",
    ...init,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return await response.blob();
}

export const api = {
  getSession(): Promise<SessionResponse> {
    return requestJson("/api/bff/auth/session");
  },

  login(email: string, password: string): Promise<SessionResponse> {
    return requestJson("/api/bff/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });
  },

  register(email: string, password: string): Promise<SessionResponse> {
    return requestJson("/api/bff/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });
  },

  async logout(): Promise<void> {
    const response = await fetch("/api/bff/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
  },

  getWorkspace(): Promise<WorkspaceSnapshot> {
    return requestJson("/api/bff/workspace");
  },

  getTracks(): Promise<Track[]> {
    return requestJson("/api/bff/library");
  },

  uploadTrack(file: File): Promise<Track> {
    const formData = new FormData();
    formData.append("file", file);

    return requestJson("/api/bff/library/upload", {
      method: "POST",
      body: formData,
    });
  },

  async deleteTrack(id: string): Promise<void> {
    const response = await fetch(`/api/bff/library/${id}`, {
      method: "DELETE",
      credentials: "same-origin",
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
  },

  async retryTrackAnalysis(id: string): Promise<void> {
    const response = await fetch(`/api/bff/library/${id}/retry-analysis`, {
      method: "POST",
      credentials: "same-origin",
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
  },

  renderMix(trackAId: string, trackBId: string): Promise<Blob> {
    return requestBlob("/api/bff/workspace/render-mix", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ trackAId, trackBId }),
    });
  },

  recommendTransitions(request: TransitionRecommendationRequest): Promise<TransitionRecommendation[]> {
    return requestJson("/api/bff/workspace/recommendations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });
  },

  generateTrack(request: MixStudioRequest): Promise<Blob> {
    return requestBlob("/api/bff/workspace/generate-track", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });
  },

  generateMiniMix(request: Pick<MixStudioRequest, "generatedTrackSeed">): Promise<Blob> {
    return requestBlob("/api/bff/workspace/generate-mini-mix", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        generatedTrackStyle: "liquid",
        generatedTrackDurationSeconds: 150,
        generatedTrackSeed: request.generatedTrackSeed,
      }),
    });
  },

  analyzeMix(trackA: File, trackB: File): Promise<MixAnalysisResult> {
    const formData = new FormData();
    formData.append("trackA", trackA);
    formData.append("trackB", trackB);

    return requestJson("/api/bff/workspace/analyze-mix", {
      method: "POST",
      body: formData,
    });
  },
};

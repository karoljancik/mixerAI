const form = document.querySelector(".mix-form");
const analyzeButton = document.querySelector("#analyze-mix-button");
const playPreviewButton = document.querySelector("#play-preview-button");
const stopPreviewButton = document.querySelector("#stop-preview-button");
const syncOffsetInput = document.querySelector("#sync-offset-input");
const overlayStartEditor = document.querySelector("#overlay-start-editor");
const rightStartEditor = document.querySelector("#right-start-editor");
const analysisPanel = document.querySelector("#mix-analysis-panel");
const analysisFeedback = document.querySelector("#analysis-feedback");
const overlayStartInput = document.querySelector("#OverlayStartSeconds");
const rightStartInput = document.querySelector("#RightStartSeconds");

const state = {
    analysis: null,
    trackAUrl: null,
    trackBUrl: null,
    trackAAudio: null,
    trackBAudio: null,
    previewTimer: null,
};

document.querySelectorAll(".file-picker-input").forEach((input) => {
    input.addEventListener("change", () => {
        const target = document.querySelector(`[data-file-name-for="${input.id}"]`);
        if (target) {
            const fileName = input.files && input.files.length > 0
                ? input.files[0].name
                : "No file selected";
            target.textContent = fileName;
        }

        stopPreview();
        analysisPanel.hidden = true;
        analysisFeedback.textContent = "";
    });
});

analyzeButton?.addEventListener("click", async () => {
    if (!form) {
        return;
    }

    const trackAInput = document.querySelector("#TrackA");
    const trackBInput = document.querySelector("#TrackB");
    if (!(trackAInput instanceof HTMLInputElement) || !(trackBInput instanceof HTMLInputElement)) {
        return;
    }

    if (!trackAInput.files?.length || !trackBInput.files?.length) {
        analysisFeedback.textContent = "Upload both tracks before analysis.";
        analysisPanel.hidden = false;
        return;
    }

    analysisFeedback.textContent = "Analyzing BPM, beat markers and AI transition candidate...";
    analysisPanel.hidden = false;

    const formData = new FormData(form);
    try {
        const response = await fetch("/Home/Analyze", {
            method: "POST",
            body: formData,
            headers: {
                "RequestVerificationToken": document.querySelector("input[name='__RequestVerificationToken']")?.value ?? "",
            },
        });

        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error ?? "Analysis failed.");
        }

        state.analysis = payload;
        resetAudioUrls(trackAInput.files[0], trackBInput.files[0]);
        applyRecommendedTiming(0, payload.recommendation.overlayStartSeconds);
        renderAnalysis(payload);
        analysisFeedback.textContent = "AI analysis loaded. Play the preview and nudge Track B if needed.";
    } catch (error) {
        analysisFeedback.textContent = error instanceof Error ? error.message : "Analysis failed.";
    }
});

syncOffsetInput?.addEventListener("input", () => {
    syncUiToRenderState();
});

overlayStartEditor?.addEventListener("input", () => {
    syncUiToRenderState();
});

rightStartEditor?.addEventListener("input", () => {
    syncUiToRenderState();
});

playPreviewButton?.addEventListener("click", async () => {
    if (!state.analysis || !state.trackAUrl || !state.trackBUrl) {
        return;
    }

    stopPreview();
    const timing = getManualTiming();
    const rightStart = timing.rightStartSeconds;
    const overlayStart = timing.overlayStartSeconds;

    state.trackAAudio = new Audio(state.trackAUrl);
    state.trackBAudio = new Audio(state.trackBUrl);
    state.trackAAudio.currentTime = 0;
    state.trackBAudio.currentTime = Math.max(0, rightStart);

    await state.trackAAudio.play();
    state.previewTimer = window.setTimeout(async () => {
        if (!state.trackBAudio) {
            return;
        }
        try {
            await state.trackBAudio.play();
        } catch {
        }
    }, Math.max(0, overlayStart * 1000));
});

stopPreviewButton?.addEventListener("click", () => {
    stopPreview();
});

function renderAnalysis(payload) {
    analysisPanel.hidden = false;
    setText("#metric-left-bpm", `${payload.recommendation.leftBpm.toFixed(2)} BPM`);
    setText("#metric-right-bpm", `${payload.recommendation.rightBpm.toFixed(2)} BPM`);
    setText("#metric-overlay-start", `${payload.recommendation.overlayStartSeconds.toFixed(2)}s`);
    setText("#metric-probability", `${(payload.recommendation.probability * 100).toFixed(1)}%`);
    setText("#track-a-meta", `Preview 0.00s - ${payload.trackA.previewDurationSeconds.toFixed(2)}s`);
    setText("#track-b-meta", `Source ${payload.trackB.previewStartSeconds.toFixed(2)}s, enters at ${payload.recommendation.overlayStartSeconds.toFixed(2)}s`);
    updateSyncReadout(0, payload.recommendation.overlayStartSeconds);
    renderTimelineScale(payload.trackA.previewDurationSeconds);
    renderWaveCanvas(document.querySelector("#track-a-canvas"), payload.trackA, payload.recommendation, 0, 0, false);
    renderWaveCanvas(document.querySelector("#track-b-canvas"), payload.trackB, payload.recommendation, 0, payload.recommendation.overlayStartSeconds, true);
}

function renderTimelineScale(durationSeconds) {
    const container = document.querySelector("#timeline-scale");
    if (!container) {
        return;
    }

    container.innerHTML = "";
    const ticks = Math.max(4, Math.floor(durationSeconds / 4));
    for (let index = 0; index <= ticks; index += 1) {
        const tick = document.createElement("div");
        tick.className = "scale-tick";
        const ratio = index / ticks;
        tick.style.left = `${ratio * 100}%`;
        const label = document.createElement("span");
        label.textContent = `${Math.round(ratio * durationSeconds)}s`;
        tick.appendChild(label);
        container.appendChild(tick);
    }
}

function renderWaveCanvas(canvas, track, recommendation, manualOffsetSeconds, overlayStartSeconds, shiftByTimeline) {
    if (!(canvas instanceof HTMLCanvasElement)) {
        return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
        return;
    }

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#050608";
    ctx.fillRect(0, 0, width, height);

    const baseline = height / 2;
    const waveColor = shiftByTimeline ? "#ff9f1c" : "#ffd166";
    const markerColor = shiftByTimeline ? "rgba(255, 122, 24, 0.85)" : "rgba(255, 209, 102, 0.8)";

    ctx.strokeStyle = "rgba(255,255,255,0.06)";
    ctx.beginPath();
    ctx.moveTo(0, baseline);
    ctx.lineTo(width, baseline);
    ctx.stroke();

    const offsetSeconds = shiftByTimeline
        ? overlayStartSeconds + manualOffsetSeconds
        : 0;
    const duration = Math.max(track.previewDurationSeconds + offsetSeconds, track.previewDurationSeconds, overlayStartSeconds + 24);

    ctx.fillStyle = waveColor;
    track.waveform.forEach((sample, index) => {
        const x = ((index / Math.max(1, track.waveform.length - 1)) * (track.previewDurationSeconds / duration) * width)
            + ((offsetSeconds / duration) * width);
        const amplitude = Math.max(2, sample * (height * 0.42));
        ctx.fillRect(x, baseline - amplitude, 2, amplitude * 2);
    });

    track.beat_markers.forEach((marker) => {
        const timelineSeconds = shiftByTimeline
            ? marker.timelineSeconds + manualOffsetSeconds
            : marker.timelineSeconds;
        const x = (timelineSeconds / duration) * width;
        ctx.strokeStyle = marker.isBar ? markerColor : "rgba(255,255,255,0.18)";
        ctx.lineWidth = marker.isBar ? 2 : 1;
        ctx.beginPath();
        ctx.moveTo(x, 10);
        ctx.lineTo(x, height - 10);
        ctx.stroke();
    });
}

function resetAudioUrls(trackAFile, trackBFile) {
    if (state.trackAUrl) {
        URL.revokeObjectURL(state.trackAUrl);
    }
    if (state.trackBUrl) {
        URL.revokeObjectURL(state.trackBUrl);
    }

    state.trackAUrl = URL.createObjectURL(trackAFile);
    state.trackBUrl = URL.createObjectURL(trackBFile);
}

function stopPreview() {
    if (state.previewTimer) {
        window.clearTimeout(state.previewTimer);
        state.previewTimer = null;
    }
    if (state.trackAAudio) {
        state.trackAAudio.pause();
        state.trackAAudio.currentTime = 0;
        state.trackAAudio = null;
    }
    if (state.trackBAudio) {
        state.trackBAudio.pause();
        state.trackBAudio.currentTime = 0;
        state.trackBAudio = null;
    }
}

function setText(selector, value) {
    const element = document.querySelector(selector);
    if (element) {
        element.textContent = value;
    }
}

function applyRecommendedTiming(offsetSeconds, overlayStartSeconds) {
    if (!state.analysis || !(overlayStartInput instanceof HTMLInputElement) || !(rightStartInput instanceof HTMLInputElement)) {
        return;
    }

    if (syncOffsetInput instanceof HTMLInputElement) {
        syncOffsetInput.value = offsetSeconds.toFixed(2);
    }
    if (overlayStartEditor instanceof HTMLInputElement) {
        overlayStartEditor.value = overlayStartSeconds.toFixed(2);
    }
    if (rightStartEditor instanceof HTMLInputElement) {
        rightStartEditor.value = Math.max(0, state.analysis.recommendation.rightStartSeconds + offsetSeconds).toFixed(2);
    }

    overlayStartInput.value = String(Math.max(0, overlayStartSeconds).toFixed(3));
    rightStartInput.value = String(Math.max(0, state.analysis.recommendation.rightStartSeconds + offsetSeconds).toFixed(3));
}

function syncUiToRenderState() {
    if (!state.analysis) {
        return;
    }

    const offsetSeconds = Number.parseFloat(syncOffsetInput?.value || "0");
    const overlayStartSeconds = Math.max(0, Number.parseFloat(overlayStartEditor?.value || "0"));
    const rightStartSeconds = Math.max(
        0,
        Number.parseFloat(rightStartEditor?.value || String(state.analysis.recommendation.rightStartSeconds)),
    );
    overlayStartInput.value = String(overlayStartSeconds.toFixed(3));
    rightStartInput.value = String(rightStartSeconds.toFixed(3));
    updateSyncReadout(offsetSeconds, overlayStartSeconds);
    renderWaveCanvas(
        document.querySelector("#track-b-canvas"),
        state.analysis.trackB,
        state.analysis.recommendation,
        rightStartSeconds - state.analysis.recommendation.rightStartSeconds,
        overlayStartSeconds,
        true,
    );
}

function getManualTiming() {
    const offsetSeconds = Number.parseFloat(syncOffsetInput?.value || "0");
    const overlayStartSeconds = Math.max(0, Number.parseFloat(overlayStartEditor?.value || "0"));
    const rightStartSeconds = Math.max(
        0,
        Number.parseFloat(rightStartEditor?.value || String(state.analysis?.recommendation?.rightStartSeconds ?? 0)),
    );
    return {
        offsetSeconds,
        overlayStartSeconds,
        rightStartSeconds,
    };
}

function updateSyncReadout(offsetSeconds, overlayStartSeconds) {
    if (!state.analysis) {
        return;
    }

    setText("#sync-offset-readout", `Offset ${offsetSeconds >= 0 ? "+" : ""}${offsetSeconds.toFixed(2)}s`);
    setText("#sync-overlay-readout", `Join at ${overlayStartSeconds.toFixed(2)}s`);
    setText("#sync-right-start-readout", `B source ${Number.parseFloat(rightStartEditor?.value || "0").toFixed(2)}s`);
}

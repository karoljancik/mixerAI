from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from array import array
from pathlib import Path

import torch

from beat_sync import beat_period_seconds
from modeling import FEATURE_KEYS, TransitionScorer, build_pair_vector
from prepare_dataset import build_segments, read_duration_seconds
from render_mix import (
    choose_best_transition,
    choose_best_transition_without_model,
    create_normalized_wav,
    extract_features_for_segments,
    refine_transition_candidate,
    try_load_model_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze two uploaded tracks for AI-guided mix preview")
    parser.add_argument("--track-a", required=True, help="Path to track A")
    parser.add_argument("--track-b", required=True, help="Path to track B")
    parser.add_argument("--model-path", required=True, help="Path to transition scorer checkpoint")
    parser.add_argument("--output-path", required=True, help="Where to write analysis JSON")
    parser.add_argument("--sample-rate", type=int, default=22050, help="Sample rate for feature extraction")
    parser.add_argument("--window-seconds", type=int, default=30, help="Segment window size")
    parser.add_argument("--hop-seconds", type=int, default=15, help="Segment hop size")
    parser.add_argument("--overlay-seconds", type=int, default=24, help="Overlap preview duration")
    parser.add_argument("--track-b-tail-seconds", type=int, default=24, help="Track B continuation after overlap")
    parser.add_argument("--min-ai-overlay-start-seconds", type=int, default=16, help="Earliest AI-selected B entry over A")
    parser.add_argument("--max-ai-overlay-start-seconds", type=int, default=40, help="Latest AI-selected B entry over A")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    track_a = create_normalized_wav(Path(args.track_a))
    track_b = create_normalized_wav(Path(args.track_b))

    try:
        duration_a = read_duration_seconds(track_a)
        duration_b = read_duration_seconds(track_b)
        if duration_a <= 0 or duration_b <= 0:
            raise RuntimeError("Both uploaded tracks must have a positive duration.")

        segments_a = build_segments(duration_a, args.window_seconds, args.hop_seconds)
        segments_b = build_segments(duration_b, args.window_seconds, args.hop_seconds)
        features_a = extract_features_for_segments(track_a, segments_a, args.sample_rate)
        features_b = extract_features_for_segments(track_b, segments_b, args.sample_rate)

        model_bundle = try_load_model_bundle(Path(args.model_path))
        if model_bundle is None:
            print(
                "warning=AI transition model is incompatible with the current feature set; using heuristic fallback.",
                file=sys.stderr,
            )
            candidate = choose_best_transition_without_model(
                segments_a,
                segments_b,
                features_a,
                features_b,
                preserve_track_a_from_start=True,
                min_ai_overlay_start_seconds=args.min_ai_overlay_start_seconds,
                max_ai_overlay_start_seconds=args.max_ai_overlay_start_seconds,
            )
        else:
            model, normalization_mean, normalization_std = model_bundle
            candidate = choose_best_transition(
                segments_a,
                segments_b,
                features_a,
                features_b,
                model,
                normalization_mean,
                normalization_std,
                preserve_track_a_from_start=True,
                min_ai_overlay_start_seconds=args.min_ai_overlay_start_seconds,
                max_ai_overlay_start_seconds=args.max_ai_overlay_start_seconds,
            )
        candidate = refine_transition_candidate(candidate)

        preview_duration = max(
            60.0,
            float(candidate["overlay_start_seconds"]) + float(args.overlay_seconds) + float(args.track_b_tail_seconds),
        )
        left_preview_duration = min(preview_duration, duration_a)
        right_preview_duration = min(max(30.0, float(args.overlay_seconds) + float(args.track_b_tail_seconds)), duration_b)

        payload = {
            "recommendation": {
                "overlay_start_seconds": round(float(candidate["overlay_start_seconds"]), 3),
                "right_start_seconds": round(float(candidate["right_start_seconds"]), 3),
                "left_bpm": round(float(candidate["left_bpm"]), 3),
                "right_bpm": round(float(candidate["right_bpm"]), 3),
                "tempo_ratio": round(float(candidate["tempo_ratio"]), 6),
                "model_probability": round(float(candidate["model_probability"]), 6),
                "probability": round(float(candidate["probability"]), 6),
            },
            "trackA": build_track_preview(
                label="Track A",
                wav_path=track_a,
                duration_seconds=duration_a,
                preview_start_seconds=0.0,
                preview_duration_seconds=left_preview_duration,
                bpm=float(candidate["left_bpm"]),
                timeline_offset_seconds=0.0,
            ),
            "trackB": build_track_preview(
                label="Track B",
                wav_path=track_b,
                duration_seconds=duration_b,
                preview_start_seconds=float(candidate["right_start_seconds"]),
                preview_duration_seconds=right_preview_duration,
                bpm=float(candidate["right_bpm"]),
                timeline_offset_seconds=float(candidate["overlay_start_seconds"]),
            ),
        }

        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"output_path={output_path}")
        return 0
    finally:
        track_a.unlink(missing_ok=True)
        track_b.unlink(missing_ok=True)
def build_track_preview(
    label: str,
    wav_path: Path,
    duration_seconds: float,
    preview_start_seconds: float,
    preview_duration_seconds: float,
    bpm: float,
    timeline_offset_seconds: float,
) -> dict:
    beat_markers = build_beat_markers(preview_duration_seconds, bpm, timeline_offset_seconds)
    waveform = extract_waveform_summary(
        wav_path=wav_path,
        start_seconds=preview_start_seconds,
        duration_seconds=preview_duration_seconds,
        bucket_count=280,
    )
    return {
        "label": label,
        "duration_seconds": round(duration_seconds, 3),
        "preview_start_seconds": round(preview_start_seconds, 3),
        "preview_duration_seconds": round(preview_duration_seconds, 3),
        "bpm": round(bpm, 3),
        "beat_period_seconds": round(beat_period_seconds(bpm), 6),
        "timeline_offset_seconds": round(timeline_offset_seconds, 3),
        "waveform": waveform,
        "beat_markers": beat_markers,
    }


def build_beat_markers(
    preview_duration_seconds: float,
    bpm: float,
    timeline_offset_seconds: float,
) -> list[dict]:
    beat_period = beat_period_seconds(bpm)
    if beat_period <= 0:
        return []

    markers: list[dict] = []
    total_beats = int(math.ceil(preview_duration_seconds / beat_period)) + 1
    for index in range(total_beats):
        relative_seconds = round(index * beat_period, 3)
        if relative_seconds > preview_duration_seconds:
            break
        markers.append(
            {
                "relative_seconds": relative_seconds,
                "timeline_seconds": round(timeline_offset_seconds + relative_seconds, 3),
                "is_bar": index % 4 == 0,
            }
        )
    return markers


def extract_waveform_summary(
    wav_path: Path,
    start_seconds: float,
    duration_seconds: float,
    bucket_count: int,
) -> list[float]:
    with wave.open(str(wav_path), "rb") as wav_file:
        frame_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        total_frames = wav_file.getnframes()

        start_frame = max(0, int(start_seconds * frame_rate))
        frame_count = min(total_frames - start_frame, max(1, int(duration_seconds * frame_rate)))
        wav_file.setpos(start_frame)
        raw_frames = wav_file.readframes(frame_count)

    if frame_count <= 0 or sample_width != 2:
        return [0.0] * bucket_count

    samples = array("h")
    samples.frombytes(raw_frames)
    if not samples:
        return [0.0] * bucket_count

    bucket_size = max(1, len(samples) // bucket_count)
    scale = max(1.0, max(abs(int(sample)) for sample in samples))
    buckets: list[float] = []

    for index in range(bucket_count):
        start = index * bucket_size
        end = min(len(samples), start + bucket_size)
        if start >= len(samples):
            buckets.append(0.0)
            continue
        window = samples[start:end]
        peak = max(abs(int(sample)) for sample in window) / scale if window else 0.0
        buckets.append(round(float(peak), 4))

    return buckets


if __name__ == "__main__":
    raise SystemExit(main())

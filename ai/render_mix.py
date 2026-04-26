from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import librosa
import numpy as np
import torch

from beat_sync import (
    beat_period_seconds,
    build_atempo_filters,
    combined_transition_rhythm_score,
    compute_tempo_ratio,
    normalize_dnb_bpm,
    snap_to_bar_grid,
)
from extract_features import extract_segment_features
from modeling import FEATURE_KEYS, TransitionScorer, build_pair_vector
from prepare_dataset import build_segments, read_duration_seconds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an AI-guided MP3 mix from two source tracks")
    parser.add_argument("--track-a", required=True, help="Path to the first source track")
    parser.add_argument("--track-b", required=True, help="Path to the second source track")
    parser.add_argument("--model-path", required=True, help="Path to the trained transition scorer")
    parser.add_argument("--output-path", required=True, help="Output MP3 path")
    parser.add_argument("--sample-rate", type=int, default=22050, help="Sample rate for feature extraction")
    parser.add_argument("--window-seconds", type=int, default=30, help="Segment window size")
    parser.add_argument("--hop-seconds", type=int, default=15, help="Segment hop size")
    parser.add_argument("--crossfade-seconds", type=int, default=12, help="Fade-out length for track A once both tracks overlap")
    parser.add_argument("--mix-lead-in-seconds", type=int, default=20, help="How much of track A plays solo before track B fades in")
    parser.add_argument("--track-b-fade-in-seconds", type=int, default=8, help="Fade-in length for track B")
    parser.add_argument("--overlay-seconds", type=int, default=24, help="How long tracks A and B overlap before track A drops out")
    parser.add_argument("--track-b-tail-seconds", type=int, default=24, help="How long track B continues after track A fades out")
    parser.add_argument("--min-ai-overlay-start-seconds", type=int, default=16, help="Earliest AI-selected start for track B over track A")
    parser.add_argument("--max-ai-overlay-start-seconds", type=int, default=40, help="Latest AI-selected start for track B over track A")
    parser.add_argument("--overlay-start-seconds", type=float, help="Optional manual override for when track B should enter over track A")
    parser.add_argument("--right-start-seconds", type=float, help="Optional manual override for where track B should start in its own source")
    parser.add_argument("--transition-style", type=str, default="bass_swap", help="Transition style (blend, bass_swap, double_drop, echo_out)")

    parser.add_argument(
        "--preserve-track-a-from-start",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Always start the rendered mix from the beginning of track A",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    source_track_a = Path(args.track_a)
    source_track_b = Path(args.track_b)
    output_path = Path(args.output_path)

    track_a = create_normalized_wav(source_track_a)
    track_b = create_normalized_wav(source_track_b)

    try:
        duration_a = read_duration_seconds(track_a)
        duration_b = read_duration_seconds(track_b)
        if duration_a <= 0 or duration_b <= 0:
            raise RuntimeError("Both source tracks must have a positive duration.")

        segments_a = build_segments(duration_a, args.window_seconds, args.hop_seconds)
        segments_b = build_segments(duration_b, args.window_seconds, args.hop_seconds)
        if not segments_a or not segments_b:
            raise RuntimeError("Failed to build segments for one or both tracks.")

        features_a = extract_features_for_segments(track_a, segments_a, args.sample_rate)
        features_b = extract_features_for_segments(track_b, segments_b, args.sample_rate)
        structure_a = analyze_track_structure(track_a, args.sample_rate)
        structure_b = analyze_track_structure(track_b, args.sample_rate)

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
                preserve_track_a_from_start=args.preserve_track_a_from_start,
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
                preserve_track_a_from_start=args.preserve_track_a_from_start,
                min_ai_overlay_start_seconds=args.min_ai_overlay_start_seconds,
                max_ai_overlay_start_seconds=args.max_ai_overlay_start_seconds,
            )
        candidate = refine_transition_candidate(candidate)
        transition_plan = build_transition_plan(
            candidate,
            structure_a,
            structure_b,
            preserve_track_a_from_start=args.preserve_track_a_from_start,
            min_ai_overlay_start_seconds=args.min_ai_overlay_start_seconds,
            max_ai_overlay_start_seconds=args.max_ai_overlay_start_seconds,
        )
        if args.overlay_start_seconds is not None:
            transition_plan["overlay_start_seconds"] = round(max(0.0, float(args.overlay_start_seconds)), 3)
            transition_plan["transition_cue_seconds"] = round(
                transition_plan["overlay_start_seconds"] + transition_plan["target_entry_lead_seconds"],
                3,
            )
        if args.right_start_seconds is not None:
            transition_plan["right_start_seconds"] = round(max(0.0, float(args.right_start_seconds)), 3)
            transition_plan["style"] = args.transition_style if args.transition_style != "blend" else "manual_blend"

        render_mix(
            track_a=track_a,
            track_b=track_b,
            output_path=output_path,
            overlay_start_seconds=transition_plan["overlay_start_seconds"],
            left_start_seconds=transition_plan["left_start_seconds"],
            right_start_seconds=transition_plan["right_start_seconds"],
            left_bpm=transition_plan["left_bpm"],
            right_bpm=transition_plan["right_bpm"],
            window_seconds=args.window_seconds,
            crossfade_seconds=args.crossfade_seconds,
            mix_lead_in_seconds=args.mix_lead_in_seconds,
            track_b_fade_in_seconds=args.track_b_fade_in_seconds,
            overlay_seconds=args.overlay_seconds,
            track_b_tail_seconds=args.track_b_tail_seconds,
            preserve_track_a_from_start=args.preserve_track_a_from_start,
            transition_plan=transition_plan,
        )

        print(f"overlay_start_seconds={transition_plan['overlay_start_seconds']:.3f}")
        print(f"left_start_seconds={transition_plan['left_start_seconds']:.3f}")
        print(f"right_start_seconds={transition_plan['right_start_seconds']:.3f}")
        print(f"transition_cue_seconds={transition_plan['transition_cue_seconds']:.3f}")
        print(f"left_bpm={transition_plan['left_bpm']:.3f}")
        print(f"right_bpm={transition_plan['right_bpm']:.3f}")
        print(f"tempo_ratio={transition_plan['tempo_ratio']:.6f}")
        print(f"transition_style={transition_plan['style']}")
        print(f"model_probability={transition_plan['model_probability']:.6f}")
        print(f"probability={transition_plan['probability']:.6f}")
        print(f"output_path={output_path}")
        return 0
    finally:
        track_a.unlink(missing_ok=True)
        track_b.unlink(missing_ok=True)


def try_load_model_bundle(model_path: Path) -> tuple[TransitionScorer, torch.Tensor, torch.Tensor] | None:
    try:
        checkpoint = torch.load(model_path, map_location="cpu")
        input_size = len(build_pair_vector([0.0] * len(FEATURE_KEYS), [0.0] * len(FEATURE_KEYS)))
        model = TransitionScorer(
            input_size=input_size,
            hidden_size=int(checkpoint.get("hidden_size", 64)),
            dropout=float(checkpoint.get("dropout", 0.2)),
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()

        normalization_mean = torch.tensor(checkpoint["normalization_mean"], dtype=torch.float32)
        normalization_std = torch.tensor(checkpoint["normalization_std"], dtype=torch.float32)
        if normalization_mean.numel() != input_size or normalization_std.numel() != input_size:
            raise ValueError("Checkpoint normalization vectors do not match the current input feature size.")
        return model, normalization_mean, normalization_std
    except (RuntimeError, KeyError, ValueError, TypeError):
        return None


def extract_features_for_segments(track_path: Path, segments: list, sample_rate: int) -> list[list[float]]:
    features: list[list[float]] = []
    for segment in segments:
        payload = extract_segment_features(
            source_path=track_path,
            start_seconds=float(segment.start_seconds),
            duration_seconds=float(segment.duration_seconds),
            sr=sample_rate, 
        )
        features.append([float(payload.get(key, 0.0)) for key in FEATURE_KEYS])
    return features


def analyze_track_structure(track_path: Path, sample_rate: int) -> dict:
    hop_length = 512
    y, sr = librosa.load(track_path, sr=sample_rate, mono=True)
    if y.size == 0:
        raise RuntimeError(f"Track analysis failed for {track_path.name}: empty waveform.")

    duration_seconds = float(y.shape[0] / sr)
    onset_envelope = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    tempo_value, beat_frames = librosa.beat.beat_track(onset_envelope=onset_envelope, sr=sr, hop_length=hop_length)
    raw_bpm = float(tempo_value[0]) if hasattr(tempo_value, "__len__") else float(tempo_value)
    bpm = normalize_dnb_bpm(raw_bpm)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)

    if beat_times.size < 24:
        fallback_period = beat_period_seconds(bpm if bpm > 0 else 174.0)
        beat_times = np.arange(0.0, max(duration_seconds, fallback_period), fallback_period, dtype=float)
        beat_frames = librosa.time_to_frames(beat_times, sr=sr, hop_length=hop_length)
    else:
        beat_frames = np.asarray(beat_frames, dtype=int)

    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    spectrum = np.abs(librosa.stft(y=y, n_fft=2048, hop_length=hop_length)) + 1e-9
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=2048)
    spectral_centroid = librosa.feature.spectral_centroid(S=spectrum, sr=sr)[0]

    low_band = np.mean(spectrum[frequencies <= 180.0], axis=0) if np.any(frequencies <= 180.0) else np.zeros_like(rms)
    mid_band = np.mean(spectrum[(frequencies > 180.0) & (frequencies <= 2500.0)], axis=0) if np.any((frequencies > 180.0) & (frequencies <= 2500.0)) else np.zeros_like(rms)
    high_band = np.mean(spectrum[frequencies > 2500.0], axis=0) if np.any(frequencies > 2500.0) else np.zeros_like(rms)

    beat_profile = []
    for index, beat_time in enumerate(beat_times.tolist()):
        frame_index = int(np.clip(librosa.time_to_frames(beat_time, sr=sr, hop_length=hop_length), 0, len(rms) - 1))
        start = max(0, frame_index - 2)
        end = min(len(rms), frame_index + 3)
        energy = float(np.mean(rms[start:end]))
        onset = float(np.mean(onset_envelope[start:end]))
        low_energy = float(np.mean(low_band[start:end]))
        mid_energy = float(np.mean(mid_band[start:end]))
        high_energy = float(np.mean(high_band[start:end]))
        centroid = float(np.mean(spectral_centroid[start:end]))
        total_band_energy = max(low_energy + mid_energy + high_energy, 1e-9)
        beat_profile.append(
            {
                "index": index,
                "time": round(float(beat_time), 3),
                "energy": energy,
                "onset": onset,
                "low_ratio": low_energy / total_band_energy,
                "high_ratio": high_energy / total_band_energy,
                "centroid": centroid,
            }
        )

    return {
        "duration_seconds": duration_seconds,
        "raw_bpm": raw_bpm,
        "bpm": bpm if bpm > 0 else 174.0,
        "beat_period_seconds": beat_period_seconds(bpm if bpm > 0 else 174.0),
        "beat_profile": beat_profile,
        "drop_cues": extract_drop_cues(beat_profile, duration_seconds),
        "exit_cues": extract_exit_cues(beat_profile, duration_seconds),
    }


def extract_drop_cues(beat_profile: list[dict], duration_seconds: float) -> list[dict]:
    cues: list[dict] = []
    if len(beat_profile) < 32 or duration_seconds <= 0:
        return cues

    for index in range(16, len(beat_profile) - 16):
        cue = beat_profile[index]
        pre_window = beat_profile[max(0, index - 8):index]
        post_window = beat_profile[index:min(len(beat_profile), index + 8)]
        if not pre_window or not post_window:
            continue

        pre_energy = average_metric(pre_window, "energy")
        post_energy = average_metric(post_window, "energy")
        pre_onset = average_metric(pre_window, "onset")
        post_onset = average_metric(post_window, "onset")
        pre_low = average_metric(pre_window, "low_ratio")
        post_low = average_metric(post_window, "low_ratio")

        energy_lift = max(0.0, post_energy - pre_energy)
        onset_lift = max(0.0, post_onset - pre_onset)
        bass_lift = max(0.0, post_low - pre_low)
        pre_quiet = max(0.0, 0.7 - pre_energy)
        phrase_weight = phrase_weight_for_beat(index)
        position = cue["time"] / duration_seconds
        position_weight = triangular_score(position, 0.42, 0.32)

        score = (
            (0.34 * energy_lift)
            + (0.22 * onset_lift)
            + (0.16 * bass_lift)
            + (0.16 * pre_quiet)
            + (0.12 * phrase_weight)
        ) * position_weight

        cues.append(
            {
                "time": cue["time"],
                "score": float(score),
                "beat_index": index,
                "energy_before": pre_energy,
                "energy_after": post_energy,
                "onset_before": pre_onset,
                "onset_after": post_onset,
                "low_before": pre_low,
                "low_after": post_low,
            }
        )

    return prune_cues(cues, minimum_beat_distance=16)


def extract_exit_cues(beat_profile: list[dict], duration_seconds: float) -> list[dict]:
    cues: list[dict] = []
    if len(beat_profile) < 24 or duration_seconds <= 0:
        return cues

    for index in range(16, len(beat_profile) - 8):
        cue = beat_profile[index]
        pre_window = beat_profile[max(0, index - 8):index]
        post_window = beat_profile[index:min(len(beat_profile), index + 8)]
        if not pre_window or not post_window:
            continue

        pre_energy = average_metric(pre_window, "energy")
        post_energy = average_metric(post_window, "energy")
        pre_onset = average_metric(pre_window, "onset")
        post_onset = average_metric(post_window, "onset")
        decay = max(0.0, pre_energy - post_energy)
        onset_decay = max(0.0, pre_onset - post_onset)
        phrase_weight = phrase_weight_for_beat(index)
        position = cue["time"] / duration_seconds
        position_weight = triangular_score(position, 0.68, 0.28)
        drive = min(1.0, pre_energy + (pre_onset * 0.35))

        score = (
            (0.34 * decay)
            + (0.18 * onset_decay)
            + (0.24 * phrase_weight)
            + (0.24 * drive)
        ) * position_weight

        cues.append(
            {
                "time": cue["time"],
                "score": float(score),
                "beat_index": index,
                "energy_before": pre_energy,
                "energy_after": post_energy,
                "onset_before": pre_onset,
                "onset_after": post_onset,
                "decay": decay,
            }
        )

    return prune_cues(cues, minimum_beat_distance=16)


def build_transition_plan(
    candidate: dict,
    structure_a: dict,
    structure_b: dict,
    preserve_track_a_from_start: bool,
    min_ai_overlay_start_seconds: int,
    max_ai_overlay_start_seconds: int,
) -> dict:
    left_bpm = float(structure_a.get("bpm") or candidate["left_bpm"])
    right_bpm = float(structure_b.get("bpm") or candidate["right_bpm"])
    tempo_ratio = float(compute_tempo_ratio(right_bpm, left_bpm))
    beat_period_a = max(beat_period_seconds(left_bpm), 0.333)
    beat_period_b = max(beat_period_seconds(right_bpm), 0.333)
    base_overlay = float(candidate["overlay_start_seconds"])
    base_right_start = float(candidate["right_start_seconds"])

    style_specs = [
        {"style": "double_drop", "lead_beats": 32, "tail_beats": 16, "late_exit_bias": 0.25},
        {"style": "bass_swap", "lead_beats": 64, "tail_beats": 24, "late_exit_bias": 0.12},
        {"style": "echo_out", "lead_beats": 32, "tail_beats": 16, "late_exit_bias": 0.0},
    ]

    exit_cues = structure_a.get("exit_cues") or [{
        "time": snap_to_bar_grid(base_overlay + (16 * beat_period_a), left_bpm),
        "score": 0.35,
        "energy_before": 0.55,
        "energy_after": 0.32,
        "decay": 0.23,
    }]
    drop_cues = structure_b.get("drop_cues") or [{
        "time": snap_to_bar_grid(base_right_start + (16 * beat_period_b), right_bpm),
        "score": 0.35,
        "energy_before": 0.3,
        "energy_after": 0.7,
        "onset_before": 0.25,
        "onset_after": 0.55,
        "low_before": 0.18,
        "low_after": 0.34,
    }]

    best_plan: dict | None = None
    best_score = float("-inf")

    for style_spec in style_specs:
        lead_beats = int(style_spec["lead_beats"])
        source_entry_lead_seconds = lead_beats * beat_period_b
        target_entry_lead_seconds = source_entry_lead_seconds / max(tempo_ratio, 1e-6)
        for exit_cue in exit_cues[:6]:
            transition_cue_seconds = float(exit_cue["time"])
            overlay_start_seconds = transition_cue_seconds - target_entry_lead_seconds
            if overlay_start_seconds < 0:
                continue
            if preserve_track_a_from_start and overlay_start_seconds < float(min_ai_overlay_start_seconds):
                continue
            if overlay_start_seconds > max(float(max_ai_overlay_start_seconds), structure_a["duration_seconds"] * 0.9):
                continue

            for drop_cue in drop_cues[:6]:
                right_start_seconds = float(drop_cue["time"]) - source_entry_lead_seconds
                if right_start_seconds < 0:
                    continue

                overlay_closeness = math.exp(-(abs(overlay_start_seconds - base_overlay) / 18.0))
                right_closeness = math.exp(-(abs(right_start_seconds - base_right_start) / 18.0))
                rhythm_score = combined_transition_rhythm_score(
                    transition_cue_seconds,
                    float(drop_cue["time"]),
                    left_bpm,
                    right_bpm,
                )
                tempo_match = 1.0 - min(abs(1.0 - tempo_ratio), 0.35) / 0.35
                style_bonus = compute_transition_style_bonus(style_spec["style"], exit_cue, drop_cue)
                candidate_score = (
                    (0.18 * float(candidate["probability"]))
                    + (0.18 * overlay_closeness)
                    + (0.16 * right_closeness)
                    + (0.18 * float(exit_cue["score"]))
                    + (0.18 * float(drop_cue["score"]))
                    + (0.07 * rhythm_score)
                    + (0.05 * max(0.0, tempo_match))
                )
                score = candidate_score + style_bonus + float(style_spec["late_exit_bias"]) * triangular_score(
                    transition_cue_seconds / max(structure_a["duration_seconds"], 1.0),
                    0.7,
                    0.25,
                )
                if score <= best_score:
                    continue

                best_score = score
                best_plan = {
                    "style": style_spec["style"],
                    "overlay_start_seconds": round(overlay_start_seconds, 3),
                    "transition_cue_seconds": round(transition_cue_seconds, 3),
                    "left_start_seconds": round(float(candidate["left_start_seconds"]), 3),
                    "right_start_seconds": round(right_start_seconds, 3),
                    "left_bpm": left_bpm,
                    "right_bpm": right_bpm,
                    "tempo_ratio": tempo_ratio,
                    "probability": float(score),
                    "model_probability": float(candidate["model_probability"]),
                    "source_entry_lead_seconds": round(source_entry_lead_seconds, 3),
                    "target_entry_lead_seconds": round(target_entry_lead_seconds, 3),
                    "tail_beats": style_spec["tail_beats"],
                }

    if best_plan is None:
        best_plan = {
            "style": "blend",
            "overlay_start_seconds": round(base_overlay, 3),
            "transition_cue_seconds": round(base_overlay + (16 * beat_period_a), 3),
            "left_start_seconds": round(float(candidate["left_start_seconds"]), 3),
            "right_start_seconds": round(base_right_start, 3),
            "left_bpm": left_bpm,
            "right_bpm": right_bpm,
            "tempo_ratio": tempo_ratio,
            "probability": float(candidate["probability"]),
            "model_probability": float(candidate["model_probability"]),
            "source_entry_lead_seconds": round(16 * beat_period_b, 3),
            "target_entry_lead_seconds": round(16 * beat_period_a, 3),
            "tail_beats": 8,
        }

    best_plan["overlay_start_seconds"] = round(snap_to_bar_grid(best_plan["overlay_start_seconds"], left_bpm), 3)
    best_plan["transition_cue_seconds"] = round(
        best_plan["overlay_start_seconds"] + best_plan["target_entry_lead_seconds"],
        3,
    )
    best_plan["right_start_seconds"] = round(
        snap_to_bar_grid(best_plan["right_start_seconds"], right_bpm),
        3,
    )
    best_plan["right_drop_seconds"] = round(
        best_plan["right_start_seconds"] + best_plan["source_entry_lead_seconds"],
        3,
    )
    return best_plan


def compute_transition_style_bonus(style: str, exit_cue: dict, drop_cue: dict) -> float:
    if style == "double_drop":
        drive_bonus = 0.08 * min(1.0, float(exit_cue.get("energy_before", 0.0)) + float(drop_cue.get("energy_after", 0.0)))
        return drive_bonus - (0.05 * float(exit_cue.get("decay", 0.0)))
    if style == "bass_swap":
        return (0.09 * float(drop_cue.get("low_after", 0.0))) + (0.06 * float(exit_cue.get("decay", 0.0)))
    if style == "echo_out":
        return (0.08 * float(exit_cue.get("decay", 0.0))) + (0.04 * float(drop_cue.get("onset_after", 0.0)))
    return 0.0


def average_metric(window: list[dict], key: str) -> float:
    if not window:
        return 0.0
    return float(sum(float(item.get(key, 0.0)) for item in window) / len(window))


def phrase_weight_for_beat(beat_index: int) -> float:
    if beat_index % 16 == 0:
        return 1.0
    if beat_index % 8 == 0:
        return 0.72
    if beat_index % 4 == 0:
        return 0.44
    return 0.18


def triangular_score(value: float, target: float, width: float) -> float:
    if width <= 0:
        return 1.0 if value == target else 0.0
    return max(0.0, 1.0 - (abs(value - target) / width))


def prune_cues(cues: list[dict], minimum_beat_distance: int) -> list[dict]:
    if not cues:
        return []

    sorted_cues = sorted(cues, key=lambda cue: float(cue["score"]), reverse=True)
    selected: list[dict] = []
    for cue in sorted_cues:
        beat_index = int(cue.get("beat_index", 0))
        if any(abs(beat_index - int(existing.get("beat_index", 0))) < minimum_beat_distance for existing in selected):
            continue
        selected.append(cue)
        if len(selected) >= 8:
            break

    return sorted(selected, key=lambda cue: float(cue["time"]))


def choose_best_transition(
    segments_a: list,
    segments_b: list,
    features_a: list[list[float]],
    features_b: list[list[float]],
    model: TransitionScorer,
    normalization_mean: torch.Tensor,
    normalization_std: torch.Tensor,
    preserve_track_a_from_start: bool,
    min_ai_overlay_start_seconds: int,
    max_ai_overlay_start_seconds: int,
) -> dict:
    min_ai_overlay_start_seconds = max(0, int(min_ai_overlay_start_seconds))
    max_ai_overlay_start_seconds = max(min_ai_overlay_start_seconds + 1, int(max_ai_overlay_start_seconds))

    if preserve_track_a_from_start:
        left_start_threshold_seconds = float(min_ai_overlay_start_seconds)
        left_end_threshold_seconds = float(max_ai_overlay_start_seconds)
    else:
        left_start_threshold_seconds = float(segments_a[len(segments_a) // 3].start_seconds)
        left_end_threshold_seconds = float(segments_a[max(len(segments_a) // 3, (len(segments_a) * 9) // 10 - 1)].start_seconds)

    right_start_threshold = len(segments_b) // 6
    right_end_threshold = max(right_start_threshold + 1, (len(segments_b) * 5) // 6)

    vectors: list[list[float]] = []
    metadata: list[dict] = []

    for left_index, left_segment in enumerate(segments_a):
        left_start_seconds = float(left_segment.start_seconds)
        if left_start_seconds < left_start_threshold_seconds:
            continue
        if left_start_seconds > left_end_threshold_seconds:
            continue

        for right_index, right_segment in enumerate(segments_b):
            if right_index < right_start_threshold:
                continue
            if right_index > right_end_threshold:
                continue

            model_probability_input = build_pair_vector(features_a[left_index], features_b[right_index])
            vectors.append(model_probability_input)
            metadata.append(
                {
                    "left_start_seconds": float(left_segment.start_seconds),
                    "right_start_seconds": float(right_segment.start_seconds),
                    "left_bpm": float(features_a[left_index][FEATURE_KEYS.index("estimated_bpm")]),
                    "right_bpm": float(features_b[right_index][FEATURE_KEYS.index("estimated_bpm")]),
                }
            )

    if not vectors:
        raise RuntimeError("No valid transition candidates were generated.")

    batch = torch.tensor(vectors, dtype=torch.float32)
    batch = (batch - normalization_mean) / normalization_std
    with torch.no_grad():
        probabilities = torch.sigmoid(model(batch)).squeeze(dim=1).tolist()

    reranked_probabilities = []
    for index, probability in enumerate(probabilities):
        metadata_item = metadata[index]
        rhythm_score = combined_transition_rhythm_score(
            metadata_item["left_start_seconds"],
            metadata_item["right_start_seconds"],
            metadata_item["left_bpm"],
            metadata_item["right_bpm"],
        )
        if preserve_track_a_from_start:
            transition_bias = compute_intro_overlay_bias(
                metadata_item["left_start_seconds"],
                metadata_item["right_start_seconds"],
                segments_b[-1].end_seconds,
                min_ai_overlay_start_seconds,
                max_ai_overlay_start_seconds,
            )
        else:
            transition_bias = compute_mid_mix_bias(
                metadata_item["left_start_seconds"],
                metadata_item["right_start_seconds"],
                segments_a[-1].end_seconds,
                segments_b[-1].end_seconds,
            )
        combined_score = (0.65 * float(probability)) + (0.25 * rhythm_score) + (0.10 * transition_bias)
        reranked_probabilities.append(combined_score)

    best_index = max(range(len(reranked_probabilities)), key=lambda index: reranked_probabilities[index])
    best_candidate = dict(metadata[best_index])
    best_candidate["probability"] = float(reranked_probabilities[best_index])
    best_candidate["model_probability"] = float(probabilities[best_index])
    best_candidate["overlay_start_seconds"] = (
        snap_to_bar_grid(best_candidate["left_start_seconds"], best_candidate["left_bpm"])
        if preserve_track_a_from_start
        else best_candidate["left_start_seconds"]
    )
    best_candidate["tempo_ratio"] = float(compute_tempo_ratio(best_candidate["right_bpm"], best_candidate["left_bpm"]))
    return best_candidate


def choose_best_transition_without_model(
    segments_a: list,
    segments_b: list,
    features_a: list[list[float]],
    features_b: list[list[float]],
    preserve_track_a_from_start: bool,
    min_ai_overlay_start_seconds: int,
    max_ai_overlay_start_seconds: int,
) -> dict:
    min_ai_overlay_start_seconds = max(0, int(min_ai_overlay_start_seconds))
    max_ai_overlay_start_seconds = max(min_ai_overlay_start_seconds + 1, int(max_ai_overlay_start_seconds))

    if preserve_track_a_from_start:
        left_start_threshold_seconds = float(min_ai_overlay_start_seconds)
        left_end_threshold_seconds = float(max_ai_overlay_start_seconds)
    else:
        left_start_threshold_seconds = float(segments_a[len(segments_a) // 3].start_seconds)
        left_end_threshold_seconds = float(segments_a[max(len(segments_a) // 3, (len(segments_a) * 9) // 10 - 1)].start_seconds)

    right_start_threshold = len(segments_b) // 6
    right_end_threshold = max(right_start_threshold + 1, (len(segments_b) * 5) // 6)
    bpm_key_index = FEATURE_KEYS.index("estimated_bpm")
    best_candidate: dict | None = None
    best_score = float("-inf")

    for left_index, left_segment in enumerate(segments_a):
        left_start_seconds = float(left_segment.start_seconds)
        if left_start_seconds < left_start_threshold_seconds or left_start_seconds > left_end_threshold_seconds:
            continue

        for right_index, right_segment in enumerate(segments_b):
            if right_index < right_start_threshold or right_index > right_end_threshold:
                continue

            left_bpm = float(features_a[left_index][bpm_key_index])
            right_bpm = float(features_b[right_index][bpm_key_index])
            if left_bpm <= 0 or right_bpm <= 0:
                continue

            right_start_seconds = float(right_segment.start_seconds)
            rhythm_score = combined_transition_rhythm_score(
                left_start_seconds,
                right_start_seconds,
                left_bpm,
                right_bpm,
            )
            tempo_ratio = compute_tempo_ratio(right_bpm, left_bpm)
            tempo_penalty = min(abs(1.0 - float(tempo_ratio)), 1.0)

            if preserve_track_a_from_start:
                transition_bias = compute_intro_overlay_bias(
                    left_start_seconds,
                    right_start_seconds,
                    segments_b[-1].end_seconds,
                    min_ai_overlay_start_seconds,
                    max_ai_overlay_start_seconds,
                )
            else:
                transition_bias = compute_mid_mix_bias(
                    left_start_seconds,
                    right_start_seconds,
                    segments_a[-1].end_seconds,
                    segments_b[-1].end_seconds,
                )

            combined_score = (0.7 * rhythm_score) + (0.2 * transition_bias) + (0.1 * (1.0 - tempo_penalty))
            if combined_score <= best_score:
                continue

            best_score = combined_score
            best_candidate = {
                "left_start_seconds": left_start_seconds,
                "right_start_seconds": right_start_seconds,
                "left_bpm": left_bpm,
                "right_bpm": right_bpm,
                "probability": float(combined_score),
                "model_probability": 0.0,
                "overlay_start_seconds": (
                    snap_to_bar_grid(left_start_seconds, left_bpm)
                    if preserve_track_a_from_start
                    else left_start_seconds
                ),
                "tempo_ratio": float(tempo_ratio),
            }

    if best_candidate is None:
        raise RuntimeError("No valid heuristic transition candidates were generated.")

    return best_candidate


def refine_transition_candidate(candidate: dict) -> dict:
    refined = dict(candidate)
    overlay_start = snap_to_bar_grid(float(refined["overlay_start_seconds"]), float(refined["left_bpm"]))
    right_start = snap_to_bar_grid(float(refined["right_start_seconds"]), float(refined["right_bpm"]))
    beat_period = beat_period_seconds(float(refined["right_bpm"]))
    if beat_period <= 0:
        refined["overlay_start_seconds"] = overlay_start
        refined["right_start_seconds"] = right_start
        return refined

    search_radius = beat_period * 2.0
    step = max(0.02, beat_period / 8.0)
    best_right_start = right_start
    best_score = combined_transition_rhythm_score(
        overlay_start,
        right_start,
        float(refined["left_bpm"]),
        float(refined["right_bpm"]),
    )

    offset = -search_radius
    while offset <= search_radius:
        candidate_right_start = max(0.0, right_start + offset)
        score = combined_transition_rhythm_score(
            overlay_start,
            candidate_right_start,
            float(refined["left_bpm"]),
            float(refined["right_bpm"]),
        )
        if score > best_score:
            best_score = score
            best_right_start = round(candidate_right_start, 3)
        offset += step

    refined["overlay_start_seconds"] = round(overlay_start, 3)
    refined["right_start_seconds"] = round(best_right_start, 3)
    return refined


def render_mix(
    track_a: Path,
    track_b: Path,
    output_path: Path,
    overlay_start_seconds: float,
    left_start_seconds: float,
    right_start_seconds: float,
    left_bpm: float,
    right_bpm: float,
    window_seconds: int,
    crossfade_seconds: int,
    mix_lead_in_seconds: int,
    track_b_fade_in_seconds: int,
    overlay_seconds: int,
    track_b_tail_seconds: int,
    preserve_track_a_from_start: bool,
    transition_plan: dict,
) -> None:
    crossfade_seconds = max(1, int(crossfade_seconds))
    mix_lead_in_seconds = max(1, int(mix_lead_in_seconds))
    track_b_fade_in_seconds = max(1, int(track_b_fade_in_seconds))
    overlay_seconds = max(crossfade_seconds, int(overlay_seconds))
    track_b_tail_seconds = max(1, int(track_b_tail_seconds))

    snapped_overlay_start = snap_to_bar_grid(overlay_start_seconds, left_bpm)
    snapped_left_start = snap_to_bar_grid(left_start_seconds, left_bpm)
    snapped_right_start = snap_to_bar_grid(right_start_seconds, right_bpm)
    transition_style = str(transition_plan.get("style", "blend"))
    transition_cue_seconds = float(transition_plan.get("transition_cue_seconds", snapped_overlay_start + overlay_seconds))
    source_entry_lead_seconds = max(0.0, float(transition_plan.get("source_entry_lead_seconds", 0.0)))
    target_entry_lead_seconds = max(0.0, float(transition_plan.get("target_entry_lead_seconds", 0.0)))
    tail_beats = max(1, int(transition_plan.get("tail_beats", 8)))
    left_render_start = 0.0 if preserve_track_a_from_start else max(0.0, snapped_left_start - mix_lead_in_seconds)
    overlay_start_seconds = snapped_overlay_start
    beat_window_seconds = max(beat_period_seconds(left_bpm), 0.333)
    transition_cue_seconds = max(overlay_start_seconds + target_entry_lead_seconds, transition_cue_seconds)
    post_switch_seconds = max(beat_window_seconds * tail_beats, float(track_b_tail_seconds))
    left_end_seconds = transition_cue_seconds + max(post_switch_seconds * 0.85, beat_window_seconds * 6.0)
    b_full_start_seconds = snapped_right_start + source_entry_lead_seconds
    b_mix_duration = max(
        float(source_entry_lead_seconds + post_switch_seconds + (beat_window_seconds * 2.0)),
        float(overlay_seconds + track_b_tail_seconds),
        float(window_seconds),
    )
    tempo_ratio = compute_tempo_ratio(right_bpm, left_bpm)
    atempo_filters = build_atempo_filters(tempo_ratio)
    b_delay_ms = max(0, int(round(overlay_start_seconds * 1000.0)))
    cue_delay_ms = max(0, int(round(transition_cue_seconds * 1000.0)))
    a_volume = 0.92
    b_volume = 0.86
    filter_graph = build_transition_filter_graph(
        transition_style=transition_style,
        left_render_start=left_render_start,
        left_end_seconds=left_end_seconds,
        snapped_right_start=snapped_right_start,
        b_full_start_seconds=b_full_start_seconds,
        b_mix_duration=b_mix_duration,
        source_entry_lead_seconds=source_entry_lead_seconds,
        overlay_start_seconds=overlay_start_seconds,
        transition_cue_seconds=transition_cue_seconds,
        beat_window_seconds=beat_window_seconds,
        atempo_filters=atempo_filters,
        a_volume=a_volume,
        b_volume=b_volume,
        track_b_fade_in_seconds=track_b_fade_in_seconds,
        crossfade_seconds=crossfade_seconds,
        b_delay_ms=b_delay_ms,
        cue_delay_ms=cue_delay_ms,
    )

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(track_a),
        "-i",
        str(track_b),
        "-filter_complex",
        filter_graph,
        "-map",
        "[out]",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        "-y",
        str(output_path),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exception:
        raise RuntimeError("ffmpeg is required to render the MP3 mix.") from exception
    except subprocess.CalledProcessError as exception:
        raise RuntimeError(f"ffmpeg mix render failed: {exception.stderr}") from exception


def build_transition_filter_graph(
    transition_style: str,
    left_render_start: float,
    left_end_seconds: float,
    snapped_right_start: float,
    b_full_start_seconds: float,
    b_mix_duration: float,
    source_entry_lead_seconds: float,
    overlay_start_seconds: float,
    transition_cue_seconds: float,
    beat_window_seconds: float,
    atempo_filters: str,
    a_volume: float,
    b_volume: float,
    track_b_fade_in_seconds: int,
    crossfade_seconds: int,
    b_delay_ms: int,
    cue_delay_ms: int,
) -> str:
    filters: list[str] = []
    mix_inputs: list[str] = []

    overlap_length = max(beat_window_seconds * 4.0, left_end_seconds - overlay_start_seconds)
    a_pre_end = min(max(left_render_start + 0.05, overlay_start_seconds), left_end_seconds)
    a_overlap_length = max(0.0, left_end_seconds - overlay_start_seconds)

    style_settings = {
        "double_drop": {
            "a_overlap_volume": 0.88,
            "a_highpass": 180, # Aggressive HP to clear space for B's bass
            "a_lowpass": 16000,
            "a_hold_seconds": beat_window_seconds * 12.0,
            "a_fade_seconds": max(beat_window_seconds * 20.0, 10.0),
            "b_intro_highpass": 220,
            "b_intro_lowpass": 15000,
            "b_intro_volume": 0.76,
            "b_full_volume": 0.95,
            "b_full_fade": 0.12,
            "b_bass_boost": 0.15,
        },
        "bass_swap": {
            "a_overlap_volume": 0.82,
            "a_highpass": 240, # Complete bass kill for handoff
            "a_lowpass": 13000,
            "a_hold_seconds": beat_window_seconds * 32.0,
            "a_fade_seconds": max(beat_window_seconds * 32.0, 15.0),
            "b_intro_highpass": 280,
            "b_intro_lowpass": 12000,
            "b_intro_volume": 0.72,
            "b_full_volume": 0.94,
            "b_full_fade": min(max(track_b_fade_in_seconds * 0.4, 0.6), 4.5),
            "b_bass_boost": 0.22,
        },
        "echo_out": {
            "a_overlap_volume": 0.76,
            "a_highpass": 320,
            "a_lowpass": 8000,
            "a_hold_seconds": beat_window_seconds * 8.0,
            "a_fade_seconds": max(beat_window_seconds * 12.0, 6.0),
            "b_intro_highpass": 200,
            "b_intro_lowpass": 14000,
            "b_intro_volume": 0.7,
            "b_full_volume": 0.92,
            "b_full_fade": min(max(track_b_fade_in_seconds * 0.5, 0.8), 3.5),
            "b_bass_boost": 0.1,
        },
        "blend": {
            "a_overlap_volume": 0.84,
            "a_highpass": 120,
            "a_lowpass": 15000,
            "a_hold_seconds": beat_window_seconds * 16.0,
            "a_fade_seconds": max(beat_window_seconds * 20.0, 12.0),
            "b_intro_highpass": 150,
            "b_intro_lowpass": 14500,
            "b_intro_volume": 0.74,
            "b_full_volume": 0.92,
            "b_full_fade": min(max(track_b_fade_in_seconds * 0.5, 0.8), 4.0),
            "b_bass_boost": 0.12,
        },
        "manual_blend": {
            "a_overlap_volume": 0.86,
            "a_highpass": 100,
            "a_lowpass": 16000,
            "a_hold_seconds": beat_window_seconds * 16.0,
            "a_fade_seconds": max(beat_window_seconds * 24.0, 15.0),
            "b_intro_highpass": 120,
            "b_intro_lowpass": 15000,
            "b_intro_volume": 0.78,
            "b_full_volume": 0.94,
            "b_full_fade": min(max(track_b_fade_in_seconds * 0.5, 0.8), 4.0),
            "b_bass_boost": 0.1,
        },
    }
    settings = style_settings.get(transition_style, style_settings["blend"])

    filters.append(
        f"[0:a]atrim={left_render_start:.3f}:{a_pre_end:.3f},asetpts=PTS-STARTPTS,"
        f"volume={a_volume:.3f}[a_pre]"
    )
    mix_inputs.append("[a_pre]")

    if a_overlap_length > 0.08:
        overlap_hold_seconds = max(
            settings["a_hold_seconds"],
            (transition_cue_seconds - overlay_start_seconds) + (beat_window_seconds * 2.0),
        )
        a_overlap_fade_start = min(overlap_hold_seconds, max(0.0, a_overlap_length - 0.15))
        a_overlap_fade_duration = min(settings["a_fade_seconds"], max(0.15, a_overlap_length - a_overlap_fade_start))
        a_overlap_chain = (
            f"[0:a]atrim={overlay_start_seconds:.3f}:{left_end_seconds:.3f},asetpts=PTS-STARTPTS,"
            f"highpass=f={settings['a_highpass']},lowpass=f={settings['a_lowpass']},"
            f"volume={settings['a_overlap_volume']:.3f},"
        )
        if transition_style == "echo_out":
            a_overlap_chain += "aecho=0.84:0.32:120:0.2,"
        a_overlap_chain += (
            f"afade=t=out:st={a_overlap_fade_start:.3f}:d={a_overlap_fade_duration:.3f},"
            f"adelay={b_delay_ms}|{b_delay_ms}[a_overlap]"
        )
        filters.append(a_overlap_chain)
        mix_inputs.append("[a_overlap]")

    if source_entry_lead_seconds > 0.35:
        intro_fade_in = min(max(beat_window_seconds * 2.0, 1.0), max(source_entry_lead_seconds * 0.45, 1.0))
        intro_fade_out = min(max(beat_window_seconds * 0.75, 0.7), max(source_entry_lead_seconds * 0.3, 0.7))
        intro_fade_out_start = max(0.0, source_entry_lead_seconds - intro_fade_out)
        filters.append(
            f"[1:a]atrim={snapped_right_start:.3f}:{snapped_right_start + source_entry_lead_seconds:.3f},asetpts=PTS-STARTPTS,"
            f"{atempo_filters},highpass=f={settings['b_intro_highpass']},lowpass=f={settings['b_intro_lowpass']},"
            f"volume={settings['b_intro_volume']:.3f},afade=t=in:st=0:d={intro_fade_in:.3f},"
            f"afade=t=out:st={intro_fade_out_start:.3f}:d={intro_fade_out:.3f},"
            f"adelay={b_delay_ms}|{b_delay_ms}[b_intro]"
        )
        mix_inputs.append("[b_intro]")

    full_fade_in = settings["b_full_fade"]
    filters.append(
        f"[1:a]atrim={b_full_start_seconds:.3f}:{snapped_right_start + b_mix_duration:.3f},asetpts=PTS-STARTPTS,"
        f"{atempo_filters},volume={settings['b_full_volume']:.3f},afade=t=in:st=0:d={full_fade_in:.3f},"
        f"adelay={cue_delay_ms}|{cue_delay_ms}[b_full]"
    )
    mix_inputs.append("[b_full]")

    if settings["b_bass_boost"] > 0.0:
        filters.append(
            f"[1:a]atrim={b_full_start_seconds:.3f}:{snapped_right_start + b_mix_duration:.3f},asetpts=PTS-STARTPTS,"
            f"{atempo_filters},lowpass=f=180,volume={settings['b_bass_boost']:.3f},"
            f"afade=t=in:st=0:d={max(beat_window_seconds * 1.5, 1.0):.3f},"
            f"afade=t=out:st={max(beat_window_seconds * 8.0, 5.0):.3f}:d={max(beat_window_seconds * 4.0, 2.5):.3f},"
            f"adelay={cue_delay_ms}|{cue_delay_ms}[b_bass]"
        )
        mix_inputs.append("[b_bass]")

    if transition_style in {"double_drop", "echo_out"}:
        fx_start = max(left_render_start, transition_cue_seconds - (beat_window_seconds * 0.35))
        fx_end = min(left_end_seconds, transition_cue_seconds + max(beat_window_seconds * 6.0, 4.0))
        fx_delay_ms = max(0, int(round(fx_start * 1000.0)))
        fx_length = max(0.8, fx_end - fx_start)
        filters.append(
            f"[0:a]atrim={fx_start:.3f}:{fx_end:.3f},asetpts=PTS-STARTPTS,"
            f"aecho=0.82:0.38:160:0.18,lowpass=f=3600,highpass=f=220,volume=0.22,"
            f"afade=t=out:st={max(0.0, fx_length - max(beat_window_seconds * 4.0, 2.0)):.3f}:d={max(beat_window_seconds * 4.0, 2.0):.3f},"
            f"adelay={fx_delay_ms}|{fx_delay_ms}[a_fx]"
        )
        mix_inputs.append("[a_fx]")

    filter_graph = ";".join(filters)
    filter_graph += ";"
    filter_graph += "".join(mix_inputs)
    filter_graph += f"amix=inputs={len(mix_inputs)}:duration=longest:dropout_transition=0,alimiter=limit=0.95[out]"
    return filter_graph


def create_normalized_wav(source_path: Path) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        output_path = Path(temp_file.name)

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(source_path),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        "-y",
        str(output_path),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Normalized WAV was not created for input: {source_path.name}")
        return output_path
    except FileNotFoundError as exception:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg is required to normalize uploaded audio.") from exception
    except RuntimeError:
        output_path.unlink(missing_ok=True)
        raise
    except subprocess.CalledProcessError as exception:
        output_path.unlink(missing_ok=True)
        stderr = (exception.stderr or "").replace("\r", " ").replace("\n", " ").strip()
        if len(stderr) > 220:
            stderr = stderr[:220] + "..."
        raise RuntimeError(
            f"Uploaded file could not be decoded as audio: {source_path.name}. "
            f"Try exporting it again as MP3 or WAV. Details: {stderr}"
        ) from exception


def compute_mid_mix_bias(
    left_start_seconds: float,
    right_start_seconds: float,
    left_duration_seconds: float,
    right_duration_seconds: float,
) -> float:
    if left_duration_seconds <= 0 or right_duration_seconds <= 0:
        return 0.0

    left_position = left_start_seconds / left_duration_seconds
    right_position = right_start_seconds / right_duration_seconds
    left_target = 0.68
    right_target = 0.45
    left_penalty = abs(left_position - left_target)
    right_penalty = abs(right_position - right_target)
    return max(0.0, 1.0 - ((left_penalty * 1.2) + (right_penalty * 1.4)))


def compute_intro_overlay_bias(
    left_start_seconds: float,
    right_start_seconds: float,
    right_duration_seconds: float,
    min_overlay_start_seconds: int,
    max_overlay_start_seconds: int,
) -> float:
    if right_duration_seconds <= 0:
        return 0.0

    target_overlay_seconds = (float(min_overlay_start_seconds) + float(max_overlay_start_seconds)) / 2.0
    overlay_window = max(1.0, float(max_overlay_start_seconds - min_overlay_start_seconds))
    left_penalty = abs(left_start_seconds - target_overlay_seconds) / overlay_window
    right_position = right_start_seconds / right_duration_seconds
    right_penalty = abs(right_position - 0.45)
    return max(0.0, 1.0 - (left_penalty + (right_penalty * 1.2)))


if __name__ == "__main__":
    raise SystemExit(main())

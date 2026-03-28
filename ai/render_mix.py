from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import torch

from beat_sync import (
    beat_period_seconds,
    build_atempo_filters,
    combined_transition_rhythm_score,
    compute_tempo_ratio,
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

        checkpoint = torch.load(args.model_path, map_location="cpu")
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
        if args.overlay_start_seconds is not None:
            candidate["overlay_start_seconds"] = round(max(0.0, float(args.overlay_start_seconds)), 3)
        if args.right_start_seconds is not None:
            candidate["right_start_seconds"] = round(max(0.0, float(args.right_start_seconds)), 3)

        render_mix(
            track_a=track_a,
            track_b=track_b,
            output_path=output_path,
            overlay_start_seconds=candidate["overlay_start_seconds"],
            left_start_seconds=candidate["left_start_seconds"],
            right_start_seconds=candidate["right_start_seconds"],
            left_bpm=candidate["left_bpm"],
            right_bpm=candidate["right_bpm"],
            window_seconds=args.window_seconds,
            crossfade_seconds=args.crossfade_seconds,
            mix_lead_in_seconds=args.mix_lead_in_seconds,
            track_b_fade_in_seconds=args.track_b_fade_in_seconds,
            overlay_seconds=args.overlay_seconds,
            track_b_tail_seconds=args.track_b_tail_seconds,
            preserve_track_a_from_start=args.preserve_track_a_from_start,
        )

        print(f"overlay_start_seconds={candidate['overlay_start_seconds']:.3f}")
        print(f"left_start_seconds={candidate['left_start_seconds']:.3f}")
        print(f"right_start_seconds={candidate['right_start_seconds']:.3f}")
        print(f"left_bpm={candidate['left_bpm']:.3f}")
        print(f"right_bpm={candidate['right_bpm']:.3f}")
        print(f"tempo_ratio={candidate['tempo_ratio']:.6f}")
        print(f"model_probability={candidate['model_probability']:.6f}")
        print(f"probability={candidate['probability']:.6f}")
        print(f"output_path={output_path}")
        return 0
    finally:
        track_a.unlink(missing_ok=True)
        track_b.unlink(missing_ok=True)


def extract_features_for_segments(track_path: Path, segments: list, sample_rate: int) -> list[list[float]]:
    features: list[list[float]] = []
    for segment in segments:
        payload = extract_segment_features(
            source_path=track_path,
            start_seconds=float(segment.start_seconds),
            duration_seconds=float(segment.duration_seconds),
            sample_rate=sample_rate,
        )
        features.append([float(payload.get(key, 0.0)) for key in FEATURE_KEYS])
    return features


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
) -> None:
    crossfade_seconds = max(1, int(crossfade_seconds))
    mix_lead_in_seconds = max(1, int(mix_lead_in_seconds))
    track_b_fade_in_seconds = max(1, int(track_b_fade_in_seconds))
    overlay_seconds = max(crossfade_seconds, int(overlay_seconds))
    track_b_tail_seconds = max(1, int(track_b_tail_seconds))

    snapped_overlay_start = snap_to_bar_grid(overlay_start_seconds, left_bpm)
    snapped_left_start = snap_to_bar_grid(left_start_seconds, left_bpm)
    snapped_right_start = snap_to_bar_grid(right_start_seconds, right_bpm)
    left_render_start = 0.0 if preserve_track_a_from_start else max(0.0, snapped_left_start - mix_lead_in_seconds)
    overlay_start_seconds = snapped_overlay_start
    left_end_seconds = overlay_start_seconds + overlay_seconds
    b_mix_duration = max(
        float(overlay_seconds + track_b_tail_seconds),
        float(track_b_fade_in_seconds + track_b_tail_seconds),
        float(window_seconds),
    )
    tempo_ratio = compute_tempo_ratio(right_bpm, left_bpm)
    atempo_filters = build_atempo_filters(tempo_ratio)
    b_delay_ms = max(0, int(round(overlay_start_seconds * 1000.0)))
    a_fade_out_start = max(0.0, left_end_seconds - crossfade_seconds)
    a_volume = 0.92
    b_volume = 0.86

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(track_a),
        "-i",
        str(track_b),
        "-filter_complex",
        (
            f"[0:a]atrim={left_render_start:.3f}:{left_end_seconds:.3f},asetpts=PTS-STARTPTS,"
            f"volume={a_volume:.3f},afade=t=out:st={a_fade_out_start - left_render_start:.3f}:d={crossfade_seconds}[a0];"
            f"[1:a]atrim={snapped_right_start:.3f}:{snapped_right_start + b_mix_duration:.3f},asetpts=PTS-STARTPTS,"
            f"{atempo_filters},volume={b_volume:.3f},afade=t=in:st=0:d={track_b_fade_in_seconds},"
            f"adelay={b_delay_ms}|{b_delay_ms}[a1];"
            f"[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0,"
            f"alimiter=limit=0.95[out]"
        ),
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

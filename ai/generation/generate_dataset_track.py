from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import wave
from array import array
from pathlib import Path

import torch

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from beat_sync import beat_period_seconds, bpm_distance_score, build_atempo_filters, compute_tempo_ratio, normalize_dnb_bpm
from extract_features import compute_rms_envelope, compute_standard_deviation
from modeling import FEATURE_KEYS, TransitionScorer, build_pair_vector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a DnB track by beat-syncing and overlaying labeled dataset clips.")
    parser.add_argument("--style", choices=("liquid", "deep"), required=True, help="Target style")
    parser.add_argument("--duration-seconds", type=int, default=150, help="Approximate output duration")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--dataset-path", required=True, help="Path to generation_dataset JSONL")
    parser.add_argument("--clips-root", required=True, help="Root directory with exported clips")
    parser.add_argument("--features-dir", required=True, help="Directory with segment feature manifests")
    parser.add_argument("--transition-model-path", required=True, help="Path to trained transition scorer")
    parser.add_argument("--output-path", required=True, help="Output MP3 or WAV path")
    parser.add_argument("--clip-seconds", type=int, default=30, help="Expected clip length")
    parser.add_argument("--crossfade-seconds", type=int, default=8, help="How long the outgoing track fades out at the end of a transition")
    parser.add_argument("--transition-bars", type=int, default=16, help="How many bars two tracks should overlap during a DJ-style transition")
    parser.add_argument("--incoming-fade-bars", type=int, default=8, help="How many bars the incoming track takes to fade up")
    parser.add_argument("--candidate-pool-size", type=int, default=24, help="Random candidates scored at each step")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)

    rows = [json.loads(line) for line in Path(args.dataset_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    style_rows = [row for row in rows if str(row.get("style", "")).strip().lower() == args.style]
    if len(style_rows) < 3:
        raise RuntimeError(f"Not enough clips available for style '{args.style}'.")

    features = load_feature_index(Path(args.features_dir))
    scorer = load_transition_model(Path(args.transition_model_path))
    selected_rows = choose_sequence(
        style_rows=style_rows,
        features=features,
        scorer=scorer,
        rng=rng,
        target_duration_seconds=args.duration_seconds,
        clip_seconds=args.clip_seconds,
        crossfade_seconds=args.crossfade_seconds,
        candidate_pool_size=args.candidate_pool_size,
        clips_root=Path(args.clips_root),
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    render_sequence(
        selected_rows,
        output_path,
        crossfade_seconds=args.crossfade_seconds,
        transition_bars=args.transition_bars,
        incoming_fade_bars=args.incoming_fade_bars,
    )

    print(f"style={args.style}")
    print(f"selected_clips={len(selected_rows)}")
    print(f"output_path={output_path}")
    return 0


def choose_sequence(
    style_rows: list[dict],
    features: dict[tuple[str, int], list[float]],
    scorer: dict,
    rng: random.Random,
    target_duration_seconds: int,
    clip_seconds: int,
    crossfade_seconds: int,
    candidate_pool_size: int,
    clips_root: Path,
) -> list[dict]:
    effective_clip_seconds = max(1, clip_seconds - crossfade_seconds)
    clip_count = max(3, int(round(target_duration_seconds / effective_clip_seconds)))
    section_targets = build_section_targets(clip_count)
    canonical_bpm = resolve_canonical_bpm(style_rows)

    current = choose_starting_row(style_rows, canonical_bpm, rng)
    sequence = [current]
    recent_sets = [str(current["set_id"])]

    for step_index in range(1, clip_count):
        candidates = build_candidate_pool(
            style_rows,
            sequence,
            recent_sets,
            rng,
            candidate_pool_size,
            target_bpm=resolve_row_bpm(current),
            fallback_bpm=canonical_bpm,
        )
        if not candidates:
            break
        target = section_targets[min(step_index, len(section_targets) - 1)]
        next_row = max(
            candidates,
            key=lambda candidate: transition_score(
                current,
                candidate,
                features,
                scorer,
                target=target,
                sequence=sequence,
                canonical_bpm=canonical_bpm,
                diversity_bonus=0.05 if str(candidate["set_id"]) not in recent_sets else 0.0,
            ),
        )
        sequence.append(next_row)
        current = next_row
        recent_sets.append(str(next_row["set_id"]))
        recent_sets = recent_sets[-3:]

    attached = [attach_clip_path(row, clips_root) for row in sequence]
    return stabilize_sequence_bpms(attached, canonical_bpm)


def build_candidate_pool(
    style_rows: list[dict],
    sequence: list[dict],
    recent_sets: list[str],
    rng: random.Random,
    size: int,
    target_bpm: float,
    fallback_bpm: float,
) -> list[dict]:
    used_keys = {(str(row["set_id"]), int(row["segment_index"])) for row in sequence}
    preferred = [
        row for row in style_rows
        if (str(row["set_id"]), int(row["segment_index"])) not in used_keys
        and str(row["set_id"]) not in recent_sets
    ]
    fallback = [
        row for row in style_rows
        if (str(row["set_id"]), int(row["segment_index"])) not in used_keys
    ]
    bpm_matched_preferred = [row for row in preferred if is_bpm_compatible(resolve_row_bpm(row), target_bpm, fallback_bpm)]
    bpm_matched_fallback = [row for row in fallback if is_bpm_compatible(resolve_row_bpm(row), target_bpm, fallback_bpm)]
    source = (
        bpm_matched_preferred
        or bpm_matched_fallback
        or preferred
        or fallback
    )
    source = sorted(
        source,
        key=lambda row: (
            compute_rhythm_stability_score(row),
            compute_transition_readiness_score(row),
        ),
        reverse=True,
    )
    if not source:
        return []
    if len(source) <= size:
        return list(source)
    head_count = max(4, size // 2)
    head = source[: min(len(source), head_count)]
    tail_source = source[min(len(source), head_count):]
    tail_count = max(0, size - len(head))
    sampled_tail = rng.sample(tail_source, min(len(tail_source), tail_count)) if tail_count > 0 and tail_source else []
    return head + sampled_tail


def transition_score(
    current: dict,
    candidate: dict,
    features: dict[tuple[str, int], list[float]],
    scorer: dict,
    target: dict,
    sequence: list[dict],
    canonical_bpm: float,
    diversity_bonus: float,
) -> float:
    left = features[(str(current["set_id"]), int(current["segment_index"]))]
    right = features[(str(candidate["set_id"]), int(candidate["segment_index"]))]
    vector = torch.tensor([build_pair_vector(left, right)], dtype=torch.float32)
    vector = (vector - scorer["mean"]) / scorer["std"]
    with torch.no_grad():
        probability = torch.sigmoid(scorer["model"](vector)).item()
    section_fit = compute_section_fit(candidate, target)
    repetition_penalty = compute_repetition_penalty(candidate, sequence)
    current_bpm = resolve_row_bpm(current)
    candidate_bpm = resolve_row_bpm(candidate)
    bpm_fit = compute_bpm_fit(current_bpm, candidate_bpm, canonical_bpm)
    bpm_penalty = compute_bpm_penalty(current_bpm, candidate_bpm)
    rhythm_stability = compute_pair_rhythm_stability(current, candidate)
    phrase_fit = compute_phrase_transition_fit(current, candidate, target)
    return (
        (0.42 * float(probability))
        + (0.16 * section_fit)
        + (0.22 * bpm_fit)
        + (0.12 * rhythm_stability)
        + (0.08 * phrase_fit)
        + diversity_bonus
        - repetition_penalty
        - bpm_penalty
    )


def attach_clip_path(row: dict, clips_root: Path) -> dict:
    enriched = dict(row)
    export_path = str(row.get("export_path", "")).strip()
    if export_path and Path(export_path).exists():
        enriched["clip_path"] = export_path
        enriched["mix_bpm"] = resolve_row_bpm(enriched)
        return enriched

    safe_name = sanitize_name(str(row["set_id"]))
    segment_index = int(row["segment_index"])
    start_ms = int(round(float(row["start_seconds"]) * 1000.0))
    inferred_path = clips_root / str(row["style"]).strip().lower() / f"{safe_name}__seg-{segment_index:04d}__start-{start_ms:08d}.wav"
    if not inferred_path.exists():
        raise FileNotFoundError(f"Clip file not found: {inferred_path}")
    enriched["clip_path"] = str(inferred_path)
    enriched["mix_bpm"] = resolve_row_bpm(enriched)
    return enriched


def render_sequence(
    sequence: list[dict],
    output_path: Path,
    crossfade_seconds: int,
    transition_bars: int,
    incoming_fade_bars: int,
) -> None:
    if not sequence:
        raise RuntimeError("No sequence selected for rendering.")

    placement_plan = build_mix_plan(
        sequence,
        requested_overlap_seconds=crossfade_seconds,
        transition_bars=transition_bars,
        incoming_fade_bars=incoming_fade_bars,
    )

    command = ["ffmpeg", "-v", "error"]
    for row in sequence:
        command.extend(["-i", str(row["clip_path"])])

    filter_parts: list[str] = []
    mixed_labels: list[str] = []
    for index, plan_item in enumerate(placement_plan):
        input_label = f"[{index}:a]"
        output_label = f"[mix{index}]"
        filters = [
            f"atrim={plan_item['source_trim_start_seconds']:.3f}:{plan_item['source_trim_end_seconds']:.3f}",
            "asetpts=PTS-STARTPTS",
            build_atempo_filters(plan_item["tempo_ratio"]),
            f"volume={plan_item['volume']:.3f}",
        ]
        if plan_item["fade_in_seconds"] > 0:
            filters.append(f"afade=t=in:st=0:d={plan_item['fade_in_seconds']:.3f}")
        if plan_item["fade_out_seconds"] > 0:
            fade_out_start = max(0.0, plan_item["adjusted_duration_seconds"] - plan_item["fade_out_seconds"])
            filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={plan_item['fade_out_seconds']:.3f}")

        delay_ms = int(round(plan_item["start_seconds"] * 1000.0))
        filters.append(f"adelay={delay_ms}|{delay_ms}")
        filter_parts.append(f"{input_label}{','.join(filters)}{output_label}")
        mixed_labels.append(output_label)

    filter_parts.append(
        f"{''.join(mixed_labels)}amix=inputs={len(mixed_labels)}:duration=longest:dropout_transition=0,"
        "alimiter=limit=0.95[out]"
    )

    command.extend([
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[out]",
    ])

    if output_path.suffix.lower() == ".wav":
        command.extend(["-y", str(output_path)])
    else:
        command.extend(["-c:a", "libmp3lame", "-b:a", "192k", "-y", str(output_path)])

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exception:
        raise RuntimeError("ffmpeg is required to render generated tracks.") from exception
    except subprocess.CalledProcessError as exception:
        raise RuntimeError(f"ffmpeg generation render failed: {exception.stderr}") from exception


def build_section_targets(clip_count: int) -> list[dict]:
    if clip_count <= 3:
        return [
            {"name": "intro", "energy": 0.25},
            {"name": "drop", "energy": 0.88},
            {"name": "outro", "energy": 0.35},
        ]

    template = [
        {"name": "intro", "energy": 0.22},
        {"name": "build", "energy": 0.48},
        {"name": "drop_a", "energy": 0.9},
        {"name": "break", "energy": 0.3},
        {"name": "drop_b", "energy": 0.94},
        {"name": "outro", "energy": 0.38},
    ]
    if clip_count <= len(template):
        return template[:clip_count]

    result = list(template)
    while len(result) < clip_count:
        insert_at = max(2, len(result) - 1)
        result.insert(insert_at, {"name": "ride", "energy": 0.78})
    return result[:clip_count]


def build_mix_plan(
    sequence: list[dict],
    requested_overlap_seconds: int,
    transition_bars: int,
    incoming_fade_bars: int,
) -> list[dict]:
    if not sequence:
        return []

    master_bpm = resolve_master_bpm(sequence)
    if master_bpm <= 0:
        master_bpm = 174.0

    bar_duration = beat_period_seconds(master_bpm) * 4.0
    beat_duration = beat_period_seconds(master_bpm)
    if bar_duration <= 0:
        bar_duration = 60.0 / 174.0 * 4.0
    if beat_duration <= 0:
        beat_duration = 60.0 / 174.0

    transition_bars = max(4, int(transition_bars))
    incoming_fade_bars = max(2, min(int(incoming_fade_bars), transition_bars))
    requested_overlap_seconds = max(1.0, float(requested_overlap_seconds))
    default_overlap = max(
        round(transition_bars * bar_duration, 3),
        round_to_bar(requested_overlap_seconds, bar_duration),
    )
    incoming_fade_seconds = round(incoming_fade_bars * bar_duration, 3)
    plan: list[dict] = []
    current_start = 0.0
    beat_offset_cache: dict[tuple[str, float], float] = {}
    rhythm_cache: dict[str, dict] = {}

    for index, row in enumerate(sequence):
        source_duration_seconds = max(1.0, float(row.get("duration_seconds", 30.0)))
        source_bpm = resolve_detected_bpm(row)
        target_bpm = resolve_row_bpm(row)
        source_trim_start_seconds = compute_source_trim_start(row, source_bpm, beat_offset_cache)
        trimmed_source_duration_seconds = max(1.0, source_duration_seconds - source_trim_start_seconds)
        tempo_ratio = compute_tempo_ratio(source_bpm, master_bpm)
        adjusted_duration_seconds = trimmed_source_duration_seconds / max(tempo_ratio, 1e-6)
        overlap_seconds = 0.0 if index == len(sequence) - 1 else min(default_overlap, adjusted_duration_seconds * 0.72)
        overlap_seconds = round_to_bar(overlap_seconds, bar_duration) if overlap_seconds > 0 else 0.0
        if overlap_seconds >= adjusted_duration_seconds:
            overlap_seconds = max(bar_duration, adjusted_duration_seconds * 0.33)
            overlap_seconds = min(overlap_seconds, max(1.0, adjusted_duration_seconds - 1.0))

        outgoing_fade_seconds = 0.0 if index == len(sequence) - 1 else min(float(requested_overlap_seconds), overlap_seconds * 0.45)
        incoming_track_fade_seconds = 0.0 if index == 0 else min(incoming_fade_seconds, max(bar_duration, overlap_seconds * 0.7))
        transition_anchor_seconds = round(current_start, 3)

        if index > 0:
            previous_row = sequence[index - 1]
            previous_plan = plan[-1]
            source_trim_start_seconds = refine_pair_phase_alignment(
                previous_row=previous_row,
                previous_plan=previous_plan,
                current_row=row,
                current_source_bpm=source_bpm,
                current_tempo_ratio=tempo_ratio,
                current_trim_start_seconds=source_trim_start_seconds,
                transition_anchor_seconds=transition_anchor_seconds,
                beat_duration=beat_duration,
                rhythm_cache=rhythm_cache,
            )
            trimmed_source_duration_seconds = max(1.0, source_duration_seconds - source_trim_start_seconds)
            adjusted_duration_seconds = trimmed_source_duration_seconds / max(tempo_ratio, 1e-6)
            overlap_seconds = 0.0 if index == len(sequence) - 1 else min(default_overlap, adjusted_duration_seconds * 0.72)
            overlap_seconds = round_to_bar(overlap_seconds, bar_duration) if overlap_seconds > 0 else 0.0
            if overlap_seconds >= adjusted_duration_seconds:
                overlap_seconds = max(bar_duration, adjusted_duration_seconds * 0.33)
                overlap_seconds = min(overlap_seconds, max(1.0, adjusted_duration_seconds - 1.0))
            outgoing_fade_seconds = 0.0 if index == len(sequence) - 1 else min(float(requested_overlap_seconds), overlap_seconds * 0.45)
            incoming_track_fade_seconds = min(incoming_fade_seconds, max(bar_duration, overlap_seconds * 0.7))

        plan.append(
            {
                "source_duration_seconds": source_duration_seconds,
                "source_trim_start_seconds": round(source_trim_start_seconds, 3),
                "source_trim_end_seconds": round(source_trim_start_seconds + trimmed_source_duration_seconds, 3),
                "start_seconds": round(current_start, 3),
                "source_bpm": round(source_bpm, 3),
                "target_bpm": round(target_bpm, 3),
                "tempo_ratio": tempo_ratio,
                "adjusted_duration_seconds": round(adjusted_duration_seconds, 3),
                "overlap_seconds": round(overlap_seconds, 3),
                "fade_in_seconds": round(incoming_track_fade_seconds, 3),
                "fade_out_seconds": round(outgoing_fade_seconds, 3),
                "volume": 0.96 if index == 0 else 0.88,
            }
        )
        current_start = snap_to_beat_grid(
            current_start + max(1.0, adjusted_duration_seconds - overlap_seconds),
            beat_duration,
        )

    return plan


def round_to_bar(seconds: float, bar_duration: float) -> float:
    if seconds <= 0 or bar_duration <= 0:
        return 0.0
    bars = max(1, round(seconds / bar_duration))
    return round(bars * bar_duration, 3)


def snap_to_beat_grid(seconds: float, beat_duration: float) -> float:
    if seconds <= 0 or beat_duration <= 0:
        return 0.0
    return round(round(seconds / beat_duration) * beat_duration, 3)


def resolve_master_bpm(sequence: list[dict]) -> float:
    bpms = []
    for row in sequence:
        bpm = resolve_row_bpm(row)
        if bpm > 0:
            bpms.append(bpm)
    bpms.sort()
    if not bpms:
        return 174.0
    return snap_to_known_bpm(bpms[len(bpms) // 2], bpms)


def resolve_canonical_bpm(rows: list[dict]) -> float:
    bpms = []
    for row in rows:
        bpm = resolve_row_bpm(row)
        if bpm > 0:
            bpms.append(bpm)
    if not bpms:
        return 174.0
    bpms.sort()
    return snap_to_known_bpm(bpms[len(bpms) // 2], bpms)


def choose_starting_row(rows: list[dict], canonical_bpm: float, rng: random.Random) -> dict:
    close_rows = [row for row in rows if abs(resolve_row_bpm(row) - canonical_bpm) <= 3.5]
    source = close_rows or rows
    return rng.choice(source)


def resolve_row_bpm(row: dict) -> float:
    candidates = [
        row.get("mix_bpm"),
        row.get("normalized_bpm"),
        row.get("estimated_bpm"),
    ]
    for candidate in candidates:
        try:
            bpm = normalize_dnb_bpm(float(candidate))
        except (TypeError, ValueError):
            bpm = 0.0
        if bpm > 0:
            return bpm
    return 174.0


def resolve_detected_bpm(row: dict) -> float:
    candidates = [
        row.get("detected_bpm"),
        row.get("normalized_bpm"),
        row.get("estimated_bpm"),
        row.get("mix_bpm"),
    ]
    for candidate in candidates:
        try:
            bpm = normalize_dnb_bpm(float(candidate))
        except (TypeError, ValueError):
            bpm = 0.0
        if bpm > 0:
            return bpm
    return 174.0


def compute_source_trim_start(
    row: dict,
    bpm: float,
    beat_offset_cache: dict[tuple[str, float], float],
) -> float:
    clip_path = str(row.get("clip_path", "")).strip()
    cache_key = (clip_path, round(bpm, 3))
    if clip_path and cache_key in beat_offset_cache:
        return beat_offset_cache[cache_key]

    metadata_offset = float(row.get("leading_beat_offset_seconds", 0.0) or 0.0)
    detected_offset = detect_phase_aligned_trim_offset(Path(clip_path), bpm, metadata_offset) if clip_path else 0.0
    if detected_offset > 0:
        beat_offset_cache[cache_key] = detected_offset
        return detected_offset

    beat_duration = beat_period_seconds(bpm)
    if beat_duration <= 0:
        return 0.0

    start_seconds = max(0.0, float(row.get("start_seconds", 0.0)))
    phase = math.fmod(start_seconds, beat_duration)
    if phase < 0:
        phase += beat_duration

    distance_to_next = beat_duration - phase if phase > 1e-4 else 0.0
    if distance_to_next <= beat_duration * 0.5:
        fallback = min(distance_to_next, max(0.0, float(row.get("duration_seconds", 30.0)) - 1.0))
        if clip_path:
            beat_offset_cache[cache_key] = fallback
        return fallback
    return 0.0


def detect_phase_aligned_trim_offset(clip_path: Path, bpm: float, metadata_offset: float) -> float:
    if not clip_path.exists() or bpm <= 0:
        return 0.0

    try:
        with wave.open(str(clip_path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frame_count = wav_file.getnframes()
            raw_frames = wav_file.readframes(frame_count)
    except (wave.Error, FileNotFoundError):
        return 0.0

    if sample_rate <= 0 or sample_width != 2 or not raw_frames:
        return 0.0

    samples = decode_pcm16(raw_frames)
    if not samples:
        return 0.0

    max_analysis_seconds = min(6.0, len(samples) / sample_rate)
    max_analysis_frames = int(max_analysis_seconds * sample_rate)
    analysis_samples = samples[:max_analysis_frames]
    envelope = compute_rms_envelope(analysis_samples, sample_rate)
    if len(envelope) < 8:
        return 0.0

    deltas = [max(0.0, envelope[index] - envelope[index - 1]) for index in range(1, len(envelope))]
    if len(deltas) < 4:
        return 0.0

    mean_delta = sum(deltas) / len(deltas)
    std_delta = compute_standard_deviation(deltas, mean_delta)
    threshold = mean_delta + (0.75 * std_delta)

    window_size = max(256, sample_rate // 20)
    hop_size = max(128, window_size // 2)
    frames_per_second = sample_rate / hop_size
    beat_period = beat_period_seconds(bpm)
    if frames_per_second <= 0 or beat_period <= 0:
        return 0.0

    search_limit_seconds = min(max_analysis_seconds, beat_period * 2.5)
    search_limit_index = max(2, min(len(deltas) - 1, int(search_limit_seconds * frames_per_second)))
    candidates: list[tuple[float, int]] = []
    for index in range(1, search_limit_index):
        value = deltas[index]
        if value < threshold:
            continue
        if value >= deltas[index - 1] and value >= deltas[min(len(deltas) - 1, index + 1)]:
            candidates.append((value, index))

    if not candidates:
        return 0.0

    peak_times = [index / frames_per_second for _, index in sorted(candidates, key=lambda item: item[1])]
    candidate_offsets = [0.0]
    if metadata_offset > 0:
        candidate_offsets.append(metadata_offset)

    max_reasonable_offset = min(beat_period * 1.25, 1.2)
    for peak_time in peak_times:
        if 0.0 < peak_time <= max_reasonable_offset:
            candidate_offsets.append(peak_time)

    best_offset = 0.0
    best_score = -1.0
    for candidate_offset in candidate_offsets:
        score = score_phase_alignment(peak_times, beat_period, candidate_offset)
        if score > best_score:
            best_score = score
            best_offset = candidate_offset

    if best_offset <= 0 or best_offset > max_reasonable_offset:
        return 0.0
    return round(best_offset, 3)


def decode_pcm16(raw_frames: bytes) -> list[int]:
    samples = array("h")
    samples.frombytes(raw_frames)
    return [int(sample) for sample in samples]


def score_phase_alignment(peak_times: list[float], beat_period: float, offset_seconds: float) -> float:
    if not peak_times or beat_period <= 0:
        return 0.0

    weighted_score = 0.0
    total_weight = 0.0
    for index, peak_time in enumerate(peak_times[:16]):
        shifted = max(0.0, peak_time - offset_seconds)
        phase = shifted % beat_period
        distance = min(phase, beat_period - phase)
        fit = max(0.0, 1.0 - (distance / max(beat_period * 0.5, 1e-6)))
        weight = 1.0 / (1.0 + (index * 0.35))
        weighted_score += fit * weight
        total_weight += weight

    return weighted_score / total_weight if total_weight > 0 else 0.0


def refine_pair_phase_alignment(
    previous_row: dict,
    previous_plan: dict,
    current_row: dict,
    current_source_bpm: float,
    current_tempo_ratio: float,
    current_trim_start_seconds: float,
    transition_anchor_seconds: float,
    beat_duration: float,
    rhythm_cache: dict[str, dict],
) -> float:
    previous_clip_path = Path(str(previous_row.get("clip_path", "")).strip())
    current_clip_path = Path(str(current_row.get("clip_path", "")).strip())
    if not previous_clip_path.exists() or not current_clip_path.exists():
        return current_trim_start_seconds

    previous_rhythm = load_clip_rhythm(previous_clip_path, rhythm_cache)
    current_rhythm = load_clip_rhythm(current_clip_path, rhythm_cache)
    if previous_rhythm is None or current_rhythm is None:
        return current_trim_start_seconds

    previous_tempo_ratio = float(previous_plan["tempo_ratio"])
    previous_elapsed_timeline = max(0.0, transition_anchor_seconds - float(previous_plan["start_seconds"]))
    previous_source_anchor = float(previous_plan["source_trim_start_seconds"]) + (previous_elapsed_timeline * previous_tempo_ratio)
    outgoing_reference_peaks = get_local_peak_times(
        previous_rhythm,
        start_seconds=max(0.0, previous_source_anchor - 0.25),
        duration_seconds=min(beat_duration * 4.0, 2.0),
        anchor_seconds=previous_source_anchor,
        tempo_ratio=previous_tempo_ratio,
    )
    if not outgoing_reference_peaks:
        return current_trim_start_seconds

    beat_period_source = beat_period_seconds(current_source_bpm)
    max_reasonable_offset = min(beat_period_source * 1.25, 1.2) if beat_period_source > 0 else 1.2
    candidate_offsets = build_phase_candidate_offsets(
        current_trim_start_seconds,
        float(current_row.get("leading_beat_offset_seconds", 0.0) or 0.0),
        beat_period_source,
        max_reasonable_offset,
    )

    best_offset = current_trim_start_seconds
    best_score = -1.0
    for candidate_offset in candidate_offsets:
        incoming_peaks = get_local_peak_times(
            current_rhythm,
            start_seconds=candidate_offset,
            duration_seconds=min(beat_duration * 4.0 * max(current_tempo_ratio, 1.0), 2.0),
            anchor_seconds=candidate_offset,
            tempo_ratio=current_tempo_ratio,
        )
        if not incoming_peaks:
            continue
        score = score_peak_alignment(outgoing_reference_peaks, incoming_peaks, beat_duration)
        if score > best_score:
            best_score = score
            best_offset = candidate_offset

    return round(best_offset, 3)


def load_clip_rhythm(clip_path: Path, rhythm_cache: dict[str, dict]) -> dict | None:
    cache_key = str(clip_path.resolve())
    if cache_key in rhythm_cache:
        return rhythm_cache[cache_key]

    try:
        with wave.open(str(clip_path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frame_count = wav_file.getnframes()
            raw_frames = wav_file.readframes(frame_count)
    except (wave.Error, FileNotFoundError):
        return None

    if sample_rate <= 0 or sample_width != 2 or not raw_frames:
        return None

    samples = decode_pcm16(raw_frames)
    if not samples:
        return None

    envelope = compute_rms_envelope(samples, sample_rate)
    if len(envelope) < 8:
        return None

    window_size = max(256, sample_rate // 20)
    hop_size = max(128, window_size // 2)
    frames_per_second = sample_rate / hop_size
    deltas = [max(0.0, envelope[index] - envelope[index - 1]) for index in range(1, len(envelope))]
    if len(deltas) < 4:
        return None

    mean_delta = sum(deltas) / len(deltas)
    std_delta = compute_standard_deviation(deltas, mean_delta)
    threshold = mean_delta + (0.75 * std_delta)
    peaks: list[float] = []
    for index in range(1, len(deltas) - 1):
        value = deltas[index]
        if value < threshold:
            continue
        if value >= deltas[index - 1] and value >= deltas[index + 1]:
            peaks.append(index / frames_per_second)

    payload = {
        "sample_rate": sample_rate,
        "frames_per_second": frames_per_second,
        "peak_times": peaks,
    }
    rhythm_cache[cache_key] = payload
    return payload


def get_local_peak_times(
    rhythm_payload: dict,
    start_seconds: float,
    duration_seconds: float,
    anchor_seconds: float,
    tempo_ratio: float,
) -> list[float]:
    peak_times = rhythm_payload.get("peak_times", [])
    if not peak_times:
        return []

    end_seconds = start_seconds + max(duration_seconds, 0.25)
    local_times: list[float] = []
    for peak_time in peak_times:
        if peak_time < start_seconds or peak_time > end_seconds:
            continue
        local_times.append((peak_time - anchor_seconds) / max(tempo_ratio, 1e-6))
    return local_times


def build_phase_candidate_offsets(
    base_offset: float,
    metadata_offset: float,
    beat_period_source: float,
    max_reasonable_offset: float,
) -> list[float]:
    candidates = {round(max(0.0, min(base_offset, max_reasonable_offset)), 3)}
    if metadata_offset > 0:
        candidates.add(round(max(0.0, min(metadata_offset, max_reasonable_offset)), 3))

    if beat_period_source > 0:
        step = max(0.01, beat_period_source / 8.0)
        for index in range(int(math.ceil(max_reasonable_offset / step)) + 1):
            candidates.add(round(min(max_reasonable_offset, index * step), 3))

    return sorted(candidates)


def score_peak_alignment(reference_peaks: list[float], candidate_peaks: list[float], beat_duration: float) -> float:
    if not reference_peaks or not candidate_peaks or beat_duration <= 0:
        return 0.0

    total_score = 0.0
    total_weight = 0.0
    for index, candidate_peak in enumerate(candidate_peaks[:12]):
        nearest_distance = min(abs(candidate_peak - reference_peak) for reference_peak in reference_peaks)
        fit = max(0.0, 1.0 - min(1.0, nearest_distance / max(beat_duration * 0.5, 1e-6)))
        weight = 1.0 / (1.0 + (index * 0.4))
        total_score += fit * weight
        total_weight += weight

    return total_score / total_weight if total_weight > 0 else 0.0


def is_bpm_compatible(candidate_bpm: float, target_bpm: float, fallback_bpm: float) -> bool:
    reference = target_bpm if target_bpm > 0 else fallback_bpm
    if reference <= 0 or candidate_bpm <= 0:
        return False
    return abs(candidate_bpm - reference) <= 6.0 or abs(candidate_bpm - fallback_bpm) <= 4.0


def compute_bpm_fit(current_bpm: float, candidate_bpm: float, canonical_bpm: float) -> float:
    pair_fit = bpm_distance_score(current_bpm, candidate_bpm)
    canonical_fit = bpm_distance_score(candidate_bpm, canonical_bpm)
    return (0.7 * pair_fit) + (0.3 * canonical_fit)


def compute_bpm_penalty(current_bpm: float, candidate_bpm: float) -> float:
    difference = abs(current_bpm - candidate_bpm)
    if difference <= 3.0:
        return 0.0
    if difference <= 6.0:
        return 0.03
    if difference <= 8.0:
        return 0.08
    return 0.2


def compute_rhythm_stability_score(row: dict) -> float:
    pulse_clarity = normalize_metric(float(row.get("pulse_clarity", 0.0)), 0.58, 0.9)
    tempo_confidence = normalize_metric(float(row.get("tempo_confidence", 0.0)), 0.25, 0.95)
    bar_pulse = normalize_metric(float(row.get("bar_pulse_strength", 0.0)), 0.2, 1.0)
    beat_offset = float(row.get("leading_beat_offset_seconds", 0.0))
    beat_entry = 1.0 if beat_offset <= 0.45 else max(0.0, 1.0 - ((beat_offset - 0.45) / 0.6))
    return (0.35 * pulse_clarity) + (0.25 * tempo_confidence) + (0.25 * bar_pulse) + (0.15 * beat_entry)


def compute_transition_readiness_score(row: dict) -> float:
    energy = normalize_metric(float(row.get("rms", 0.0)), 2500.0, 11000.0)
    density = normalize_metric(float(row.get("onset_density", 0.0)), 0.16, 0.30)
    phrase = float(row.get("phrase_energy_balance", 0.0))
    phrase_fit = max(0.0, 1.0 - min(1.0, abs(phrase) / 0.9))
    return (0.4 * energy) + (0.35 * density) + (0.25 * phrase_fit)


def compute_pair_rhythm_stability(current: dict, candidate: dict) -> float:
    current_score = compute_rhythm_stability_score(current)
    candidate_score = compute_rhythm_stability_score(candidate)
    offset_delta = abs(
        float(current.get("leading_beat_offset_seconds", 0.0))
        - float(candidate.get("leading_beat_offset_seconds", 0.0))
    )
    offset_fit = max(0.0, 1.0 - min(1.0, offset_delta / 0.35))
    return (0.4 * current_score) + (0.45 * candidate_score) + (0.15 * offset_fit)


def compute_phrase_transition_fit(current: dict, candidate: dict, target: dict) -> float:
    current_phrase = float(current.get("phrase_energy_balance", 0.0))
    candidate_phrase = float(candidate.get("phrase_energy_balance", 0.0))
    target_name = str(target.get("name", ""))

    if target_name in {"intro", "build"}:
        desired_candidate = 0.18
        desired_current = -0.12
    elif target_name in {"drop", "drop_a", "drop_b", "ride"}:
        desired_candidate = 0.05
        desired_current = -0.05
    else:
        desired_candidate = -0.18
        desired_current = -0.05

    current_fit = max(0.0, 1.0 - min(1.0, abs(current_phrase - desired_current) / 0.8))
    candidate_fit = max(0.0, 1.0 - min(1.0, abs(candidate_phrase - desired_candidate) / 0.8))
    return (0.45 * current_fit) + (0.55 * candidate_fit)


def stabilize_sequence_bpms(sequence: list[dict], canonical_bpm: float) -> list[dict]:
    if not sequence:
        return []

    observed_bpms = [resolve_row_bpm(row) for row in sequence]
    master_bpm = snap_to_known_bpm(resolve_master_bpm(sequence), observed_bpms + [canonical_bpm])
    stabilized: list[dict] = []
    for row in sequence:
        enriched = dict(row)
        row_bpm = resolve_row_bpm(enriched)
        enriched["detected_bpm"] = row_bpm
        enriched["mix_bpm"] = snap_row_bpm(row_bpm, master_bpm, canonical_bpm)
        stabilized.append(enriched)
    return stabilized


def snap_row_bpm(row_bpm: float, master_bpm: float, canonical_bpm: float) -> float:
    if row_bpm <= 0:
        return canonical_bpm if canonical_bpm > 0 else master_bpm
    if abs(row_bpm - master_bpm) <= 4.0:
        return master_bpm
    if abs(row_bpm - canonical_bpm) <= 4.0:
        return canonical_bpm
    if row_bpm >= 188.0 or row_bpm <= 164.0:
        return canonical_bpm if canonical_bpm > 0 else master_bpm
    return row_bpm


def snap_to_known_bpm(target_bpm: float, candidates: list[float]) -> float:
    usable = sorted(candidate for candidate in candidates if 166.0 <= candidate <= 180.0)
    if not usable:
        return 174.0 if target_bpm <= 0 else target_bpm
    rounded_counts: dict[float, int] = {}
    for candidate in usable:
        key = round(candidate, 3)
        rounded_counts[key] = rounded_counts.get(key, 0) + 1
    ranked = sorted(rounded_counts.items(), key=lambda item: (-item[1], abs(item[0] - target_bpm)))
    return float(ranked[0][0])


def compute_section_fit(candidate: dict, target: dict) -> float:
    energy = normalize_metric(float(candidate.get("rms", 0.0)), minimum=2500.0, maximum=11000.0)
    density = normalize_metric(float(candidate.get("onset_density", 0.0)), minimum=0.16, maximum=0.30)
    clarity = normalize_metric(float(candidate.get("pulse_clarity", 0.0)), minimum=0.55, maximum=0.90)
    candidate_energy = (0.45 * energy) + (0.35 * density) + (0.20 * clarity)
    distance = abs(candidate_energy - float(target["energy"]))
    return max(0.0, 1.0 - distance)


def compute_repetition_penalty(candidate: dict, sequence: list[dict]) -> float:
    last = sequence[-1]
    penalty = 0.0
    if str(candidate["set_id"]) == str(last["set_id"]):
        penalty += 0.08
        if abs(int(candidate["segment_index"]) - int(last["segment_index"])) <= 2:
            penalty += 0.12
    if len(sequence) >= 2 and str(candidate["set_id"]) == str(sequence[-2]["set_id"]):
        penalty += 0.05
    return penalty


def normalize_metric(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 0.0
    return max(0.0, min(1.0, (value - minimum) / (maximum - minimum)))


def load_feature_index(features_dir: Path) -> dict[tuple[str, int], list[float]]:
    feature_index: dict[tuple[str, int], list[float]] = {}
    for path in sorted(features_dir.glob("*.features.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        set_id = payload["set_id"]
        for segment in payload["segments"]:
            feature_index[(set_id, int(segment["index"]))] = [
                float(segment["features"].get(key, 0.0)) for key in FEATURE_KEYS
            ]
    return feature_index


def load_transition_model(model_path: Path) -> dict:
    checkpoint = torch.load(model_path, map_location="cpu")
    input_size = len(build_pair_vector([0.0] * len(FEATURE_KEYS), [0.0] * len(FEATURE_KEYS)))
    model = TransitionScorer(
        input_size=input_size,
        hidden_size=int(checkpoint.get("hidden_size", 64)),
        dropout=float(checkpoint.get("dropout", 0.2)),
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return {
        "model": model,
        "mean": torch.tensor(checkpoint["normalization_mean"], dtype=torch.float32),
        "std": torch.tensor(checkpoint["normalization_std"], dtype=torch.float32),
    }


def sanitize_name(value: str) -> str:
    allowed = []
    for character in value:
        if character.isalnum():
            allowed.append(character)
        elif character in {" ", "-", "_"}:
            allowed.append("_")
    collapsed = "".join(allowed).strip("_")
    while "__" in collapsed:
        collapsed = collapsed.replace("__", "_")
    return collapsed or "unknown_set"


if __name__ == "__main__":
    raise SystemExit(main())

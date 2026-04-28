import librosa
import numpy as np
import math

DNB_MIN_BPM = 160.0
DNB_MAX_BPM = 180.0


def normalize_dnb_bpm(bpm: float) -> float:
    if bpm <= 0:
        return 0.0

    base_bpm = float(bpm)
    preferred_center = 172.0
    lower_bound = DNB_MIN_BPM - 10.0
    upper_bound = DNB_MAX_BPM + 20.0
    candidates = [base_bpm * (2.0 ** shift) for shift in range(-2, 3)]
    in_range_candidates = [candidate for candidate in candidates if lower_bound <= candidate <= upper_bound]

    if in_range_candidates:
        return min(in_range_candidates, key=lambda candidate: abs(candidate - preferred_center))

    return min(candidates, key=lambda candidate: abs(candidate - preferred_center))


def compute_tempo_ratio(source_bpm: float, target_bpm: float) -> float:
    normalized_source = normalize_dnb_bpm(source_bpm)
    normalized_target = normalize_dnb_bpm(target_bpm)
    if normalized_source <= 0 or normalized_target <= 0:
        return 1.0

    ratio = normalized_target / normalized_source
    return max(0.5, min(2.0, ratio))


def build_atempo_filters(ratio: float) -> str:
    clamped_ratio = max(0.25, min(4.0, ratio))
    filters: list[str] = []
    remaining = clamped_ratio

    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0

    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5

    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def beat_period_seconds(bpm: float) -> float:
    normalized = normalize_dnb_bpm(bpm)
    if normalized <= 0:
        return 0.0
    return 60.0 / normalized


def snap_to_beat_grid(seconds: float, bpm: float, beat_offset_seconds: float = 0.0) -> float:
    period = beat_period_seconds(bpm)
    if period <= 0:
        return seconds

    offset = float(beat_offset_seconds)
    beat_index = round((seconds - offset) / period)
    snapped = offset + (beat_index * period)
    return round(float(max(0.0, snapped)), 3)


def snap_to_bar_grid(seconds: float, bpm: float, beats_per_bar: int = 4, beat_offset_seconds: float = 0.0) -> float:
    period = beat_period_seconds(bpm)
    if period <= 0:
        return seconds

    bar_duration = period * beats_per_bar
    if bar_duration <= 0:
        return seconds

    offset = float(beat_offset_seconds)
    bar_index = round((seconds - offset) / bar_duration)
    snapped = offset + (bar_index * bar_duration)
    return round(float(max(0.0, snapped)), 3)


def normalize_phase(value: float) -> float:
    return ((float(value) % 1.0) + 1.0) % 1.0


def phase_error_seconds(
    master_seconds: float,
    slave_seconds: float,
    master_bpm: float,
    slave_bpm: float,
    master_offset_seconds: float = 0.0,
    slave_offset_seconds: float = 0.0,
) -> float:
    master_period = beat_period_seconds(master_bpm)
    slave_period = beat_period_seconds(slave_bpm)
    if master_period <= 0 or slave_period <= 0:
        return 0.0

    master_phase = normalize_phase((master_seconds - master_offset_seconds) / master_period)
    slave_phase = normalize_phase((slave_seconds - slave_offset_seconds) / slave_period)
    delta = master_phase - slave_phase
    if delta > 0.5:
        delta -= 1.0
    if delta < -0.5:
        delta += 1.0

    return delta * master_period


def bpm_distance_score(left_bpm: float, right_bpm: float) -> float:
    normalized_left = normalize_dnb_bpm(left_bpm)
    normalized_right = normalize_dnb_bpm(right_bpm)
    if normalized_left <= 0 or normalized_right <= 0:
        return 0.0

    difference = abs(normalized_left - normalized_right)
    return math.exp(-(difference / 6.0))


def beat_phase_score(
    left_seconds: float,
    right_seconds: float,
    left_bpm: float,
    right_bpm: float,
    left_offset_seconds: float = 0.0,
    right_offset_seconds: float = 0.0,
) -> float:
    left_period = beat_period_seconds(left_bpm)
    right_period = beat_period_seconds(right_bpm)
    if left_period <= 0 or right_period <= 0:
        return 0.0

    left_phase = normalize_phase((left_seconds - left_offset_seconds) / left_period)
    right_phase = normalize_phase((right_seconds - right_offset_seconds) / right_period)
    difference = min(abs(left_phase - right_phase), 1.0 - abs(left_phase - right_phase))
    return max(0.0, 1.0 - (difference * 2.0))


def phrase_alignment_score(
    left_seconds: float,
    right_seconds: float,
    left_bpm: float,
    right_bpm: float,
    left_offset_seconds: float = 0.0,
    right_offset_seconds: float = 0.0,
) -> float:
    left_period = beat_period_seconds(left_bpm)
    right_period = beat_period_seconds(right_bpm)
    if left_period <= 0 or right_period <= 0:
        return 0.0

    left_phrase = left_period * 16.0
    right_phrase = right_period * 16.0
    left_phase = normalize_phase((left_seconds - left_offset_seconds) / left_phrase)
    right_phase = normalize_phase((right_seconds - right_offset_seconds) / right_phrase)
    difference = min(abs(left_phase - right_phase), 1.0 - abs(left_phase - right_phase))
    return max(0.0, 1.0 - (difference * 2.0))


def combined_transition_rhythm_score(
    left_seconds: float,
    right_seconds: float,
    left_bpm: float,
    right_bpm: float,
    left_offset_seconds: float = 0.0,
    right_offset_seconds: float = 0.0,
) -> float:
    tempo_score = bpm_distance_score(left_bpm, right_bpm)
    phase_score = beat_phase_score(left_seconds, right_seconds, left_bpm, right_bpm, left_offset_seconds, right_offset_seconds)
    phrase_score = phrase_alignment_score(left_seconds, right_seconds, left_bpm, right_bpm, left_offset_seconds, right_offset_seconds)
    return (0.45 * tempo_score) + (0.3 * phase_score) + (0.25 * phrase_score)


def estimate_beat_offset_seconds(
    beat_times: np.ndarray,
    onset_envelope: np.ndarray,
    sr: int,
    hop_length: int,
    duration_seconds: float,
    tempo: float,
) -> float:
    if beat_times.size == 0 or onset_envelope.size == 0 or tempo <= 0:
        return float(beat_times[0]) if beat_times.size > 0 else 0.0

    beat_period = beat_period_seconds(tempo)
    if beat_period <= 0:
        return float(beat_times[0]) if beat_times.size > 0 else 0.0

    first_beat = float(beat_times[0])
    coarse_search_window = min(beat_period * 0.5, 0.35)
    candidate_offsets = np.linspace(first_beat - coarse_search_window, first_beat + coarse_search_window, 121)
    beat_horizon = min(48, max(16, int(duration_seconds / beat_period) + 1))
    beat_indices = np.arange(beat_horizon, dtype=np.float32)
    coarse_frame_radius = max(1, int(round((beat_period * 0.035) / (hop_length / sr))))
    fine_frame_radius = max(1, int(round((beat_period * 0.02) / (hop_length / sr))))

    beat_weights = np.ones(beat_horizon, dtype=np.float32)
    beat_weights /= np.maximum(1.0, 1.0 + (beat_indices * 0.06))
    beat_weights *= np.where((beat_indices % 4) == 0, 1.35, 1.0)
    beat_weights *= np.where((beat_indices % 16) == 0, 1.12, 1.0)

    def score_candidate(candidate: float, frame_radius: int) -> tuple[float, float, np.ndarray] | None:
        if candidate < -beat_period or candidate > duration_seconds:
            return None

        expected_beats = candidate + (beat_indices * beat_period)
        expected_beats = expected_beats[expected_beats <= duration_seconds]
        if expected_beats.size == 0:
            return None

        frame_scores: list[float] = []
        frame_weights: list[float] = []
        peak_deltas: list[float] = []
        analysis_beats = min(expected_beats.size, 24)

        for beat_index, beat_time in enumerate(expected_beats[:analysis_beats].tolist()):
            frame = int(np.clip(librosa.time_to_frames(beat_time, sr=sr, hop_length=hop_length), 0, max(0, onset_envelope.size - 1)))
            start = max(0, frame - frame_radius)
            end = min(onset_envelope.size, frame + frame_radius + 1)
            local = onset_envelope[start:end]
            if local.size == 0:
                continue

            peak_offset = int(np.argmax(local))
            peak_frame = start + peak_offset
            peak_time = float(librosa.frames_to_time(peak_frame, sr=sr, hop_length=hop_length))
            center_value = float(onset_envelope[frame])
            peak_value = float(local[peak_offset])
            local_mean = float(np.mean(local))
            local_score = (0.28 * center_value) + (0.52 * peak_value) + (0.20 * local_mean)
            delta_seconds = peak_time - beat_time
            local_score -= abs(delta_seconds) * 0.85

            weight = float(beat_weights[min(beat_index, beat_weights.size - 1)])
            frame_scores.append(local_score * weight)
            frame_weights.append(weight)
            peak_deltas.append(delta_seconds * weight)

        if not frame_scores or not frame_weights:
            return None

        score = float(sum(frame_scores) / max(sum(frame_weights), 1e-9))
        score -= abs(candidate - first_beat) * 0.012
        if peak_deltas:
            score -= abs(sum(peak_deltas) / max(sum(frame_weights), 1e-9)) * 0.65

        return score, float(sum(peak_deltas) / max(sum(frame_weights), 1e-9)) if peak_deltas else 0.0, expected_beats

    best_offset = first_beat
    best_score = float("-inf")

    for candidate in candidate_offsets:
        scored = score_candidate(float(candidate), coarse_frame_radius)
        if scored is None:
            continue

        score, _, _ = scored
        if score > best_score:
            best_score = score
            best_offset = float(candidate)

    fine_search_window = min(beat_period * 0.18, 0.14)
    fine_candidates = np.linspace(best_offset - fine_search_window, best_offset + fine_search_window, 161)
    refined_offset = best_offset
    refined_score = best_score

    for candidate in fine_candidates:
        scored = score_candidate(float(candidate), fine_frame_radius)
        if scored is None:
            continue

        score, peak_delta, _ = scored
        if score > refined_score:
            refined_score = score
            refined_offset = float(candidate + peak_delta * 0.45)

    return round(max(0.0, refined_offset), 3)

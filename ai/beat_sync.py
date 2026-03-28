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


def snap_to_bar_grid(seconds: float, bpm: float, beats_per_bar: int = 4) -> float:
    period = beat_period_seconds(bpm)
    if period <= 0:
        return seconds

    bar_duration = period * beats_per_bar
    if bar_duration <= 0:
        return seconds

    return round(float(round(seconds / bar_duration) * bar_duration), 3)


def bpm_distance_score(left_bpm: float, right_bpm: float) -> float:
    normalized_left = normalize_dnb_bpm(left_bpm)
    normalized_right = normalize_dnb_bpm(right_bpm)
    if normalized_left <= 0 or normalized_right <= 0:
        return 0.0

    difference = abs(normalized_left - normalized_right)
    return math.exp(-(difference / 6.0))


def beat_phase_score(left_seconds: float, right_seconds: float, left_bpm: float, right_bpm: float) -> float:
    left_period = beat_period_seconds(left_bpm)
    right_period = beat_period_seconds(right_bpm)
    if left_period <= 0 or right_period <= 0:
        return 0.0

    left_phase = (left_seconds / left_period) % 1.0
    right_phase = (right_seconds / right_period) % 1.0
    difference = min(abs(left_phase - right_phase), 1.0 - abs(left_phase - right_phase))
    return max(0.0, 1.0 - (difference * 2.0))


def phrase_alignment_score(left_seconds: float, right_seconds: float, left_bpm: float, right_bpm: float) -> float:
    left_period = beat_period_seconds(left_bpm)
    right_period = beat_period_seconds(right_bpm)
    if left_period <= 0 or right_period <= 0:
        return 0.0

    left_phrase = left_period * 16.0
    right_phrase = right_period * 16.0
    left_phase = (left_seconds / left_phrase) % 1.0
    right_phase = (right_seconds / right_phrase) % 1.0
    difference = min(abs(left_phase - right_phase), 1.0 - abs(left_phase - right_phase))
    return max(0.0, 1.0 - (difference * 2.0))


def combined_transition_rhythm_score(
    left_seconds: float,
    right_seconds: float,
    left_bpm: float,
    right_bpm: float,
) -> float:
    tempo_score = bpm_distance_score(left_bpm, right_bpm)
    phase_score = beat_phase_score(left_seconds, right_seconds, left_bpm, right_bpm)
    phrase_score = phrase_alignment_score(left_seconds, right_seconds, left_bpm, right_bpm)
    return (0.45 * tempo_score) + (0.3 * phase_score) + (0.25 * phrase_score)

import warnings
warnings.filterwarnings("ignore")

import argparse
import json
import sys

import librosa
import numpy as np


# Mapping from Musical Key to Camelot Wheel Code
# 1A = Ab Minor, 1B = B Major, etc.
KEY_TO_CAMELOT = {
    "Ab minor": "1A", "B major": "1B",
    "Eb minor": "2A", "F# major": "2B",
    "Bb minor": "3A", "Db major": "3B",
    "F minor": "4A", "Ab major": "4B",
    "C minor": "5A", "Eb major": "5B",
    "G minor": "6A", "Bb major": "6B",
    "D minor": "7A", "F major": "7B",
    "A minor": "8A", "C major": "8B",
    "E minor": "9A", "G major": "9B",
    "B minor": "10A", "D major": "10B",
    "F# minor": "11A", "A major": "11B",
    "Db minor": "12A", "E major": "12B",
}


def aggregate_series(values: np.ndarray, num_points: int, percentile: float) -> np.ndarray:
    if values.size == 0:
        return np.zeros(num_points, dtype=np.float32)

    boundaries = np.linspace(0, values.size, num_points + 1, dtype=int)
    result = np.zeros(num_points, dtype=np.float32)

    for index in range(num_points):
        start = boundaries[index]
        end = boundaries[index + 1]
        if end <= start:
            end = min(values.size, start + 1)

        chunk = values[start:end]
        if chunk.size == 0:
            continue

        result[index] = float(np.percentile(chunk, percentile))

    return result


def normalize_series(values: np.ndarray, low_percentile: float, high_percentile: float, gamma: float) -> list[float]:
    if values.size == 0:
        return []

    lower = float(np.percentile(values, low_percentile))
    upper = float(np.percentile(values, high_percentile))
    if upper - lower < 1e-8:
        normalized = np.zeros_like(values, dtype=np.float32)
    else:
        normalized = np.clip((values - lower) / (upper - lower), 0.0, 1.0)

    shaped = np.power(normalized, gamma).astype(np.float32)
    return [round(float(value), 6) for value in shaped]


def extract_multiband_waveform(y: np.ndarray, sr: int, num_points: int = 1200) -> dict[str, object]:
    n_fft = 2048
    hop_length = 512

    mel = librosa.feature.melspectrogram(
        y=y,
        sr=sr,
        n_fft=n_fft,
        hop_length=hop_length,
        n_mels=96,
        fmin=30,
        fmax=16000,
        power=2.0,
    )
    mel = np.maximum(mel, 1e-10)
    mel_db = librosa.power_to_db(mel, ref=np.max)
    mel_energy = np.maximum(mel_db + 80.0, 0.0)
    frequencies = librosa.mel_frequencies(n_mels=mel.shape[0], fmin=30, fmax=16000)

    low_mask = frequencies < 180
    mid_mask = np.logical_and(frequencies >= 180, frequencies < 2200)
    high_mask = frequencies >= 2200

    def band_profile(mask: np.ndarray, percentile: float) -> np.ndarray:
        band = mel_energy[mask]
        if band.size == 0:
            return np.zeros(mel_energy.shape[1], dtype=np.float32)

        return np.percentile(band, percentile, axis=0).astype(np.float32)

    low_frames = band_profile(low_mask, 94)
    mid_frames = band_profile(mid_mask, 90)
    high_frames = band_profile(high_mask, 87)
    energy_frames = np.percentile(mel_energy, 92, axis=0).astype(np.float32)
    transient_frames = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length).astype(np.float32)

    low = normalize_series(aggregate_series(low_frames, num_points, 95), 10, 99.6, 0.9)
    mid = normalize_series(aggregate_series(mid_frames, num_points, 93), 10, 99.4, 0.92)
    high = normalize_series(aggregate_series(high_frames, num_points, 90), 8, 99.2, 0.95)
    energy = normalize_series(aggregate_series(energy_frames, num_points, 95), 12, 99.7, 0.85)
    transient = normalize_series(aggregate_series(transient_frames, num_points, 97), 60, 99.8, 0.75)

    return {
        "version": 2,
        "bands": {
            "low": low,
            "mid": mid,
            "high": high,
            "energy": energy,
            "transient": transient,
        },
    }


def get_key_from_chroma(chroma: np.ndarray) -> tuple[str, str]:
    # Krumhansl-Schmuckler Key Profiles
    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    notes = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    chroma_mean = np.mean(chroma, axis=1)

    best_key = ""
    best_score = -1.0
    is_minor = False

    for i in range(12):
        # Rotate profiles to match current root
        corr_major = np.corrcoef(chroma_mean, np.roll(major_profile, i))[0, 1]
        corr_minor = np.corrcoef(chroma_mean, np.roll(minor_profile, i))[0, 1]

        if corr_major > best_score:
            best_score = corr_major
            best_key = notes[i]
            is_minor = False
        if corr_minor > best_score:
            best_score = corr_minor
            best_key = notes[i]
            is_minor = True

    key_name = f"{best_key} {'minor' if is_minor else 'major'}"
    camelot = KEY_TO_CAMELOT.get(key_name, "Unknown")
    return key_name, camelot


def analyze_track(file_path: str, output_json: str) -> None:
    print(f"Analyzing {file_path}...")

    # Load with higher SR for better transient resolution
    y, sr = librosa.load(file_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # Robust BPM and Beat Track Detection
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo_val, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    tempo_float = float(tempo_val)
    
    # Key Detection
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=24)
    key_name, camelot = get_key_from_chroma(chroma)

    # Precision Beat Alignment
    # Detecting the first major beat to align the grid properly
    _, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    beat_offset = float(beat_times[0]) if len(beat_times) > 0 else 0.0

    waveform = extract_multiband_waveform(y, sr)

    result = {
        "bpm": round(tempo_float, 2),
        "beat_offset": round(beat_offset, 3),
        "key": key_name,
        "camelot": camelot,
        "duration": round(duration, 2),
        "waveform": waveform,
    }

    with open(output_json, "w", encoding="utf-8") as output_file:
        json.dump(result, output_file)

    print("Analysis complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        analyze_track(args.input, args.output)
    except Exception as exception:
        print(f"Error: {exception}", file=sys.stderr)
        sys.exit(1)

"""
generate_mini_mix.py
--------------------
Generates a 1:30 mini-mix from the raw_sets directory.
- Randomly picks 3 tracks
- Extracts a 30-second clip from each (random start between 30-120s)
- Detects BPM of each clip via librosa
- Adjusts each subsequent clip's tempo to match the first clip's BPM (time-stretching)
- Aligns downbeats so beats snap together at crossfade point
- Applies an 8-second linear crossfade between clips
- Exports the final 1:30 MP3
"""
from __future__ import annotations

import argparse
import random
import subprocess
import tempfile
import warnings
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore", category=UserWarning)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 1:30 mini-mix from 3 x 30s clips")
    parser.add_argument("--input-dir", required=True, help="Directory containing raw tracks (e.g. data/raw_sets)")
    parser.add_argument("--output-path", required=True, help="Output MP3 path")
    parser.add_argument("--clip-duration", type=int, default=30, help="Duration of each clip in seconds")
    parser.add_argument("--crossfade", type=int, default=8, help="Crossfade duration between clips in seconds")
    parser.add_argument("--target-bpm", type=float, default=None, help="Force a specific target BPM for all clips")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    return parser.parse_args()


def detect_bpm_and_downbeat(y: np.ndarray, sr: int) -> tuple[float, float]:
    """
    Detect BPM and the offset (in seconds) of the first strong downbeat.
    Returns (bpm, downbeat_offset_seconds).
    """
    tempo_array, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    raw_tempo = float(tempo_array[0]) if hasattr(tempo_array, "__len__") else float(tempo_array)

    # Normalise to DnB range (~170 BPM)
    bpm = raw_tempo
    if bpm > 0 and bpm < 100:
        bpm *= 2.0
    elif bpm > 300:
        bpm /= 2.0

    if bpm <= 0:
        bpm = 174.0  # fallback for silent / unrecognisable audio

    # Find first beat position in seconds
    if len(beat_frames) > 0:
        downbeat_offset = float(librosa.frames_to_time(beat_frames[0], sr=sr))
    else:
        downbeat_offset = 0.0

    return bpm, downbeat_offset


def time_stretch_to_bpm(y: np.ndarray, orig_bpm: float, target_bpm: float) -> np.ndarray:
    """
    Time-stretch `y` so its tempo matches `target_bpm`.
    Uses librosa phase-vocoder (no pitch artefacts from raw speed change).
    """
    if orig_bpm <= 0 or target_bpm <= 0:
        return y

    rate = target_bpm / orig_bpm
    if abs(1.0 - rate) < 0.002:
        return y  # already close enough — skip processing

    print(f"    Time-stretching {orig_bpm:.1f} -> {target_bpm:.1f} BPM (rate={rate:.4f})")
    return librosa.effects.time_stretch(y, rate=rate)


def beat_align_trim(y: np.ndarray, sr: int, bpm: float, downbeat_offset: float, target_duration: float) -> np.ndarray:
    """
    Trim the clip so it starts exactly on the downbeat and is exactly
    `target_duration` seconds long (zero-padded if shorter).
    """
    start_sample = int(downbeat_offset * sr)
    target_samples = int(target_duration * sr)

    if start_sample >= len(y):
        start_sample = 0

    trimmed = y[start_sample:]
    if len(trimmed) < target_samples:
        trimmed = np.pad(trimmed, (0, target_samples - len(trimmed)))
    else:
        trimmed = trimmed[:target_samples]

    return trimmed.astype(np.float32)


def crossfade_mix(clip_a: np.ndarray, clip_b: np.ndarray, sr: int, crossfade_sec: int) -> np.ndarray:
    """
    Linearly crossfade clip_b into clip_a over `crossfade_sec` seconds.
    clip_a fades out, clip_b fades in during the overlap region.
    """
    cf_samples = min(int(crossfade_sec * sr), len(clip_a), len(clip_b))

    fade_out = np.linspace(1.0, 0.0, cf_samples, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, cf_samples, dtype=np.float32)

    overlap_start = len(clip_a) - cf_samples
    out_len = overlap_start + len(clip_b)
    mixed = np.zeros(out_len, dtype=np.float32)

    # Non-overlapping part of clip_a
    mixed[:overlap_start] = clip_a[:overlap_start]

    # Overlapping region
    a_overlap = clip_a[overlap_start:overlap_start + cf_samples] * fade_out
    b_overlap = clip_b[:cf_samples] * fade_in
    mixed[overlap_start:overlap_start + cf_samples] = a_overlap + b_overlap

    # Rest of clip_b after crossfade
    if len(clip_b) > cf_samples:
        mixed[overlap_start + cf_samples:overlap_start + len(clip_b)] = clip_b[cf_samples:]

    return mixed


def main() -> int:
    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    input_dir = Path(args.input_dir)
    output_path = Path(args.output_path)

    if not input_dir.is_dir():
        print(f"Error: {input_dir} does not exist or is not a directory.")
        return 1

    tracks = [p for p in input_dir.iterdir() if p.suffix.lower() in {".mp3", ".wav", ".flac"}]
    if len(tracks) < 3:
        print(f"Error: need at least 3 tracks in {input_dir}, found {len(tracks)}")
        return 1

    selected = random.sample(tracks, 3)
    print("Selected Tracks:")
    for t in selected:
        print(f"  - {t.name}")

    sr = 44100
    clip_duration = args.clip_duration
    crossfade_sec = args.crossfade

    raw_clips: list[np.ndarray] = []
    bpms: list[float] = []

    # ── Step 1: Load and analyse each clip ───────────────────────────────────
    for i, track in enumerate(selected):
        # Random start, but not too close to the beginning (intros) or end
        start_sec = random.uniform(40.0, 130.0)
        print(f"\n[Track {i+1}] {track.name}  (start={start_sec:.1f}s)")

        y, _ = librosa.load(track, sr=sr, offset=start_sec, duration=clip_duration, mono=True)
        bpm, downbeat = detect_bpm_and_downbeat(y, sr)
        print(f"  Detected BPM: {bpm:.1f}  |  downbeat offset: {downbeat:.3f}s")

        raw_clips.append((y, bpm, downbeat))
        bpms.append(bpm)

    # ── Step 2: Choose reference BPM ─────────────────────────────────────────
    ref_bpm: float = args.target_bpm if args.target_bpm else bpms[0]
    print(f"\nMaster BPM: {ref_bpm:.1f}")

    # ── Step 3: Stretch each clip to ref BPM, then trim to downbeat ──────────
    aligned: list[np.ndarray] = []
    for i, (y, orig_bpm, downbeat) in enumerate(raw_clips):
        print(f"\n[Track {i+1}] aligning...")
        stretched = time_stretch_to_bpm(y, orig_bpm, ref_bpm)

        # After stretching the downbeat offset also shifts proportionally
        adjusted_downbeat = downbeat * (ref_bpm / orig_bpm) if orig_bpm > 0 else downbeat
        clip = beat_align_trim(stretched, sr, ref_bpm, adjusted_downbeat, float(clip_duration))
        aligned.append(clip)
        print(f"  Clip ready: {len(clip)/sr:.2f}s")

    # ── Step 4: Crossfade 1→2→3 ──────────────────────────────────────────────
    print("\nMixing clips with beat-aligned crossfades...")
    mix = crossfade_mix(aligned[0], aligned[1], sr, crossfade_sec)
    mix = crossfade_mix(mix, aligned[2], sr, crossfade_sec)

    total_seconds = len(mix) / sr
    print(f"Total mix duration: {total_seconds:.1f}s")

    # ── Step 5: Normalise output ──────────────────────────────────────────────
    peak = np.max(np.abs(mix))
    if peak > 0.95:
        mix = mix * (0.93 / peak)

    # ── Step 6: Export to MP3 ────────────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    sf.write(str(tmp_path), mix, sr, subtype="PCM_16")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(tmp_path),
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    tmp_path.unlink(missing_ok=True)

    print(f"\n[DONE] Mini-mix saved: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

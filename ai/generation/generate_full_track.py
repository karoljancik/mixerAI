from __future__ import annotations

import argparse
import math
import random
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

try:
    import torch
except ImportError:
    torch = None


SAMPLE_RATE = 44100
STYLE_PRESETS = {
    "liquid": {
        "bpm": 174,
        "sub_gain": 0.55,
        "reese_gain": 0.22,
        "pad_gain": 0.32,
        "hat_density": 0.95,
        "melodic_spread": 1.0,
        "darkness": 0.35,
    },
    "deep": {
        "bpm": 172,
        "sub_gain": 0.72,
        "reese_gain": 0.34,
        "pad_gain": 0.12,
        "hat_density": 0.82,
        "melodic_spread": 0.45,
        "darkness": 0.82,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a full DnB track conditioned on style")
    parser.add_argument("--style", choices=sorted(STYLE_PRESETS), required=True, help="Target style")
    parser.add_argument("--duration-seconds", type=int, default=144, help="Track length")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--style-model-path", help="Optional style classifier checkpoint")
    parser.add_argument("--output-path", required=True, help="Output WAV or MP3 path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    style_profile = build_style_profile(args.style, args.style_model_path)
    arrangement = build_arrangement(args.duration_seconds)
    samples = render_track(args.style, style_profile, arrangement, rng)
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_output(samples, output_path)

    print(f"style={args.style}")
    print(f"duration_seconds={args.duration_seconds}")
    print(f"output_path={output_path}")
    return 0


def build_style_profile(style: str, style_model_path: str | None) -> dict[str, float]:
    profile = dict(STYLE_PRESETS[style])
    if not style_model_path or torch is None:
        return profile

    checkpoint_path = Path(style_model_path)
    if not checkpoint_path.exists():
        return profile

    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    centroids = checkpoint.get("style_centroids", {})
    centroid = centroids.get(style)
    if not centroid:
        return profile

    profile["sub_gain"] = clamp(profile["sub_gain"] + (float(centroid[0]) / 5000.0), 0.4, 0.9)
    profile["reese_gain"] = clamp(profile["reese_gain"] + (float(centroid[3]) * 0.08), 0.12, 0.45)
    profile["pad_gain"] = clamp(profile["pad_gain"] + (float(centroid[7]) * 0.12), 0.08, 0.4)
    return profile


def build_arrangement(duration_seconds: int) -> list[tuple[str, int]]:
    section_bars = [
        ("intro", 32),
        ("build", 16),
        ("drop_a", 32),
        ("breakdown", 16),
        ("drop_b", 32),
        ("outro", 16),
    ]
    return section_bars


def render_track(style: str, style_profile: dict[str, float], arrangement: list[tuple[str, int]], rng: random.Random) -> list[int]:
    bpm = int(style_profile["bpm"])
    beat_seconds = 60.0 / bpm
    bar_seconds = beat_seconds * 4.0
    total_seconds = sum(bars * bar_seconds for _, bars in arrangement)
    total_samples = int(total_seconds * SAMPLE_RATE)
    mix = [0.0] * total_samples

    cursor_bar = 0
    bass_root_cycle = [43, 43, 46, 41, 43, 48, 46, 41]
    chord_offsets_liquid = [0, 7, 12]
    chord_offsets_deep = [0, 5, 10]

    for section_name, bars in arrangement:
        section_start = cursor_bar * bar_seconds
        section_energy = section_energy_multiplier(section_name)
        for bar_index in range(bars):
            absolute_bar = cursor_bar + bar_index
            bar_start = section_start + (bar_index * bar_seconds)
            root_midi = bass_root_cycle[absolute_bar % len(bass_root_cycle)]

            add_drum_bar(mix, bar_start, bpm, section_energy, style_profile, rng)
            add_bass_bar(mix, bar_start, bpm, root_midi, section_name, style_profile, rng)

            if style == "liquid":
                add_pad_bar(mix, bar_start, bpm, root_midi, chord_offsets_liquid, section_name, style_profile)
            else:
                add_reese_bar(mix, bar_start, bpm, root_midi, chord_offsets_deep, section_name, style_profile)

        cursor_bar += bars

    limiter_scale = max(1.0, max(abs(sample) for sample in mix) / 0.92)
    return [int(clamp(sample / limiter_scale, -1.0, 1.0) * 32767) for sample in mix]


def add_drum_bar(
    mix: list[float],
    bar_start: float,
    bpm: int,
    energy: float,
    style_profile: dict[str, float],
    rng: random.Random,
) -> None:
    beat_seconds = 60.0 / bpm
    kick_times = [bar_start + (beat_seconds * offset) for offset in (0.0, 1.5, 2.0, 3.5)]
    snare_times = [bar_start + (beat_seconds * offset) for offset in (1.0, 3.0)]
    hat_step = beat_seconds / 2.0
    hat_count = 8 if style_profile["hat_density"] >= 0.9 else 6
    hat_times = [bar_start + (index * hat_step) for index in range(hat_count)]

    for time_seconds in kick_times:
        add_kick(mix, time_seconds, 0.95 * energy)
    for time_seconds in snare_times:
        add_snare(mix, time_seconds, 0.55 * energy, rng)
    for time_seconds in hat_times:
        add_hat(mix, time_seconds, 0.18 * energy, rng)


def add_bass_bar(
    mix: list[float],
    bar_start: float,
    bpm: int,
    root_midi: int,
    section_name: str,
    style_profile: dict[str, float],
    rng: random.Random,
) -> None:
    beat_seconds = 60.0 / bpm
    pattern = [0.0, 0.75, 1.5, 2.25, 3.0]
    note_lengths = [0.55, 0.35, 0.45, 0.35, 0.65]
    for index, beat_offset in enumerate(pattern):
        start = bar_start + (beat_offset * beat_seconds)
        duration = note_lengths[index] * beat_seconds
        pitch = midi_to_frequency(root_midi + (12 if section_name.startswith("drop") and index % 2 == 1 else 0))
        drive = 1.15 if section_name.startswith("drop") else 0.92
        add_sub_note(mix, start, duration, pitch, style_profile["sub_gain"] * drive)

        if style_profile["reese_gain"] > 0.16:
            detune = 0.7 + (0.3 * rng.random())
            add_reese_note(mix, start, duration, pitch * (1.0 - detune * 0.01), style_profile["reese_gain"] * drive)
            add_reese_note(mix, start, duration, pitch * (1.0 + detune * 0.01), style_profile["reese_gain"] * drive)


def add_pad_bar(
    mix: list[float],
    bar_start: float,
    bpm: int,
    root_midi: int,
    chord_offsets: list[int],
    section_name: str,
    style_profile: dict[str, float],
) -> None:
    if section_name in {"drop_a", "drop_b"}:
        gain = style_profile["pad_gain"] * 0.65
    else:
        gain = style_profile["pad_gain"]
    duration = (60.0 / bpm) * 4.0
    for offset in chord_offsets:
        add_soft_tone(mix, bar_start, duration, midi_to_frequency(root_midi + 12 + offset), gain / len(chord_offsets))


def add_reese_bar(
    mix: list[float],
    bar_start: float,
    bpm: int,
    root_midi: int,
    chord_offsets: list[int],
    section_name: str,
    style_profile: dict[str, float],
) -> None:
    if not section_name.startswith("drop"):
        return
    duration = (60.0 / bpm) * 4.0
    gain = style_profile["reese_gain"] * 0.55
    for offset in chord_offsets:
        add_reese_note(mix, bar_start, duration, midi_to_frequency(root_midi + offset), gain / len(chord_offsets))


def add_kick(mix: list[float], start_seconds: float, gain: float) -> None:
    start_sample = int(start_seconds * SAMPLE_RATE)
    length = int(0.18 * SAMPLE_RATE)
    for offset in range(length):
        position = start_sample + offset
        if position >= len(mix):
            break
        progress = offset / length
        envelope = math.exp(-progress * 9.0)
        frequency = 120.0 - (80.0 * progress)
        mix[position] += math.sin(2.0 * math.pi * frequency * (offset / SAMPLE_RATE)) * envelope * gain


def add_snare(mix: list[float], start_seconds: float, gain: float, rng: random.Random) -> None:
    start_sample = int(start_seconds * SAMPLE_RATE)
    length = int(0.16 * SAMPLE_RATE)
    for offset in range(length):
        position = start_sample + offset
        if position >= len(mix):
            break
        progress = offset / length
        noise = (rng.random() * 2.0) - 1.0
        tone = math.sin(2.0 * math.pi * 180.0 * (offset / SAMPLE_RATE)) * 0.25
        envelope = math.exp(-progress * 18.0)
        mix[position] += (noise * 0.8 + tone) * envelope * gain


def add_hat(mix: list[float], start_seconds: float, gain: float, rng: random.Random) -> None:
    start_sample = int(start_seconds * SAMPLE_RATE)
    length = int(0.05 * SAMPLE_RATE)
    for offset in range(length):
        position = start_sample + offset
        if position >= len(mix):
            break
        progress = offset / length
        noise = (rng.random() * 2.0) - 1.0
        envelope = math.exp(-progress * 36.0)
        mix[position] += noise * envelope * gain


def add_sub_note(mix: list[float], start_seconds: float, duration_seconds: float, frequency: float, gain: float) -> None:
    start_sample = int(start_seconds * SAMPLE_RATE)
    length = int(duration_seconds * SAMPLE_RATE)
    for offset in range(length):
        position = start_sample + offset
        if position >= len(mix):
            break
        progress = offset / max(1, length)
        envelope = min(1.0, progress * 18.0) * math.exp(-max(0.0, progress - 0.8) * 7.0)
        mix[position] += math.sin(2.0 * math.pi * frequency * (offset / SAMPLE_RATE)) * envelope * gain


def add_reese_note(mix: list[float], start_seconds: float, duration_seconds: float, frequency: float, gain: float) -> None:
    start_sample = int(start_seconds * SAMPLE_RATE)
    length = int(duration_seconds * SAMPLE_RATE)
    for offset in range(length):
        position = start_sample + offset
        if position >= len(mix):
            break
        progress = offset / max(1, length)
        envelope = min(1.0, progress * 20.0) * math.exp(-max(0.0, progress - 0.88) * 9.0)
        t = offset / SAMPLE_RATE
        wave = (
            math.sin(2.0 * math.pi * frequency * t)
            + 0.6 * math.sin(2.0 * math.pi * frequency * 2.01 * t)
            + 0.3 * math.sin(2.0 * math.pi * frequency * 3.02 * t)
        )
        mix[position] += math.tanh(wave * 1.35) * envelope * gain


def add_soft_tone(mix: list[float], start_seconds: float, duration_seconds: float, frequency: float, gain: float) -> None:
    start_sample = int(start_seconds * SAMPLE_RATE)
    length = int(duration_seconds * SAMPLE_RATE)
    for offset in range(length):
        position = start_sample + offset
        if position >= len(mix):
            break
        progress = offset / max(1, length)
        envelope = min(1.0, progress * 10.0) * math.exp(-max(0.0, progress - 0.8) * 3.0)
        t = offset / SAMPLE_RATE
        wave = (
            math.sin(2.0 * math.pi * frequency * t)
            + 0.4 * math.sin(2.0 * math.pi * frequency * 2.0 * t)
            + 0.2 * math.sin(2.0 * math.pi * frequency * 3.0 * t)
        )
        mix[position] += wave * envelope * gain


def write_output(samples: list[int], output_path: Path) -> None:
    if output_path.suffix.lower() == ".wav":
        write_wav(samples, output_path)
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        write_wav(samples, temp_path)
        convert_to_output(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_wav(samples: list[int], output_path: Path) -> None:
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


def convert_to_output(source_path: Path, output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(source_path),
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
        raise RuntimeError("ffmpeg is required to export generated tracks as MP3.") from exception
    except subprocess.CalledProcessError as exception:
        raise RuntimeError(f"ffmpeg export failed: {exception.stderr}") from exception


def section_energy_multiplier(section_name: str) -> float:
    return {
        "intro": 0.55,
        "build": 0.72,
        "drop_a": 1.0,
        "breakdown": 0.48,
        "drop_b": 1.05,
        "outro": 0.62,
    }.get(section_name, 0.8)


def midi_to_frequency(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


if __name__ == "__main__":
    raise SystemExit(main())

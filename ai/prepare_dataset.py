from __future__ import annotations

import argparse
import json
import math
import sys
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff"}


@dataclass
class SegmentRecord:
    index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float


@dataclass
class SetManifest:
    set_id: str
    title: str
    source_path: str
    duration_seconds: float
    window_seconds: int
    hop_seconds: int
    segments: list[SegmentRecord]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare MixerAI set manifests")
    parser.add_argument("--input-dir", required=True, help="Directory with full DJ sets")
    parser.add_argument("--output-dir", required=True, help="Directory for generated manifests")
    parser.add_argument("--window-seconds", type=int, default=30, help="Segment window size")
    parser.add_argument("--hop-seconds", type=int, default=15, help="Segment hop size")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    audio_files = sorted(path for path in input_dir.iterdir() if path.suffix.lower() in SUPPORTED_EXTENSIONS)
    manifests: list[Path] = []

    for audio_file in audio_files:
        duration_seconds = read_duration_seconds(audio_file)
        manifest = build_manifest(audio_file, duration_seconds, args.window_seconds, args.hop_seconds)
        manifest_path = output_dir / f"{manifest.set_id}.json"
        manifest_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        manifests.append(manifest_path)

    print(f"prepared_sets={len(manifests)}")
    for manifest_path in manifests:
        print_safe(str(manifest_path))

    return 0


def build_manifest(audio_file: Path, duration_seconds: float, window_seconds: int, hop_seconds: int) -> SetManifest:
    segments = build_segments(duration_seconds, window_seconds, hop_seconds)

    return SetManifest(
        set_id=audio_file.stem,
        title=audio_file.stem.replace("_", " ").replace("-", " ").strip(),
        source_path=str(audio_file.resolve()),
        duration_seconds=duration_seconds,
        window_seconds=window_seconds,
        hop_seconds=hop_seconds,
        segments=segments,
    )


def build_segments(duration_seconds: float, window_seconds: int, hop_seconds: int) -> list[SegmentRecord]:
    if duration_seconds <= 0:
        return []

    if duration_seconds <= window_seconds:
        return [SegmentRecord(index=0, start_seconds=0.0, end_seconds=duration_seconds, duration_seconds=duration_seconds)]

    segment_count = math.floor((duration_seconds - window_seconds) / hop_seconds) + 1
    segments: list[SegmentRecord] = []

    for index in range(segment_count):
        start_seconds = index * hop_seconds
        end_seconds = min(start_seconds + window_seconds, duration_seconds)
        segments.append(
            SegmentRecord(
                index=index,
                start_seconds=round(start_seconds, 3),
                end_seconds=round(end_seconds, 3),
                duration_seconds=round(end_seconds - start_seconds, 3),
            )
        )

    last_end = segments[-1].end_seconds
    if last_end < duration_seconds:
        start_seconds = max(0.0, duration_seconds - window_seconds)
        segments.append(
            SegmentRecord(
                index=len(segments),
                start_seconds=round(start_seconds, 3),
                end_seconds=round(duration_seconds, 3),
                duration_seconds=round(duration_seconds - start_seconds, 3),
            )
        )

    return segments


def read_duration_seconds(audio_file: Path) -> float:
    if audio_file.suffix.lower() == ".wav":
        return read_wav_duration_seconds(audio_file)

    return read_duration_with_ffprobe(audio_file)


def read_wav_duration_seconds(audio_file: Path) -> float:
    with wave.open(str(audio_file), "rb") as wav_file:
        frames = wav_file.getnframes()
        frame_rate = wav_file.getframerate()
        if frame_rate == 0:
            return 0.0
        return frames / float(frame_rate)


def read_duration_with_ffprobe(audio_file: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_file),
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exception:
        raise RuntimeError("ffprobe is required to read non-WAV audio durations.") from exception
    except subprocess.CalledProcessError as exception:
        raise RuntimeError(f"ffprobe failed for file: {audio_file}") from exception

    output = result.stdout.strip()
    if not output:
        return 0.0

    try:
        return float(output)
    except ValueError as exception:
        raise RuntimeError(f"Invalid duration returned by ffprobe for file: {audio_file}") from exception


def print_safe(value: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = value.encode(encoding, errors="backslashreplace").decode(encoding)
    print(safe_text)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export concrete audio clips from a generation dataset JSONL manifest."
    )
    parser.add_argument("--dataset-path", required=True, help="Path to generation_dataset JSONL")
    parser.add_argument("--output-dir", required=True, help="Directory for exported clips")
    parser.add_argument("--sample-rate", type=int, default=32000, help="Target mono WAV sample rate")
    parser.add_argument(
        "--limit-per-style",
        type=int,
        default=0,
        help="Optional max exported clips per style, 0 means no limit",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite clips that already exist",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset_path)
    output_dir = Path(args.output_dir)
    rows = load_rows(dataset_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    exported_manifest_path = output_dir / "clips_manifest.jsonl"

    style_counts: dict[str, int] = {}
    exported_rows: list[dict] = []

    for row in rows:
        style = str(row["style"]).strip().lower()
        count = style_counts.get(style, 0)
        if args.limit_per_style > 0 and count >= args.limit_per_style:
            continue

        relative_name = build_relative_name(row)
        clip_path = output_dir / style / relative_name
        clip_path.parent.mkdir(parents=True, exist_ok=True)

        if args.overwrite or not clip_path.exists():
            export_clip(
                source_path=Path(row["source_path"]),
                output_path=clip_path,
                start_seconds=float(row["start_seconds"]),
                duration_seconds=float(row["duration_seconds"]),
                sample_rate=args.sample_rate,
            )

        exported_row = dict(row)
        exported_row["export_path"] = str(clip_path.resolve())
        exported_rows.append(exported_row)
        style_counts[style] = count + 1

    with exported_manifest_path.open("w", encoding="utf-8") as handle:
        for row in exported_rows:
            handle.write(json.dumps(row) + "\n")

    print(f"exported_clips={len(exported_rows)}")
    for style, count in sorted(style_counts.items()):
        print(f"style_{style}={count}")
    print(f"clips_manifest={exported_manifest_path}")
    return 0


def load_rows(dataset_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_relative_name(row: dict) -> str:
    set_id = sanitize_name(str(row["set_id"]))
    segment_index = int(row["segment_index"])
    start_ms = int(round(float(row["start_seconds"]) * 1000.0))
    return f"{set_id}__seg-{segment_index:04d}__start-{start_ms:08d}.wav"


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


def export_clip(
    source_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
    sample_rate: int,
) -> None:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        str(source_path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-sample_fmt",
        "s16",
        "-y",
        str(output_path),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exception:
        raise RuntimeError("ffmpeg is required to export generation clips.") from exception
    except subprocess.CalledProcessError as exception:
        raise RuntimeError(
            f"ffmpeg failed while exporting clip from {source_path}: {exception.stderr}"
        ) from exception


if __name__ == "__main__":
    raise SystemExit(main())

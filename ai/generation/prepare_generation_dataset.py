from __future__ import annotations

import argparse
import json
from pathlib import Path


TRAINABLE_STYLES = {"liquid", "deep"}
KNOWN_LABELS = TRAINABLE_STYLES | {"exclude"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a clip-level dataset manifest for future full-track generation training."
    )
    parser.add_argument("--manifests-dir", required=True, help="Directory with set manifests")
    parser.add_argument("--features-dir", required=True, help="Directory with per-segment feature manifests")
    parser.add_argument("--style-map-path", required=True, help="JSON file mapping set_id to liquid|deep|exclude")
    parser.add_argument("--output-path", required=True, help="Output JSONL path")
    parser.add_argument(
        "--min-pulse-clarity",
        type=float,
        default=0.6,
        help="Reject segments that are too rhythmically unstable for training",
    )
    parser.add_argument(
        "--min-duration-seconds",
        type=float,
        default=29.0,
        help="Reject truncated segments shorter than this duration",
    )
    parser.add_argument(
        "--min-tempo-confidence",
        type=float,
        default=0.08,
        help="Reject segments with unreliable tempo estimation",
    )
    parser.add_argument(
        "--min-bar-pulse-strength",
        type=float,
        default=0.12,
        help="Reject segments without a sufficiently stable bar pulse",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifests_dir = Path(args.manifests_dir)
    features_dir = Path(args.features_dir)
    output_path = Path(args.output_path)
    style_map = load_style_map(Path(args.style_map_path))

    rows: list[dict] = []
    skipped_missing_features = 0
    skipped_unlabeled = 0
    skipped_excluded = 0

    for manifest_path in sorted(manifests_dir.glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        set_id = str(manifest.get("set_id", "")).strip()
        if not set_id:
            continue

        style = style_map.get(set_id)
        if style is None:
            skipped_unlabeled += 1
            continue
        if style not in TRAINABLE_STYLES:
            skipped_excluded += 1
            continue

        feature_path = features_dir / f"{set_id}.features.json"
        if not feature_path.exists():
            skipped_missing_features += 1
            continue

        feature_manifest = json.loads(feature_path.read_text(encoding="utf-8"))
        rows.extend(
            build_rows(
                manifest,
                feature_manifest,
                style,
                min_pulse_clarity=args.min_pulse_clarity,
                min_duration_seconds=args.min_duration_seconds,
                min_tempo_confidence=args.min_tempo_confidence,
                min_bar_pulse_strength=args.min_bar_pulse_strength,
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    print(f"clip_rows={len(rows)}")
    print(f"skipped_unlabeled_sets={skipped_unlabeled}")
    print(f"skipped_excluded_sets={skipped_excluded}")
    print(f"skipped_missing_features={skipped_missing_features}")
    print(f"output_path={output_path}")
    return 0


def load_style_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(key): str(value).strip().lower()
        for key, value in payload.items()
        if str(value).strip().lower() in KNOWN_LABELS
    }


def build_rows(
    manifest: dict,
    feature_manifest: dict,
    style: str,
    min_pulse_clarity: float,
    min_duration_seconds: float,
    min_tempo_confidence: float,
    min_bar_pulse_strength: float,
) -> list[dict]:
    segments = manifest.get("segments", [])
    feature_segments = {
        int(segment["index"]): segment
        for segment in feature_manifest.get("segments", [])
        if "index" in segment
    }

    rows: list[dict] = []
    for segment in segments:
        segment_index = int(segment.get("index", -1))
        feature_segment = feature_segments.get(segment_index)
        if feature_segment is None:
            continue

        duration_seconds = float(segment.get("duration_seconds", 0.0))
        feature_map = feature_segment.get("features", {})
        pulse_clarity = float(feature_map.get("pulse_clarity", 0.0))
        normalized_bpm = float(feature_map.get("normalized_bpm", 0.0))
        energy = float(feature_map.get("rms", 0.0))
        onset_density = float(feature_map.get("onset_density", 0.0))
        leading_beat_offset_seconds = float(feature_map.get("leading_beat_offset_seconds", 0.0))
        tempo_confidence = float(feature_map.get("tempo_confidence", 0.0))
        bar_pulse_strength = float(feature_map.get("bar_pulse_strength", 0.0))
        phrase_energy_balance = float(feature_map.get("phrase_energy_balance", 0.0))

        if duration_seconds < min_duration_seconds:
            continue
        if pulse_clarity < min_pulse_clarity:
            continue
        if tempo_confidence < min_tempo_confidence:
            continue
        if bar_pulse_strength < min_bar_pulse_strength:
            continue
        if normalized_bpm < 160.0 or normalized_bpm > 180.0:
            continue

        rows.append(
            {
                "set_id": manifest["set_id"],
                "style": style,
                "source_path": manifest["source_path"],
                "segment_index": segment_index,
                "start_seconds": round(float(segment.get("start_seconds", 0.0)), 3),
                "end_seconds": round(float(segment.get("end_seconds", 0.0)), 3),
                "duration_seconds": round(duration_seconds, 3),
                "normalized_bpm": round(normalized_bpm, 3),
                "pulse_clarity": round(pulse_clarity, 6),
                "rms": round(energy, 6),
                "onset_density": round(onset_density, 6),
                "leading_beat_offset_seconds": round(leading_beat_offset_seconds, 6),
                "tempo_confidence": round(tempo_confidence, 6),
                "bar_pulse_strength": round(bar_pulse_strength, 6),
                "phrase_energy_balance": round(phrase_energy_balance, 6),
            }
        )

    return rows


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from style_modeling import STYLE_FEATURE_KEYS


LIQUID_HINTS = ("monrroe", "glxy", "nu_tone", "nu tone", "document one", "monroe", "koherent")
DEEP_HINTS = ("waeys", "klinical", "qzb", "sustance", "kasra", "enei", "kyrist", "thread", "zero t")
TRAINABLE_STYLES = {"liquid", "deep"}
KNOWN_LABELS = TRAINABLE_STYLES | {"exclude"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a style-labeled dataset from feature manifests")
    parser.add_argument("--features-dir", required=True, help="Directory with *.features.json manifests")
    parser.add_argument("--output-path", required=True, help="Output JSONL path")
    parser.add_argument("--style-map-path", help="Explicit style map JSON { set_id: liquid|deep|exclude }")
    parser.add_argument(
        "--allow-name-inference",
        action="store_true",
        help="Allow fallback style guessing from set names when a curated style map is incomplete",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    features_dir = Path(args.features_dir)
    output_path = Path(args.output_path)
    style_map = load_style_map(Path(args.style_map_path)) if args.style_map_path else {}
    if not style_map and not args.allow_name_inference:
        raise RuntimeError("Provide --style-map-path or explicitly opt into --allow-name-inference.")

    rows: list[dict] = []
    for path in sorted(features_dir.glob("*.features.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        set_id = payload["set_id"]
        style = style_map.get(set_id)
        if style is None and args.allow_name_inference:
            style = infer_style(set_id)
        if style is None or style not in TRAINABLE_STYLES:
            continue

        vector = summarize_style_features(payload)
        rows.append(
            {
                "set_id": set_id,
                "style": style,
                "features": vector,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    print(f"style_rows={len(rows)}")
    print(f"output_path={output_path}")
    return 0


def load_style_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(key): str(value).strip().lower()
        for key, value in payload.items()
        if str(value).strip().lower() in KNOWN_LABELS
    }


def infer_style(set_id: str) -> str | None:
    normalized = set_id.lower()
    if any(hint in normalized for hint in LIQUID_HINTS):
        return "liquid"
    if any(hint in normalized for hint in DEEP_HINTS):
        return "deep"
    return None


def summarize_style_features(feature_manifest: dict) -> list[float]:
    segments = feature_manifest.get("segments", [])
    features_by_key: dict[str, list[float]] = {
        "rms": [],
        "dynamic_range": [],
        "onset_density": [],
        "normalized_bpm": [],
        "pulse_clarity": [],
        "bar_pulse_strength": [],
        "phrase_energy_balance": [],
        "low_energy_ratio": [],
        "beat_interval_cv": [],
    }

    for segment in segments:
        feature_map = segment.get("features", {})
        for key in features_by_key:
            features_by_key[key].append(float(feature_map.get(key, 0.0)))

    vector = [
        mean(features_by_key["rms"]),
        std(features_by_key["rms"]),
        mean(features_by_key["dynamic_range"]),
        mean(features_by_key["onset_density"]),
        mean(features_by_key["normalized_bpm"]),
        mean(features_by_key["pulse_clarity"]),
        mean(features_by_key["bar_pulse_strength"]),
        mean(features_by_key["phrase_energy_balance"]),
        mean(features_by_key["low_energy_ratio"]),
        mean(features_by_key["beat_interval_cv"]),
    ]

    if len(vector) != len(STYLE_FEATURE_KEYS):
        raise RuntimeError("Style feature summary length does not match STYLE_FEATURE_KEYS.")
    return [round(value, 6) for value in vector]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return variance ** 0.5


if __name__ == "__main__":
    raise SystemExit(main())

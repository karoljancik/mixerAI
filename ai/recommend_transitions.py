from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import torch
except ImportError as exception:
    raise SystemExit("PyTorch is required for transition recommendations.") from exception

from beat_sync import combined_transition_rhythm_score
from modeling import FEATURE_KEYS, TransitionScorer, build_pair_vector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend top transition candidates between two sets")
    parser.add_argument("--model-path", required=True, help="Path to transition_scorer.pt")
    parser.add_argument("--features-dir", required=True, help="Directory with segment feature manifests")
    parser.add_argument("--left-set-id", required=True, help="Left set id")
    parser.add_argument("--right-set-id", required=True, help="Right set id")
    parser.add_argument("--top-k", type=int, default=10, help="Number of candidates to return")
    parser.add_argument("--min-segment-index", type=int, default=0, help="Minimum segment index to consider")
    parser.add_argument("--output-path", help="Optional JSON output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    feature_manifests = load_feature_manifests(Path(args.features_dir))

    left_manifest = feature_manifests[args.left_set_id]
    right_manifest = feature_manifests[args.right_set_id]

    checkpoint = torch.load(args.model_path, map_location="cpu")
    input_size = len(build_pair_vector([0.0] * len(FEATURE_KEYS), [0.0] * len(FEATURE_KEYS)))
    model = TransitionScorer(
        input_size=input_size,
        hidden_size=int(checkpoint.get("hidden_size", 64)),
        dropout=float(checkpoint.get("dropout", 0.2)),
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    normalization_mean = torch.tensor(checkpoint["normalization_mean"], dtype=torch.float32)
    normalization_std = torch.tensor(checkpoint["normalization_std"], dtype=torch.float32)

    candidates = build_candidates(
        left_manifest,
        right_manifest,
        model,
        normalization_mean,
        normalization_std,
        min_segment_index=args.min_segment_index,
    )
    ranked = sorted(candidates, key=lambda item: item["probability"], reverse=True)[: args.top_k]

    for candidate in ranked:
        print(json.dumps(candidate))

    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(ranked, indent=2), encoding="utf-8")
        print(f"output_path={output_path}")

    return 0


def build_candidates(
    left_manifest: dict,
    right_manifest: dict,
    model: TransitionScorer,
    normalization_mean: torch.Tensor,
    normalization_std: torch.Tensor,
    min_segment_index: int,
) -> list[dict]:
    left_segments = [segment for segment in left_manifest["segments"] if int(segment["index"]) >= min_segment_index]
    right_segments = [segment for segment in right_manifest["segments"] if int(segment["index"]) >= min_segment_index]

    vectors: list[list[float]] = []
    metadata: list[dict] = []

    for left_segment in left_segments:
        left_values = [float(left_segment["features"].get(key, 0.0)) for key in FEATURE_KEYS]
        for right_segment in right_segments:
            right_values = [float(right_segment["features"].get(key, 0.0)) for key in FEATURE_KEYS]
            vectors.append(build_pair_vector(left_values, right_values))
            metadata.append(
                {
                    "left_set_id": left_manifest["set_id"],
                    "left_segment_index": int(left_segment["index"]),
                    "left_start_seconds": float(left_segment["start_seconds"]),
                    "left_bpm": float(left_segment["features"].get("estimated_bpm", 0.0)),
                    "right_set_id": right_manifest["set_id"],
                    "right_segment_index": int(right_segment["index"]),
                    "right_start_seconds": float(right_segment["start_seconds"]),
                    "right_bpm": float(right_segment["features"].get("estimated_bpm", 0.0)),
                }
            )

    batch = torch.tensor(vectors, dtype=torch.float32)
    batch = (batch - normalization_mean) / normalization_std

    with torch.no_grad():
        logits = model(batch)
        probabilities = torch.sigmoid(logits).squeeze(dim=1).tolist()

    candidates = []
    for item, probability in zip(metadata, probabilities, strict=False):
        candidate = dict(item)
        rhythm_score = combined_transition_rhythm_score(
            candidate["left_start_seconds"],
            candidate["right_start_seconds"],
            candidate["left_bpm"],
            candidate["right_bpm"],
        )
        candidate["model_probability"] = round(float(probability), 6)
        candidate["probability"] = round((0.75 * float(probability)) + (0.25 * rhythm_score), 6)
        candidates.append(candidate)

    return candidates


def load_feature_manifests(features_dir: Path) -> dict[str, dict]:
    if not features_dir.exists():
        raise FileNotFoundError(f"Features directory not found: {features_dir}")

    manifests: dict[str, dict] = {}
    for path in sorted(features_dir.glob("*.features.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifests[payload["set_id"]] = payload
    return manifests


if __name__ == "__main__":
    raise SystemExit(main())

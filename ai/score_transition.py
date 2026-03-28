from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import torch
except ImportError as exception:
    raise SystemExit("PyTorch is required for scoring. Install it before running this script.") from exception

from modeling import FEATURE_KEYS, TransitionScorer, build_pair_vector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a transition pair with the trained model")
    parser.add_argument("--model-path", required=True, help="Path to transition_scorer.pt")
    parser.add_argument("--features-dir", required=True, help="Directory with segment feature manifests")
    parser.add_argument("--left-set-id", required=True, help="Left set id")
    parser.add_argument("--left-segment-index", type=int, required=True, help="Left segment index")
    parser.add_argument("--right-set-id", required=True, help="Right set id")
    parser.add_argument("--right-segment-index", type=int, required=True, help="Right segment index")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    feature_index = load_feature_index(Path(args.features_dir))
    left = feature_index[(args.left_set_id, args.left_segment_index)]
    right = feature_index[(args.right_set_id, args.right_segment_index)]

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
    vector = torch.tensor([build_pair_vector(left, right)], dtype=torch.float32)
    vector = (vector - normalization_mean) / normalization_std
    with torch.no_grad():
        logits = model(vector)
        probability = torch.sigmoid(logits).item()

    print(f"transition_probability={probability:.6f}")
    return 0


def load_feature_index(features_dir: Path) -> dict[tuple[str, int], list[float]]:
    if not features_dir.exists():
        raise FileNotFoundError(f"Features directory not found: {features_dir}")

    feature_index: dict[tuple[str, int], list[float]] = {}
    for path in sorted(features_dir.glob("*.features.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        set_id = payload["set_id"]
        for segment in payload["segments"]:
            feature_index[(set_id, int(segment["index"]))] = [
                float(segment["features"].get(key, 0.0)) for key in FEATURE_KEYS
            ]

    return feature_index


if __name__ == "__main__":
    raise SystemExit(main())

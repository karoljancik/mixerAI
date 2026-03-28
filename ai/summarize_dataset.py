from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize MixerAI manifests, features and training pairs")
    parser.add_argument("--manifests-dir", required=True, help="Directory with set manifests")
    parser.add_argument("--features-dir", required=True, help="Directory with feature manifests")
    parser.add_argument("--pairs-path", required=True, help="Path to pairs.jsonl")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifests_dir = Path(args.manifests_dir)
    features_dir = Path(args.features_dir)
    pairs_path = Path(args.pairs_path)

    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(manifests_dir.glob("*.json"))]
    feature_manifests = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(features_dir.glob("*.features.json"))]
    pairs = [json.loads(line) for line in pairs_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    total_duration = sum(float(manifest.get("duration_seconds", 0.0)) for manifest in manifests)
    total_segments = sum(len(manifest.get("segments", [])) for manifest in manifests)
    total_feature_segments = sum(len(manifest.get("segments", [])) for manifest in feature_manifests)
    positive_pairs = sum(int(pair.get("label", 0)) for pair in pairs)
    negative_pairs = len(pairs) - positive_pairs

    print(f"set_count={len(manifests)}")
    print(f"total_duration_seconds={total_duration:.3f}")
    print(f"total_segments={total_segments}")
    print(f"feature_manifest_count={len(feature_manifests)}")
    print(f"feature_segment_count={total_feature_segments}")
    print(f"pair_count={len(pairs)}")
    print(f"positive_pairs={positive_pairs}")
    print(f"negative_pairs={negative_pairs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

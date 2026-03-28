from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PairRecord:
    left_set_id: str
    left_segment_index: int
    right_set_id: str
    right_segment_index: int
    label: int
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weakly supervised training pairs")
    parser.add_argument("--manifests-dir", required=True, help="Directory with set manifests")
    parser.add_argument("--output-path", required=True, help="Output JSONL path")
    parser.add_argument("--negative-gap-windows", type=int, default=8, help="Minimum gap for same-set negatives")
    parser.add_argument("--cross-set-negative-limit", type=int, default=4, help="Sampled negatives per set segment")
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifests_dir = Path(args.manifests_dir)
    output_path = Path(args.output_path)

    manifests = load_manifests(manifests_dir)
    rng = random.Random(args.seed)
    pairs: list[PairRecord] = []

    for manifest in manifests:
        segments = manifest["segments"]

        for index in range(len(segments) - 1):
            pairs.append(
                PairRecord(
                    left_set_id=manifest["set_id"],
                    left_segment_index=segments[index]["index"],
                    right_set_id=manifest["set_id"],
                    right_segment_index=segments[index + 1]["index"],
                    label=1,
                    reason="adjacent_same_set",
                )
            )

        for index in range(len(segments) - 2):
            pairs.append(
                PairRecord(
                    left_set_id=manifest["set_id"],
                    left_segment_index=segments[index]["index"],
                    right_set_id=manifest["set_id"],
                    right_segment_index=segments[index + 2]["index"],
                    label=1,
                    reason="phrase_neighbor_same_set",
                )
            )

        for index in range(len(segments)):
            nearby_negative_index = index + 3
            if nearby_negative_index < len(segments):
                pairs.append(
                    PairRecord(
                        left_set_id=manifest["set_id"],
                        left_segment_index=segments[index]["index"],
                        right_set_id=manifest["set_id"],
                        right_segment_index=segments[nearby_negative_index]["index"],
                        label=0,
                        reason="hard_nearby_negative_same_set",
                    )
                )

            far_index = index + args.negative_gap_windows
            if far_index < len(segments):
                pairs.append(
                    PairRecord(
                        left_set_id=manifest["set_id"],
                        left_segment_index=segments[index]["index"],
                        right_set_id=manifest["set_id"],
                        right_segment_index=segments[far_index]["index"],
                        label=0,
                        reason="distant_same_set",
                    )
                )

    for left_manifest in manifests:
        other_manifests = [manifest for manifest in manifests if manifest["set_id"] != left_manifest["set_id"] and manifest["segments"]]
        if not other_manifests:
            continue

        sampled_left_segments = sample_segments(left_manifest["segments"], limit=12, rng=rng)
        for left_segment in sampled_left_segments:
            chosen_sets = rng.sample(other_manifests, k=min(args.cross_set_negative_limit, len(other_manifests)))
            for right_manifest in chosen_sets:
                right_segment = rng.choice(right_manifest["segments"])
                pairs.append(
                    PairRecord(
                        left_set_id=left_manifest["set_id"],
                        left_segment_index=left_segment["index"],
                        right_set_id=right_manifest["set_id"],
                        right_segment_index=right_segment["index"],
                        label=0,
                        reason="cross_set_sampled_negative",
                    )
                )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair.__dict__) + "\n")

    print(f"pair_count={len(pairs)}")
    print(f"output={output_path}")
    return 0


def sample_segments(segments: list[dict], limit: int, rng: random.Random) -> list[dict]:
    if len(segments) <= limit:
        return list(segments)
    return rng.sample(segments, k=limit)


def load_manifests(manifests_dir: Path) -> list[dict]:
    if not manifests_dir.exists():
        raise FileNotFoundError(f"Manifest directory not found: {manifests_dir}")

    manifests: list[dict] = []
    for path in sorted(manifests_dir.glob("*.json")):
        manifests.append(json.loads(path.read_text(encoding="utf-8")))
    return manifests


if __name__ == "__main__":
    raise SystemExit(main())

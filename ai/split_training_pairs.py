from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split training pairs into train, validation and test sets")
    parser.add_argument("--pairs-path", required=True, help="Path to pairs.jsonl")
    parser.add_argument("--output-dir", required=True, help="Directory for split JSONL files")
    parser.add_argument("--train-ratio", type=float, default=0.7, help="Train split ratio")
    parser.add_argument("--validation-ratio", type=float, default=0.15, help="Validation split ratio")
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = [json.loads(line) for line in Path(args.pairs_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise RuntimeError("No pairs available to split.")

    if args.train_ratio <= 0 or args.validation_ratio <= 0 or args.train_ratio + args.validation_ratio >= 1:
        raise ValueError("Split ratios must be positive and leave room for a test split.")

    random.Random(args.seed).shuffle(rows)

    total = len(rows)
    train_end = int(total * args.train_ratio)
    validation_end = train_end + int(total * args.validation_ratio)

    splits = {
        "train.jsonl": rows[:train_end],
        "validation.jsonl": rows[train_end:validation_end],
        "test.jsonl": rows[validation_end:],
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for file_name, split_rows in splits.items():
        output_path = output_dir / file_name
        with output_path.open("w", encoding="utf-8") as handle:
            for row in split_rows:
                handle.write(json.dumps(row) + "\n")
        print(f"{file_name}={len(split_rows)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

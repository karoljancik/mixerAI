from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


SPLIT_NAMES = ("train", "validation", "test")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split a clip-level generation dataset into train, validation and test splits."
    )
    parser.add_argument("--dataset-path", required=True, help="Path to generation_dataset JSONL")
    parser.add_argument("--output-dir", required=True, help="Directory for split JSONL files")
    parser.add_argument("--train-ratio", type=float, default=0.7, help="Train split ratio")
    parser.add_argument("--validation-ratio", type=float, default=0.15, help="Validation split ratio")
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.train_ratio <= 0 or args.validation_ratio <= 0 or args.train_ratio + args.validation_ratio >= 1:
        raise ValueError("Split ratios must be positive and leave room for a test split.")

    rows = load_rows(Path(args.dataset_path))
    if not rows:
        raise RuntimeError("No generation rows available to split.")

    grouped_rows = group_rows_by_style_and_set(rows)
    split_rows = {
        "train": [],
        "validation": [],
        "test": [],
    }

    rng = random.Random(args.seed)
    for style, style_groups in grouped_rows.items():
        set_ids = list(style_groups.keys())
        rng.shuffle(set_ids)

        train_set_ids, validation_set_ids, test_set_ids = split_ids(
            set_ids,
            train_ratio=args.train_ratio,
            validation_ratio=args.validation_ratio,
        )

        for set_id in train_set_ids:
            split_rows["train"].extend(style_groups[set_id])
        for set_id in validation_set_ids:
            split_rows["validation"].extend(style_groups[set_id])
        for set_id in test_set_ids:
            split_rows["test"].extend(style_groups[set_id])

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for split_name in SPLIT_NAMES:
        output_path = output_dir / f"{split_name}.jsonl"
        write_rows(output_path, split_rows[split_name])
        print(f"{split_name}_rows={len(split_rows[split_name])}")
        print(f"{split_name}_sets={count_distinct_sets(split_rows[split_name])}")
        print(f"{split_name}_styles={json.dumps(count_by_style(split_rows[split_name]), sort_keys=True)}")

    return 0


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def group_rows_by_style_and_set(rows: list[dict]) -> dict[str, dict[str, list[dict]]]:
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        style = str(row["style"]).strip().lower()
        set_id = str(row["set_id"]).strip()
        grouped[style][set_id].append(row)
    return grouped


def split_ids(set_ids: list[str], train_ratio: float, validation_ratio: float) -> tuple[list[str], list[str], list[str]]:
    total = len(set_ids)
    if total < 3:
        raise RuntimeError(
            f"Need at least 3 distinct sets per style for train/validation/test splitting. Got {total}."
        )

    train_count = max(1, int(total * train_ratio))
    validation_count = max(1, int(total * validation_ratio))
    test_count = total - train_count - validation_count

    if test_count <= 0:
        test_count = 1
        if train_count >= validation_count and train_count > 1:
            train_count -= 1
        elif validation_count > 1:
            validation_count -= 1
        else:
            raise RuntimeError("Unable to allocate a non-empty test split.")

    train_end = train_count
    validation_end = train_end + validation_count
    return (
        set_ids[:train_end],
        set_ids[train_end:validation_end],
        set_ids[validation_end:],
    )


def write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def count_distinct_sets(rows: list[dict]) -> int:
    return len({str(row["set_id"]) for row in rows})


def count_by_style(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row["style"]).strip().lower()] += 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())

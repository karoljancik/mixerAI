from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from generation_dataset import GenerationClipDataset, collate_generation_batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sanity-check the clip dataset loader for generation training."
    )
    parser.add_argument("--split-path", required=True, help="Path to train/validation/test JSONL split")
    parser.add_argument("--clips-root", required=True, help="Root directory with exported clips")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size for inspection")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional fixed waveform length")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    dataset = GenerationClipDataset(
        split_path=Path(args.split_path),
        clips_root=Path(args.clips_root),
        max_samples=args.max_samples,
    )
    dataloader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_generation_batch,
    )

    batch = next(iter(dataloader))
    summary = {
        "dataset_rows": len(dataset),
        "batch_audio_shape": list(batch["audio"].shape),
        "batch_lengths": batch["lengths"].tolist(),
        "batch_labels": batch["labels"].tolist(),
        "batch_styles": batch["styles"],
        "batch_set_ids": batch["set_ids"],
        "sample_rate": batch["sample_rate"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

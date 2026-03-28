from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

from audio_style_modeling import build_audio_style_model
from generation_dataset import GenerationClipDataset, collate_generation_batch
from style_modeling import INDEX_TO_STYLE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a raw-audio liquid-vs-deep baseline model.")
    parser.add_argument("--split-path", required=True, help="Path to evaluation split JSONL")
    parser.add_argument("--clips-root", required=True, help="Root directory with exported WAV clips")
    parser.add_argument("--model-path", required=True, help="Path to trained checkpoint")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--max-samples", type=int, default=0, help="Override clip length from checkpoint")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(Path(args.model_path), map_location="cpu")

    model = load_model_from_checkpoint(checkpoint).to(device)
    expected_sample_rate = int(checkpoint.get("sample_rate", 32000))
    max_samples = int(args.max_samples) if args.max_samples > 0 else int(checkpoint.get("max_samples", 0))

    dataset = GenerationClipDataset(
        split_path=Path(args.split_path),
        clips_root=Path(args.clips_root),
        expected_sample_rate=expected_sample_rate,
        max_samples=max_samples,
    )
    dataloader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_generation_batch,
    )

    loss_fn = nn.CrossEntropyLoss()
    metrics = evaluate(model, dataloader, loss_fn, device)
    metrics["model_type"] = str(checkpoint.get("model_type", "cnn"))
    metrics["class_weighting"] = checkpoint.get("class_weighting")
    if "class_weights" in checkpoint:
        metrics["class_weights"] = checkpoint.get("class_weights")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def load_model_from_checkpoint(checkpoint: dict) -> nn.Module:
    model_type = str(checkpoint.get("model_type", "cnn"))
    base_channels = int(checkpoint.get("base_channels", 24))
    dropout = float(checkpoint.get("dropout", 0.2))
    model = build_audio_style_model(model_type=model_type, base_channels=base_channels, dropout=dropout)
    model.load_state_dict(checkpoint["model_state_dict"])
    return model


def evaluate(
    model: nn.Module,
    dataloader: DataLoader,
    loss_fn: nn.Module,
    device: torch.device,
) -> dict:
    model.eval()
    total_loss = 0.0
    total_examples = 0
    correct = 0
    confusion = [[0, 0], [0, 0]]

    with torch.no_grad():
        for batch in dataloader:
            audio = batch["audio"].to(device)
            labels = batch["labels"].to(device)
            logits = model(audio)
            loss = loss_fn(logits, labels)
            predictions = torch.argmax(logits, dim=1)

            batch_size = int(labels.numel())
            total_loss += float(loss.item()) * batch_size
            total_examples += batch_size
            correct += int((predictions == labels).sum().item())

            for target, predicted in zip(labels.tolist(), predictions.tolist(), strict=False):
                confusion[int(target)][int(predicted)] += 1

    accuracy = correct / total_examples if total_examples > 0 else 0.0
    average_loss = total_loss / max(1, total_examples)
    per_class_accuracy = {}
    for class_index, class_name in sorted(INDEX_TO_STYLE.items()):
        row = confusion[class_index]
        row_total = sum(row)
        per_class_accuracy[class_name] = (row[class_index] / row_total) if row_total > 0 else 0.0

    return {
        "rows": total_examples,
        "loss": round(average_loss, 6),
        "accuracy": round(accuracy, 6),
        "per_class_accuracy": {key: round(value, 6) for key, value in per_class_accuracy.items()},
        "confusion_matrix": {
            "labels": [INDEX_TO_STYLE[0], INDEX_TO_STYLE[1]],
            "matrix": confusion,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())

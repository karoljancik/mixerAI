from __future__ import annotations

import argparse
from collections import Counter
import random
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

from audio_style_modeling import MODEL_TYPES, build_audio_style_model
from generation_dataset import GenerationClipDataset, collate_generation_batch
from style_modeling import INDEX_TO_STYLE, STYLE_TO_INDEX


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a raw-audio liquid-vs-deep baseline model.")
    parser.add_argument("--train-split-path", required=True, help="Path to train.jsonl")
    parser.add_argument("--validation-split-path", required=True, help="Path to validation.jsonl")
    parser.add_argument("--clips-root", required=True, help="Root directory with exported WAV clips")
    parser.add_argument("--epochs", type=int, default=8, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=0.0005, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=0.0001, help="AdamW weight decay")
    parser.add_argument(
        "--class-weighting",
        choices=("auto", "none"),
        default="auto",
        help="Apply inverse-frequency class weights on the training split",
    )
    parser.add_argument("--model-type", choices=sorted(MODEL_TYPES), default="resnet_attn", help="Model architecture")
    parser.add_argument("--base-channels", type=int, default=24, help="Base channel count")
    parser.add_argument("--dropout", type=float, default=0.2, help="Dropout rate")
    parser.add_argument("--max-samples", type=int, default=262144, help="Fixed waveform length per clip")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--model-output", default="data/training/audio_style_baseline.pt", help="Output checkpoint path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_dataset = GenerationClipDataset(
        split_path=Path(args.train_split_path),
        clips_root=Path(args.clips_root),
        max_samples=args.max_samples,
    )
    validation_dataset = GenerationClipDataset(
        split_path=Path(args.validation_split_path),
        clips_root=Path(args.clips_root),
        max_samples=args.max_samples,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_generation_batch,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_generation_batch,
    )

    model = build_audio_style_model(
        model_type=args.model_type,
        base_channels=args.base_channels,
        dropout=args.dropout,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    class_weights = build_class_weights(train_dataset, device, mode=args.class_weighting)
    loss_fn = nn.CrossEntropyLoss(weight=class_weights)
    print(f"class_weighting={args.class_weighting}")
    print(f"class_weights={format_class_weights(class_weights)}")

    best_accuracy = 0.0
    best_checkpoint = None

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        total_examples = 0

        for batch in train_loader:
            audio = batch["audio"].to(device)
            labels = batch["labels"].to(device)

            optimizer.zero_grad()
            logits = model(audio)
            loss = loss_fn(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            batch_size = int(labels.numel())
            total_loss += float(loss.item()) * batch_size
            total_examples += batch_size

        validation_loss, validation_accuracy = evaluate(model, validation_loader, loss_fn, device)
        average_train_loss = total_loss / max(1, total_examples)
        print(
            f"epoch={epoch + 1} "
            f"train_loss={average_train_loss:.6f} "
            f"val_loss={validation_loss:.6f} "
            f"val_accuracy={validation_accuracy:.6f}"
        )

        if validation_accuracy >= best_accuracy:
            best_accuracy = validation_accuracy
            best_checkpoint = {
                "model_state_dict": model.state_dict(),
                "model_type": args.model_type,
                "base_channels": args.base_channels,
                "dropout": args.dropout,
                "max_samples": args.max_samples,
                "sample_rate": train_dataset.expected_sample_rate,
                "class_weighting": args.class_weighting,
                "class_weights": class_weights.detach().cpu().tolist(),
                "validation_accuracy": best_accuracy,
            }

    model_output = Path(args.model_output)
    model_output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_checkpoint or {}, model_output)
    print(f"model_output={model_output}")
    return 0


def evaluate(
    model: nn.Module,
    dataloader: DataLoader,
    loss_fn: nn.Module,
    device: torch.device,
) -> tuple[float, float]:
    model.eval()
    total_loss = 0.0
    total_examples = 0
    correct = 0

    with torch.no_grad():
        for batch in dataloader:
            audio = batch["audio"].to(device)
            labels = batch["labels"].to(device)
            logits = model(audio)
            loss = loss_fn(logits, labels)

            batch_size = int(labels.numel())
            total_loss += float(loss.item()) * batch_size
            total_examples += batch_size
            correct += int((torch.argmax(logits, dim=1) == labels).sum().item())

    average_loss = total_loss / max(1, total_examples)
    accuracy = correct / total_examples if total_examples > 0 else 0.0
    return average_loss, accuracy


def build_class_weights(dataset: GenerationClipDataset, device: torch.device, mode: str) -> torch.Tensor:
    if mode == "none":
        return torch.ones(2, dtype=torch.float32, device=device)

    counts = Counter(STYLE_TO_INDEX[str(row["style"]).strip().lower()] for row in dataset.rows)
    total = sum(counts.values())
    if total == 0:
        return torch.ones(2, dtype=torch.float32, device=device)

    weights = []
    class_count = len(INDEX_TO_STYLE)
    for index in sorted(INDEX_TO_STYLE):
        count = counts.get(index, 0)
        weight = float(total) / max(1.0, float(class_count * count))
        weights.append(weight)
    return torch.tensor(weights, dtype=torch.float32, device=device)


def format_class_weights(class_weights: torch.Tensor) -> dict[str, float]:
    values = class_weights.detach().cpu().tolist()
    return {
        INDEX_TO_STYLE[index]: round(float(values[index]), 6)
        for index in sorted(INDEX_TO_STYLE)
    }


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


if __name__ == "__main__":
    raise SystemExit(main())

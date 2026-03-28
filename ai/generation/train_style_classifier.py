from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from style_modeling import INDEX_TO_STYLE, STYLE_TO_INDEX, STYLE_FEATURE_KEYS, StyleClassifier, build_style_vector


class StyleDataset(Dataset):
    def __init__(self, dataset_path: Path) -> None:
        self.rows = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        row = self.rows[index]
        vector = torch.tensor(build_style_vector(row["features"]), dtype=torch.float32)
        label = torch.tensor(STYLE_TO_INDEX[row["style"]], dtype=torch.long)
        return vector, label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a liquid-vs-deep style classifier")
    parser.add_argument("--dataset-path", required=True, help="Path to style_dataset.jsonl")
    parser.add_argument("--epochs", type=int, default=60, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=8, help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--hidden-size", type=int, default=48, help="Hidden layer size")
    parser.add_argument("--dropout", type=float, default=0.2, help="Dropout rate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--model-output", default="data/training/style_classifier.pt", help="Output checkpoint path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_seed(args.seed)

    dataset = StyleDataset(Path(args.dataset_path))
    if len(dataset) < 4:
        raise RuntimeError("Style dataset is too small. Label more liquid/deep sets first.")

    train_rows, validation_rows = split_rows(dataset.rows, seed=args.seed)
    train_path = write_temp_split(train_rows, "style-train")
    validation_path = write_temp_split(validation_rows, "style-validation")

    try:
        train_dataset = StyleDataset(train_path)
        validation_dataset = StyleDataset(validation_path)
        train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
        validation_loader = DataLoader(validation_dataset, batch_size=args.batch_size, shuffle=False)

        input_size = len(build_style_vector([0.0] * len(STYLE_FEATURE_KEYS)))
        model = StyleClassifier(input_size=input_size, hidden_size=args.hidden_size, dropout=args.dropout)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.0001)
        loss_fn = nn.CrossEntropyLoss()

        best_accuracy = 0.0
        best_checkpoint = None
        centroids = compute_style_centroids(dataset.rows)

        for epoch in range(args.epochs):
            model.train()
            total_loss = 0.0
            for vectors, labels in train_loader:
                optimizer.zero_grad()
                logits = model(vectors)
                loss = loss_fn(logits, labels)
                loss.backward()
                optimizer.step()
                total_loss += float(loss.item())

            validation_accuracy = evaluate(model, validation_loader)
            average_loss = total_loss / max(1, len(train_loader))
            print(f"epoch={epoch + 1} train_loss={average_loss:.6f} val_accuracy={validation_accuracy:.6f}")

            if validation_accuracy >= best_accuracy:
                best_accuracy = validation_accuracy
                best_checkpoint = {
                    "model_state_dict": model.state_dict(),
                    "hidden_size": args.hidden_size,
                    "dropout": args.dropout,
                    "style_feature_keys": STYLE_FEATURE_KEYS,
                    "style_to_index": STYLE_TO_INDEX,
                    "index_to_style": INDEX_TO_STYLE,
                    "style_centroids": centroids,
                    "validation_accuracy": best_accuracy,
                }

        model_output = Path(args.model_output)
        model_output.parent.mkdir(parents=True, exist_ok=True)
        torch.save(best_checkpoint or {}, model_output)
        print(f"model_output={model_output}")
        return 0
    finally:
        train_path.unlink(missing_ok=True)
        validation_path.unlink(missing_ok=True)


def split_rows(rows: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    validation_size = max(1, len(shuffled) // 5)
    return shuffled[validation_size:], shuffled[:validation_size]


def write_temp_split(rows: list[dict], stem: str) -> Path:
    path = Path(f"{stem}-{random.randint(1000, 9999)}.jsonl")
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


def compute_style_centroids(rows: list[dict]) -> dict[str, list[float]]:
    grouped: dict[str, list[list[float]]] = {}
    for row in rows:
        grouped.setdefault(row["style"], []).append([float(value) for value in row["features"]])

    centroids: dict[str, list[float]] = {}
    for style, vectors in grouped.items():
        length = len(vectors[0])
        centroid = []
        for index in range(length):
            centroid.append(sum(vector[index] for vector in vectors) / len(vectors))
        centroids[style] = [round(value, 6) for value in centroid]
    return centroids


def evaluate(model: nn.Module, dataloader: DataLoader) -> float:
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for vectors, labels in dataloader:
            logits = model(vectors)
            predictions = torch.argmax(logits, dim=1)
            correct += int((predictions == labels).sum().item())
            total += labels.numel()
    return correct / total if total > 0 else 0.0


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


if __name__ == "__main__":
    raise SystemExit(main())

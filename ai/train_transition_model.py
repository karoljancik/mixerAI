from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset
except ImportError as exception:
    raise SystemExit("PyTorch is required for training. Install it before running this script.") from exception

from modeling import FEATURE_KEYS, TransitionScorer, build_pair_vector


class PairDataset(Dataset):
    def __init__(self, pair_path: Path, features_dir: Path) -> None:
        self.rows = [json.loads(line) for line in pair_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.feature_index = load_feature_index(features_dir)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        row = self.rows[index]
        left = self.feature_index[(row["left_set_id"], row["left_segment_index"])]
        right = self.feature_index[(row["right_set_id"], row["right_segment_index"])]
        vector = torch.tensor(build_pair_vector(left, right), dtype=torch.float32)
        label = torch.tensor([float(row["label"])], dtype=torch.float32)
        return vector, label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train an improved transition scorer")
    parser.add_argument("--pairs-path", required=True, help="Path to training pairs JSONL")
    parser.add_argument("--features-dir", required=True, help="Directory with segment feature manifests")
    parser.add_argument("--validation-pairs-path", help="Optional validation pairs JSONL")
    parser.add_argument("--epochs", type=int, default=40, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=0.0005, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=0.0001, help="AdamW weight decay")
    parser.add_argument("--hidden-size", type=int, default=64, help="Hidden layer width")
    parser.add_argument("--dropout", type=float, default=0.2, help="Dropout rate")
    parser.add_argument("--early-stopping-patience", type=int, default=8, help="Epochs to wait for validation improvement")
    parser.add_argument("--min-training-minutes", type=float, default=8.0, help="Minimum wall-clock training time")
    parser.add_argument("--max-epochs", type=int, default=400, help="Hard upper bound for epochs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--model-output", default="data/training/transition_scorer.pt", help="Output model path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_seed(args.seed)

    pair_path = Path(args.pairs_path)
    features_dir = Path(args.features_dir)
    model_output = Path(args.model_output)

    dataset = PairDataset(pair_path, features_dir)
    if len(dataset) == 0:
        raise RuntimeError("Training pairs are empty.")

    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)
    validation_loader = None
    if args.validation_pairs_path:
        validation_dataset = PairDataset(Path(args.validation_pairs_path), features_dir)
        validation_loader = DataLoader(validation_dataset, batch_size=args.batch_size, shuffle=False)

    input_size = len(build_pair_vector([0.0] * len(FEATURE_KEYS), [0.0] * len(FEATURE_KEYS)))
    normalization = compute_normalization_stats(dataset)
    model = TransitionScorer(input_size=input_size, hidden_size=args.hidden_size, dropout=args.dropout)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    loss_fn = nn.BCEWithLogitsLoss()
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=3)
    best_validation_loss = float("inf")
    best_checkpoint = None
    stale_epochs = 0
    training_started_at = time.perf_counter()
    epoch = 0

    while epoch < args.max_epochs:
        epoch_loss = 0.0
        for vectors, labels in dataloader:
            vectors = normalize_batch(vectors, normalization)
            optimizer.zero_grad()
            logits = model(vectors)
            loss = loss_fn(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            epoch_loss += float(loss.item())

        average_loss = epoch_loss / max(1, len(dataloader))
        elapsed_minutes = (time.perf_counter() - training_started_at) / 60.0
        if validation_loader is None:
            print(f"epoch={epoch + 1} train_loss={average_loss:.6f} elapsed_minutes={elapsed_minutes:.2f}")
            if epoch + 1 >= args.epochs and elapsed_minutes >= args.min_training_minutes:
                break
            epoch += 1
            continue

        validation_loss, validation_accuracy = evaluate(model, validation_loader, loss_fn, normalization)
        scheduler.step(validation_loss)
        learning_rate = optimizer.param_groups[0]["lr"]
        print(
            f"epoch={epoch + 1} "
            f"train_loss={average_loss:.6f} "
            f"val_loss={validation_loss:.6f} "
            f"val_accuracy={validation_accuracy:.6f} "
            f"lr={learning_rate:.6f} "
            f"elapsed_minutes={elapsed_minutes:.2f}"
        )

        if validation_loss < best_validation_loss:
            best_validation_loss = validation_loss
            stale_epochs = 0
            best_checkpoint = {
                "model_state_dict": model.state_dict(),
                "feature_keys": FEATURE_KEYS,
                "normalization_mean": normalization["mean"].tolist(),
                "normalization_std": normalization["std"].tolist(),
                "hidden_size": args.hidden_size,
                "dropout": args.dropout,
                "best_validation_loss": best_validation_loss,
            }
        else:
            stale_epochs += 1

        minimum_time_reached = elapsed_minutes >= args.min_training_minutes
        if stale_epochs >= args.early_stopping_patience and epoch + 1 >= args.epochs and minimum_time_reached:
            print(f"early_stopping=triggered epoch={epoch + 1}")
            break

        if epoch + 1 >= args.epochs and minimum_time_reached:
            break

        epoch += 1

    model_output.parent.mkdir(parents=True, exist_ok=True)
    if best_checkpoint is None:
        best_checkpoint = {
            "model_state_dict": model.state_dict(),
            "feature_keys": FEATURE_KEYS,
            "normalization_mean": normalization["mean"].tolist(),
            "normalization_std": normalization["std"].tolist(),
            "hidden_size": args.hidden_size,
            "dropout": args.dropout,
            "best_validation_loss": None,
        }

    best_checkpoint["trained_epochs"] = epoch + 1
    best_checkpoint["elapsed_minutes"] = round((time.perf_counter() - training_started_at) / 60.0, 3)
    torch.save(best_checkpoint, model_output)
    print(f"model_output={model_output}")
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


def compute_normalization_stats(dataset: Dataset) -> dict[str, torch.Tensor]:
    vectors = [dataset[index][0] for index in range(len(dataset))]
    stacked = torch.stack(vectors)
    mean = stacked.mean(dim=0)
    std = stacked.std(dim=0)
    std = torch.where(std < 1e-6, torch.ones_like(std), std)
    return {"mean": mean, "std": std}


def normalize_batch(vectors: torch.Tensor, normalization: dict[str, torch.Tensor]) -> torch.Tensor:
    return (vectors - normalization["mean"]) / normalization["std"]


def evaluate(
    model: nn.Module,
    dataloader: DataLoader,
    loss_fn: nn.Module,
    normalization: dict[str, torch.Tensor],
) -> tuple[float, float]:
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for vectors, labels in dataloader:
            vectors = normalize_batch(vectors, normalization)
            logits = model(vectors)
            loss = loss_fn(logits, labels)
            total_loss += float(loss.item())

            predictions = (torch.sigmoid(logits) >= 0.5).float()
            correct += int((predictions == labels).sum().item())
            total += labels.numel()

    model.train()
    average_loss = total_loss / max(1, len(dataloader))
    accuracy = correct / total if total > 0 else 0.0
    return average_loss, accuracy


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


if __name__ == "__main__":
    raise SystemExit(main())

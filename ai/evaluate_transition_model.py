from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader
except ImportError as exception:
    raise SystemExit("PyTorch is required for evaluation. Install it before running this script.") from exception

from modeling import FEATURE_KEYS, TransitionScorer, build_pair_vector
from train_transition_model import PairDataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a trained transition scorer on a labeled split")
    parser.add_argument("--pairs-path", required=True, help="Path to evaluation pairs JSONL")
    parser.add_argument("--features-dir", required=True, help="Directory with segment feature manifests")
    parser.add_argument("--model-path", required=True, help="Path to trained model checkpoint")
    parser.add_argument("--batch-size", type=int, default=64, help="Evaluation batch size")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = PairDataset(Path(args.pairs_path), Path(args.features_dir))
    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)

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
    loss_fn = nn.BCEWithLogitsLoss()

    total_loss = 0.0
    correct = 0
    total = 0
    true_positive = 0
    false_positive = 0
    false_negative = 0

    with torch.no_grad():
        for vectors, labels in dataloader:
            vectors = (vectors - normalization_mean) / normalization_std
            logits = model(vectors)
            loss = loss_fn(logits, labels)
            total_loss += float(loss.item())

            probabilities = torch.sigmoid(logits)
            predictions = (probabilities >= 0.5).float()
            correct += int((predictions == labels).sum().item())
            total += labels.numel()

            true_positive += int(((predictions == 1.0) & (labels == 1.0)).sum().item())
            false_positive += int(((predictions == 1.0) & (labels == 0.0)).sum().item())
            false_negative += int(((predictions == 0.0) & (labels == 1.0)).sum().item())

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) > 0 else 0.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    average_loss = total_loss / max(1, len(dataloader))
    accuracy = correct / total if total > 0 else 0.0

    print(f"eval_pairs={len(dataset)}")
    print(f"loss={average_loss:.6f}")
    print(f"accuracy={accuracy:.6f}")
    print(f"precision={precision:.6f}")
    print(f"recall={recall:.6f}")
    print(f"f1={f1:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

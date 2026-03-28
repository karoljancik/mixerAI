from __future__ import annotations

import argparse
import random
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from audio_latent_modeling import AudioLatentAutoencoder
from latent_audio_dataset import LatentSequenceDataset, collate_latent_sequence_batch
from latent_sequence_modeling import LatentPhraseGenerator, latent_prediction_loss
from style_modeling import STYLE_TO_INDEX


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a phrase-level latent sequence generator on top of a frozen audio autoencoder.")
    parser.add_argument("--train-split-path", required=True, help="Path to train.jsonl")
    parser.add_argument("--validation-split-path", required=True, help="Path to validation.jsonl")
    parser.add_argument("--clips-root", required=True, help="Root directory with exported WAV clips")
    parser.add_argument("--autoencoder-model-path", required=True, help="Path to trained audio latent autoencoder checkpoint")
    parser.add_argument("--epochs", type=int, default=8, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=0.0004, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=0.0001, help="AdamW weight decay")
    parser.add_argument("--context-phrases", type=int, default=8, help="How many consecutive phrases form one training sequence")
    parser.add_argument("--width", type=int, default=256, help="GRU width")
    parser.add_argument("--depth", type=int, default=2, help="GRU depth")
    parser.add_argument("--dropout", type=float, default=0.1, help="Dropout")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-train-batches", type=int, default=0, help="Optional cap for smoke runs")
    parser.add_argument("--max-validation-batches", type=int, default=0, help="Optional cap for smoke runs")
    parser.add_argument("--model-output", default="data/training/latent_phrase_generator.pt", help="Output checkpoint path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    autoencoder_checkpoint = torch.load(Path(args.autoencoder_model_path), map_location=device)
    autoencoder = AudioLatentAutoencoder(
        phrase_samples=int(autoencoder_checkpoint["phrase_samples"]),
        latent_dim=int(autoencoder_checkpoint["latent_dim"]),
        base_channels=int(autoencoder_checkpoint["base_channels"]),
    ).to(device)
    autoencoder.load_state_dict(autoencoder_checkpoint["model_state_dict"])
    autoencoder.eval()
    for parameter in autoencoder.parameters():
        parameter.requires_grad_(False)

    train_dataset = LatentSequenceDataset(
        split_path=Path(args.train_split_path),
        clips_root=Path(args.clips_root),
        phrase_seconds=float(autoencoder_checkpoint["phrase_seconds"]),
        sample_rate=int(autoencoder_checkpoint["sample_rate"]),
        context_phrases=args.context_phrases,
        seed=args.seed,
    )
    validation_dataset = LatentSequenceDataset(
        split_path=Path(args.validation_split_path),
        clips_root=Path(args.clips_root),
        phrase_seconds=float(autoencoder_checkpoint["phrase_seconds"]),
        sample_rate=int(autoencoder_checkpoint["sample_rate"]),
        context_phrases=args.context_phrases,
        seed=args.seed + 1,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_latent_sequence_batch,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_latent_sequence_batch,
    )

    model = LatentPhraseGenerator(
        latent_dim=int(autoencoder_checkpoint["latent_dim"]),
        style_count=len(STYLE_TO_INDEX),
        width=args.width,
        depth=args.depth,
        dropout=args.dropout,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)

    best_validation_loss = float("inf")
    best_checkpoint = None

    for epoch in range(args.epochs):
        train_metrics = run_epoch(
            model=model,
            autoencoder=autoencoder,
            dataloader=train_loader,
            optimizer=optimizer,
            device=device,
            max_batches=args.max_train_batches,
            train=True,
        )
        validation_metrics = run_epoch(
            model=model,
            autoencoder=autoencoder,
            dataloader=validation_loader,
            optimizer=optimizer,
            device=device,
            max_batches=args.max_validation_batches,
            train=False,
        )
        print(
            f"epoch={epoch + 1} "
            f"train_loss={train_metrics['loss']:.6f} "
            f"val_loss={validation_metrics['loss']:.6f} "
            f"val_mse={validation_metrics['mse']:.6f} "
            f"val_cosine={validation_metrics['cosine']:.6f}"
        )

        if validation_metrics["loss"] <= best_validation_loss:
            best_validation_loss = validation_metrics["loss"]
            best_checkpoint = {
                "model_state_dict": model.state_dict(),
                "latent_dim": int(autoencoder_checkpoint["latent_dim"]),
                "phrase_seconds": float(autoencoder_checkpoint["phrase_seconds"]),
                "sample_rate": int(autoencoder_checkpoint["sample_rate"]),
                "phrase_samples": int(autoencoder_checkpoint["phrase_samples"]),
                "context_phrases": args.context_phrases,
                "width": args.width,
                "depth": args.depth,
                "dropout": args.dropout,
                "validation_loss": best_validation_loss,
                "latent_mean": train_metrics["latent_mean"],
                "latent_std": train_metrics["latent_std"],
            }

    output_path = Path(args.model_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_checkpoint or {}, output_path)
    print(f"model_output={output_path}")
    return 0


def run_epoch(
    model: LatentPhraseGenerator,
    autoencoder: AudioLatentAutoencoder,
    dataloader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    max_batches: int,
    train: bool,
) -> dict[str, object]:
    if train:
        model.train()
    else:
        model.eval()

    totals = {
        "loss": 0.0,
        "mse": 0.0,
        "cosine": 0.0,
        "examples": 0,
    }
    latent_sum = None
    latent_sq_sum = None
    latent_count = 0

    for batch_index, batch in enumerate(dataloader):
        if max_batches > 0 and batch_index >= max_batches:
            break

        phrases = batch["phrases"].to(device)
        style_indices = batch["style_indices"].to(device)
        batch_size, phrase_count, phrase_samples = phrases.shape
        flat_phrases = phrases.view(batch_size * phrase_count, phrase_samples)

        with torch.no_grad():
            encoded = autoencoder.encode(flat_phrases).view(batch_size, phrase_count, -1).detach()

        if latent_sum is None:
            latent_sum = encoded.sum(dim=(0, 1))
            latent_sq_sum = encoded.square().sum(dim=(0, 1))
        else:
            latent_sum = latent_sum + encoded.sum(dim=(0, 1))
            latent_sq_sum = latent_sq_sum + encoded.square().sum(dim=(0, 1))
        latent_count += batch_size * phrase_count

        if train:
            optimizer.zero_grad()

        with torch.set_grad_enabled(train):
            predicted = model(encoded, style_indices)
            loss, metrics = latent_prediction_loss(predicted, encoded)
            if train:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

        totals["loss"] += float(loss.item()) * batch_size
        totals["mse"] += metrics["mse"] * batch_size
        totals["cosine"] += metrics["cosine"] * batch_size
        totals["examples"] += batch_size

    example_count = max(1, totals["examples"])
    latent_mean, latent_std = compute_latent_stats(latent_sum, latent_sq_sum, latent_count)
    return {
        "loss": totals["loss"] / example_count,
        "mse": totals["mse"] / example_count,
        "cosine": totals["cosine"] / example_count,
        "latent_mean": latent_mean.tolist(),
        "latent_std": latent_std.tolist(),
    }


def compute_latent_stats(
    latent_sum: torch.Tensor | None,
    latent_sq_sum: torch.Tensor | None,
    latent_count: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    if latent_sum is None or latent_sq_sum is None or latent_count <= 0:
        return torch.zeros(1), torch.ones(1)

    mean = latent_sum / latent_count
    variance = torch.clamp((latent_sq_sum / latent_count) - mean.square(), min=1e-6)
    return mean.detach().cpu(), torch.sqrt(variance).detach().cpu()


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import random
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from audio_latent_modeling import AudioLatentAutoencoder, autoencoder_loss
from latent_audio_dataset import LatentPhraseDataset, collate_latent_phrase_batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a waveform autoencoder for phrase-level latent audio representation.")
    parser.add_argument("--train-split-path", required=True, help="Path to train.jsonl")
    parser.add_argument("--validation-split-path", required=True, help="Path to validation.jsonl")
    parser.add_argument("--clips-root", required=True, help="Root directory with exported WAV clips")
    parser.add_argument("--epochs", type=int, default=8, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=0.0003, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=0.0001, help="AdamW weight decay")
    parser.add_argument("--phrase-seconds", type=float, default=2.75, help="Phrase duration in seconds")
    parser.add_argument("--sample-rate", type=int, default=32000, help="Expected clip sample rate")
    parser.add_argument("--latent-dim", type=int, default=128, help="Latent vector size")
    parser.add_argument("--base-channels", type=int, default=32, help="Base channel count")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-train-batches", type=int, default=0, help="Optional cap for smoke runs")
    parser.add_argument("--max-validation-batches", type=int, default=0, help="Optional cap for smoke runs")
    parser.add_argument("--model-output", default="data/training/audio_latent_autoencoder.pt", help="Output checkpoint path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_dataset = LatentPhraseDataset(
        split_path=Path(args.train_split_path),
        clips_root=Path(args.clips_root),
        phrase_seconds=args.phrase_seconds,
        sample_rate=args.sample_rate,
        seed=args.seed,
    )
    validation_dataset = LatentPhraseDataset(
        split_path=Path(args.validation_split_path),
        clips_root=Path(args.clips_root),
        phrase_seconds=args.phrase_seconds,
        sample_rate=args.sample_rate,
        seed=args.seed + 1,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_latent_phrase_batch,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_latent_phrase_batch,
    )

    model = AudioLatentAutoencoder(
        phrase_samples=train_dataset.phrase_samples,
        latent_dim=args.latent_dim,
        base_channels=args.base_channels,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)

    best_validation_loss = float("inf")
    best_checkpoint = None

    for epoch in range(args.epochs):
        train_metrics = run_epoch(
            model,
            train_loader,
            optimizer,
            device,
            max_batches=args.max_train_batches,
            train=True,
        )
        validation_metrics = run_epoch(
            model,
            validation_loader,
            optimizer,
            device,
            max_batches=args.max_validation_batches,
            train=False,
        )
        print(
            f"epoch={epoch + 1} "
            f"train_loss={train_metrics['loss']:.6f} "
            f"val_loss={validation_metrics['loss']:.6f} "
            f"val_waveform_l1={validation_metrics['waveform_l1']:.6f} "
            f"val_spectral={validation_metrics['spectral']:.6f}"
        )

        if validation_metrics["loss"] <= best_validation_loss:
            best_validation_loss = validation_metrics["loss"]
            best_checkpoint = {
                "model_state_dict": model.state_dict(),
                "phrase_seconds": args.phrase_seconds,
                "sample_rate": args.sample_rate,
                "phrase_samples": train_dataset.phrase_samples,
                "latent_dim": args.latent_dim,
                "base_channels": args.base_channels,
                "validation_loss": best_validation_loss,
            }

    output_path = Path(args.model_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_checkpoint or {}, output_path)
    print(f"model_output={output_path}")
    return 0


def run_epoch(
    model: AudioLatentAutoencoder,
    dataloader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    max_batches: int,
    train: bool,
) -> dict[str, float]:
    if train:
        model.train()
    else:
        model.eval()

    totals = {
        "loss": 0.0,
        "waveform_l1": 0.0,
        "spectral": 0.0,
        "latent_penalty": 0.0,
        "examples": 0,
    }

    for batch_index, batch in enumerate(dataloader):
        if max_batches > 0 and batch_index >= max_batches:
            break

        audio = batch["audio"].to(device)
        if train:
            optimizer.zero_grad()

        with torch.set_grad_enabled(train):
            reconstructed, latents = model(audio)
            loss, metrics = autoencoder_loss(reconstructed, audio, latents)
            if train:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

        batch_size = int(audio.size(0))
        totals["loss"] += float(loss.item()) * batch_size
        totals["waveform_l1"] += metrics["waveform_l1"] * batch_size
        totals["spectral"] += metrics["spectral"] * batch_size
        totals["latent_penalty"] += metrics["latent_penalty"] * batch_size
        totals["examples"] += batch_size

    example_count = max(1, totals["examples"])
    return {
        "loss": totals["loss"] / example_count,
        "waveform_l1": totals["waveform_l1"] / example_count,
        "spectral": totals["spectral"] / example_count,
        "latent_penalty": totals["latent_penalty"] / example_count,
    }


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


if __name__ == "__main__":
    raise SystemExit(main())

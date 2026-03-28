from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

try:
    from phrase_generator_dataset import PhraseTokenDataset, collate_phrase_token_batch
    from phrase_token_codec import BOS_TOKEN_ID, VOCAB_SIZE
    from phrase_token_modeling import PhraseTokenGenerator
    from style_modeling import STYLE_TO_INDEX
except ModuleNotFoundError:
    from generation.phrase_generator_dataset import PhraseTokenDataset, collate_phrase_token_batch
    from generation.phrase_token_codec import BOS_TOKEN_ID, VOCAB_SIZE
    from generation.phrase_token_modeling import PhraseTokenGenerator
    from generation.style_modeling import STYLE_TO_INDEX


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a phrase-level token generator from exported DnB clips.")
    parser.add_argument("--train-split-path", required=True, help="Path to generation train split JSONL")
    parser.add_argument("--validation-split-path", required=True, help="Path to generation validation split JSONL")
    parser.add_argument("--clips-root", required=True, help="Root directory with exported WAV clips")
    parser.add_argument("--epochs", type=int, default=12, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=8, help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=0.0003, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=0.0001, help="AdamW weight decay")
    parser.add_argument("--phrase-seconds", type=float, default=2.75, help="Phrase duration in seconds")
    parser.add_argument("--sample-rate", type=int, default=32000, help="Expected clip sample rate")
    parser.add_argument("--chunk-size", type=int, default=128, help="PCM samples per token")
    parser.add_argument("--width", type=int, default=256, help="Transformer width")
    parser.add_argument("--depth", type=int, default=6, help="Transformer depth")
    parser.add_argument("--num-heads", type=int, default=8, help="Attention heads")
    parser.add_argument("--dropout", type=float, default=0.1, help="Dropout")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--model-output", default="data/training/phrase_token_generator.pt", help="Output checkpoint path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_dataset = PhraseTokenDataset(
        split_path=Path(args.train_split_path),
        clips_root=Path(args.clips_root),
        phrase_seconds=args.phrase_seconds,
        sample_rate=args.sample_rate,
        chunk_size=args.chunk_size,
        seed=args.seed,
    )
    validation_dataset = PhraseTokenDataset(
        split_path=Path(args.validation_split_path),
        clips_root=Path(args.clips_root),
        phrase_seconds=args.phrase_seconds,
        sample_rate=args.sample_rate,
        chunk_size=args.chunk_size,
        seed=args.seed + 1,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_phrase_token_batch,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_phrase_token_batch,
    )

    model = PhraseTokenGenerator(
        vocab_size=VOCAB_SIZE,
        style_count=len(STYLE_TO_INDEX),
        sequence_length=train_dataset.sequence_length - 1,
        width=args.width,
        depth=args.depth,
        num_heads=args.num_heads,
        dropout=args.dropout,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    loss_fn = nn.CrossEntropyLoss()

    best_validation_loss = float("inf")
    best_checkpoint: dict | None = None

    for epoch in range(args.epochs):
        train_loss = run_epoch(model, train_loader, optimizer, loss_fn, device, train=True)
        validation_loss = run_epoch(model, validation_loader, optimizer, loss_fn, device, train=False)
        print(f"epoch={epoch + 1} train_loss={train_loss:.6f} val_loss={validation_loss:.6f}")

        if validation_loss <= best_validation_loss:
            best_validation_loss = validation_loss
            best_checkpoint = {
                "model_state_dict": model.state_dict(),
                "phrase_seconds": args.phrase_seconds,
                "sample_rate": args.sample_rate,
                "chunk_size": args.chunk_size,
                "width": args.width,
                "depth": args.depth,
                "num_heads": args.num_heads,
                "dropout": args.dropout,
                "vocab_size": VOCAB_SIZE,
                "bos_token_id": BOS_TOKEN_ID,
                "sequence_length": train_dataset.sequence_length - 1,
                "validation_loss": best_validation_loss,
            }

    output_path = Path(args.model_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_checkpoint or {}, output_path)
    print(f"model_output={output_path}")
    return 0


def run_epoch(
    model: PhraseTokenGenerator,
    dataloader: DataLoader,
    optimizer: torch.optim.Optimizer,
    loss_fn: nn.Module,
    device: torch.device,
    train: bool,
) -> float:
    if train:
        model.train()
    else:
        model.eval()

    total_loss = 0.0
    total_examples = 0

    for batch in dataloader:
        tokens = batch["tokens"].to(device)
        style_indices = batch["style_indices"].to(device)
        inputs = tokens[:, :-1]
        targets = tokens[:, 1:]

        if train:
            optimizer.zero_grad()

        with torch.set_grad_enabled(train):
            logits = model(inputs, style_indices)
            loss = loss_fn(logits.reshape(-1, logits.size(-1)), targets.reshape(-1))
            if train:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

        batch_size = int(tokens.size(0))
        total_loss += float(loss.item()) * batch_size
        total_examples += batch_size

    return total_loss / max(1, total_examples)


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

try:
    from generation_dataset import read_wave_mono, resolve_clip_path
    from phrase_token_codec import BOS_TOKEN_ID, chunk_waveform, mu_law_encode
    from style_modeling import STYLE_TO_INDEX
except ModuleNotFoundError:
    from generation.generation_dataset import read_wave_mono, resolve_clip_path
    from generation.phrase_token_codec import BOS_TOKEN_ID, chunk_waveform, mu_law_encode
    from generation.style_modeling import STYLE_TO_INDEX


class PhraseTokenDataset(Dataset):
    def __init__(
        self,
        split_path: Path,
        clips_root: Path,
        phrase_seconds: float = 2.75,
        sample_rate: int = 32000,
        chunk_size: int = 128,
        seed: int = 42,
    ) -> None:
        self.rows = [json.loads(line) for line in split_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not self.rows:
            raise RuntimeError(f"No rows found in split: {split_path}")

        self.clips_root = clips_root
        self.phrase_seconds = max(0.5, float(phrase_seconds))
        self.sample_rate = int(sample_rate)
        self.chunk_size = int(chunk_size)
        self.rng = random.Random(seed)
        self.phrase_samples = int(round(self.sample_rate * self.phrase_seconds))
        self.sequence_length = max(8, math.ceil(self.phrase_samples / self.chunk_size)) + 1

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        style = str(row["style"]).strip().lower()
        if style not in STYLE_TO_INDEX:
            raise RuntimeError(f"Unsupported style label: {style}")

        clip_path = resolve_clip_path(row, self.clips_root)
        waveform, sample_rate = read_wave_mono(clip_path)
        if sample_rate != self.sample_rate:
            raise RuntimeError(f"Unexpected sample rate for {clip_path}: {sample_rate}, expected {self.sample_rate}")

        phrase = extract_phrase(waveform, self.phrase_samples, self.rng)
        pooled = chunk_waveform(phrase, self.chunk_size)
        audio_tokens = mu_law_encode(pooled)
        tokens = torch.cat([torch.tensor([BOS_TOKEN_ID], dtype=torch.long), audio_tokens], dim=0)
        if int(tokens.numel()) != self.sequence_length:
            raise RuntimeError(
                f"Unexpected token length for {clip_path}: {tokens.numel()}, expected {self.sequence_length}"
            )

        return {
            "tokens": tokens,
            "style": style,
            "style_index": torch.tensor(STYLE_TO_INDEX[style], dtype=torch.long),
            "set_id": str(row["set_id"]),
            "segment_index": int(row["segment_index"]),
            "path": str(clip_path),
        }


def extract_phrase(waveform: torch.Tensor, phrase_samples: int, rng: random.Random) -> torch.Tensor:
    phrase_samples = max(1, int(phrase_samples))
    if int(waveform.numel()) <= phrase_samples:
        padded = torch.zeros(phrase_samples, dtype=waveform.dtype)
        padded[: int(waveform.numel())] = waveform[:phrase_samples]
        return padded

    max_offset = int(waveform.numel()) - phrase_samples
    start = rng.randint(0, max_offset)
    return waveform[start : start + phrase_samples]


def collate_phrase_token_batch(batch: list[dict[str, Any]]) -> dict[str, Any]:
    if not batch:
        raise RuntimeError("Cannot collate empty phrase batch.")

    tokens = torch.stack([item["tokens"] for item in batch])
    style_indices = torch.stack([item["style_index"] for item in batch])
    return {
        "tokens": tokens,
        "style_indices": style_indices,
        "styles": [item["style"] for item in batch],
        "set_ids": [item["set_id"] for item in batch],
        "segment_indices": [item["segment_index"] for item in batch],
        "paths": [item["path"] for item in batch],
    }

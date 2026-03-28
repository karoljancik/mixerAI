from __future__ import annotations

import json
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
    from style_modeling import STYLE_TO_INDEX
except ModuleNotFoundError:
    from generation.generation_dataset import read_wave_mono, resolve_clip_path
    from generation.style_modeling import STYLE_TO_INDEX


class LatentPhraseDataset(Dataset):
    def __init__(
        self,
        split_path: Path,
        clips_root: Path,
        phrase_seconds: float = 2.75,
        sample_rate: int = 32000,
        seed: int = 42,
    ) -> None:
        self.rows = [json.loads(line) for line in split_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not self.rows:
            raise RuntimeError(f"No rows found in split: {split_path}")

        self.clips_root = clips_root
        self.sample_rate = int(sample_rate)
        self.phrase_seconds = max(0.5, float(phrase_seconds))
        self.phrase_samples = int(round(self.sample_rate * self.phrase_seconds))
        self.seed = int(seed)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        clip_path = resolve_clip_path(row, self.clips_root)
        waveform, sample_rate = read_wave_mono(clip_path)
        if sample_rate != self.sample_rate:
            raise RuntimeError(f"Unexpected sample rate for {clip_path}: {sample_rate}, expected {self.sample_rate}")

        phrase = extract_random_phrase(
            waveform,
            phrase_samples=self.phrase_samples,
            rng=random.Random(self.seed + index),
        )
        style = str(row["style"]).strip().lower()
        if style not in STYLE_TO_INDEX:
            raise RuntimeError(f"Unsupported style label: {style}")

        return {
            "audio": phrase,
            "style": style,
            "style_index": torch.tensor(STYLE_TO_INDEX[style], dtype=torch.long),
            "set_id": str(row["set_id"]),
            "segment_index": int(row["segment_index"]),
            "path": str(clip_path),
        }


class LatentSequenceDataset(Dataset):
    def __init__(
        self,
        split_path: Path,
        clips_root: Path,
        phrase_seconds: float = 2.75,
        sample_rate: int = 32000,
        context_phrases: int = 8,
        seed: int = 42,
    ) -> None:
        rows = [json.loads(line) for line in split_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            raise RuntimeError(f"No rows found in split: {split_path}")

        self.sample_rate = int(sample_rate)
        self.phrase_seconds = max(0.5, float(phrase_seconds))
        self.phrase_samples = int(round(self.sample_rate * self.phrase_seconds))
        self.context_phrases = max(2, int(context_phrases))
        self.seed = int(seed)
        self.clips_root = clips_root
        self.rows = [
            row for row in rows
            if float(row.get("duration_seconds", 0.0)) >= self.phrase_seconds * self.context_phrases
        ]
        if not self.rows:
            raise RuntimeError(
                f"No rows long enough for {self.context_phrases} phrases of {self.phrase_seconds:.2f}s in split: {split_path}"
            )

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        clip_path = resolve_clip_path(row, self.clips_root)
        waveform, sample_rate = read_wave_mono(clip_path)
        if sample_rate != self.sample_rate:
            raise RuntimeError(f"Unexpected sample rate for {clip_path}: {sample_rate}, expected {self.sample_rate}")

        phrases = extract_consecutive_phrases(
            waveform,
            phrase_samples=self.phrase_samples,
            phrase_count=self.context_phrases,
            rng=random.Random(self.seed + index),
        )
        style = str(row["style"]).strip().lower()
        if style not in STYLE_TO_INDEX:
            raise RuntimeError(f"Unsupported style label: {style}")

        return {
            "phrases": phrases,
            "style": style,
            "style_index": torch.tensor(STYLE_TO_INDEX[style], dtype=torch.long),
            "set_id": str(row["set_id"]),
            "segment_index": int(row["segment_index"]),
            "path": str(clip_path),
        }


def extract_random_phrase(waveform: torch.Tensor, phrase_samples: int, rng: random.Random) -> torch.Tensor:
    phrase_samples = max(1, int(phrase_samples))
    if int(waveform.numel()) <= phrase_samples:
        return trim_or_pad(waveform, phrase_samples)

    start = rng.randint(0, int(waveform.numel()) - phrase_samples)
    return waveform[start : start + phrase_samples]


def extract_consecutive_phrases(
    waveform: torch.Tensor,
    phrase_samples: int,
    phrase_count: int,
    rng: random.Random,
) -> torch.Tensor:
    total_required = int(phrase_samples) * int(phrase_count)
    if int(waveform.numel()) <= total_required:
        padded = trim_or_pad(waveform, total_required)
        return padded.view(phrase_count, phrase_samples)

    max_start = int(waveform.numel()) - total_required
    start = rng.randint(0, max_start)
    cropped = waveform[start : start + total_required]
    return cropped.view(phrase_count, phrase_samples)


def trim_or_pad(waveform: torch.Tensor, target_samples: int) -> torch.Tensor:
    length = int(waveform.numel())
    if length == target_samples:
        return waveform
    if length > target_samples:
        return waveform[:target_samples]

    padded = torch.zeros(target_samples, dtype=waveform.dtype)
    padded[:length] = waveform
    return padded


def collate_latent_phrase_batch(batch: list[dict[str, Any]]) -> dict[str, Any]:
    if not batch:
        raise RuntimeError("Cannot collate empty latent phrase batch.")

    return {
        "audio": torch.stack([item["audio"] for item in batch]),
        "style_indices": torch.stack([item["style_index"] for item in batch]),
        "styles": [item["style"] for item in batch],
        "set_ids": [item["set_id"] for item in batch],
        "segment_indices": [item["segment_index"] for item in batch],
        "paths": [item["path"] for item in batch],
    }


def collate_latent_sequence_batch(batch: list[dict[str, Any]]) -> dict[str, Any]:
    if not batch:
        raise RuntimeError("Cannot collate empty latent sequence batch.")

    return {
        "phrases": torch.stack([item["phrases"] for item in batch]),
        "style_indices": torch.stack([item["style_index"] for item in batch]),
        "styles": [item["style"] for item in batch],
        "set_ids": [item["set_id"] for item in batch],
        "segment_indices": [item["segment_index"] for item in batch],
        "paths": [item["path"] for item in batch],
    }

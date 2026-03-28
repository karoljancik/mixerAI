from __future__ import annotations

import json
import sys
import wave
from array import array
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

try:
    from style_modeling import STYLE_TO_INDEX
except ModuleNotFoundError:
    from generation.style_modeling import STYLE_TO_INDEX


class GenerationClipDataset(Dataset):
    def __init__(
        self,
        split_path: Path,
        clips_root: Path,
        expected_sample_rate: int = 32000,
        max_samples: int = 0,
    ) -> None:
        self.rows = [json.loads(line) for line in split_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.clips_root = clips_root
        self.expected_sample_rate = expected_sample_rate
        self.max_samples = max_samples

        if not self.rows:
            raise RuntimeError(f"No clip rows found in split: {split_path}")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        clip_path = resolve_clip_path(row, self.clips_root)
        waveform, sample_rate = read_wave_mono(clip_path)
        if self.expected_sample_rate > 0 and sample_rate != self.expected_sample_rate:
            raise RuntimeError(
                f"Unexpected sample rate for {clip_path}: got {sample_rate}, expected {self.expected_sample_rate}."
            )

        if self.max_samples > 0:
            waveform = trim_or_pad(waveform, self.max_samples)

        style = str(row["style"]).strip().lower()
        if style not in STYLE_TO_INDEX:
            raise RuntimeError(f"Unsupported style label in clip dataset: {style}")

        return {
            "audio": waveform,
            "label": torch.tensor(STYLE_TO_INDEX[style], dtype=torch.long),
            "style": style,
            "set_id": str(row["set_id"]),
            "segment_index": int(row["segment_index"]),
            "sample_rate": sample_rate,
            "path": str(clip_path),
        }


def resolve_clip_path(row: dict, clips_root: Path) -> Path:
    export_path = str(row.get("export_path", "")).strip()
    if export_path:
        path = Path(export_path)
        if path.exists():
            return path

    style = str(row["style"]).strip().lower()
    relative_name = build_relative_name(row)
    path = clips_root / style / relative_name
    if not path.exists():
        raise FileNotFoundError(f"Exported clip not found for row: {path}")
    return path


def build_relative_name(row: dict) -> str:
    set_id = sanitize_name(str(row["set_id"]))
    segment_index = int(row["segment_index"])
    start_ms = int(round(float(row["start_seconds"]) * 1000.0))
    return f"{set_id}__seg-{segment_index:04d}__start-{start_ms:08d}.wav"


def sanitize_name(value: str) -> str:
    allowed = []
    for character in value:
        if character.isalnum():
            allowed.append(character)
        elif character in {" ", "-", "_"}:
            allowed.append("_")
    collapsed = "".join(allowed).strip("_")
    while "__" in collapsed:
        collapsed = collapsed.replace("__", "_")
    return collapsed or "unknown_set"


def read_wave_mono(path: Path) -> tuple[torch.Tensor, int]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        raw_frames = wav_file.readframes(frame_count)

    if channels != 1:
        raise RuntimeError(f"Expected mono WAV clip, got {channels} channels: {path}")
    if sample_width != 2:
        raise RuntimeError(f"Expected 16-bit PCM WAV clip, got sample width {sample_width}: {path}")

    samples = array("h")
    samples.frombytes(raw_frames)
    waveform = torch.tensor([float(sample) / 32768.0 for sample in samples], dtype=torch.float32)
    return waveform, sample_rate


def trim_or_pad(waveform: torch.Tensor, target_samples: int) -> torch.Tensor:
    length = int(waveform.numel())
    if length == target_samples:
        return waveform
    if length > target_samples:
        return waveform[:target_samples]

    padded = torch.zeros(target_samples, dtype=waveform.dtype)
    padded[:length] = waveform
    return padded


def collate_generation_batch(batch: list[dict[str, Any]]) -> dict[str, Any]:
    if not batch:
        raise RuntimeError("Cannot collate an empty batch.")

    max_samples = max(int(item["audio"].numel()) for item in batch)
    audio = torch.stack([trim_or_pad(item["audio"], max_samples) for item in batch])
    lengths = torch.tensor([int(item["audio"].numel()) for item in batch], dtype=torch.long)
    labels = torch.stack([item["label"] for item in batch])

    return {
        "audio": audio,
        "lengths": lengths,
        "labels": labels,
        "styles": [item["style"] for item in batch],
        "set_ids": [item["set_id"] for item in batch],
        "segment_indices": [item["segment_index"] for item in batch],
        "paths": [item["path"] for item in batch],
        "sample_rate": batch[0]["sample_rate"],
    }

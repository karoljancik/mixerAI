from __future__ import annotations

from typing import Sequence

import torch
from torch import nn


STYLE_FEATURE_KEYS = [
    "rms_mean",
    "rms_std",
    "dynamic_range_mean",
    "onset_density_mean",
    "normalized_bpm_mean",
    "pulse_clarity_mean",
    "bar_pulse_strength_mean",
    "phrase_energy_balance_mean",
    "low_energy_ratio_mean",
    "beat_interval_cv_mean",
]

STYLE_TO_INDEX = {
    "liquid": 0,
    "deep": 1,
}

INDEX_TO_STYLE = {value: key for key, value in STYLE_TO_INDEX.items()}


def build_style_vector(values: Sequence[float]) -> list[float]:
    normalized = [float(value) for value in values]
    squared = [value * value for value in normalized]
    return normalized + squared


class StyleClassifier(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 48, dropout: float = 0.2) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, len(STYLE_TO_INDEX)),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.network(inputs)

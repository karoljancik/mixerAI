from __future__ import annotations

from typing import Sequence

import torch
from torch import nn


FEATURE_KEYS = [
    "rms",
    "peak",
    "zero_crossing_rate",
    "crest_factor",
    "dynamic_range",
    "envelope_mean",
    "envelope_std",
    "onset_density",
    "low_energy_ratio",
    "estimated_bpm",
    "tempo_confidence",
    "energy_slope",
    "normalized_bpm",
    "pulse_clarity",
    "beat_interval_mean",
    "beat_interval_std",
    "beat_interval_cv",
    "bar_pulse_strength",
    "phrase_energy_balance",
    "spectral_flatness",
    "spectral_rolloff",
    "mfcc_mean",
    "chroma_std",
]


def build_pair_vector(left: Sequence[float], right: Sequence[float]) -> list[float]:
    left_values = [float(value) for value in left]
    right_values = [float(value) for value in right]
    absolute_difference = [abs(a - b) for a, b in zip(left_values, right_values, strict=False)]
    signed_difference = [a - b for a, b in zip(left_values, right_values, strict=False)]
    product = [a * b for a, b in zip(left_values, right_values, strict=False)]
    ratio = [a / b if abs(b) > 1e-6 else 0.0 for a, b in zip(left_values, right_values, strict=False)]
    return left_values + right_values + absolute_difference + signed_difference + product + ratio


class ResidualBlock(nn.Module):
    def __init__(self, width: int, dropout: float) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(width, width),
            nn.LayerNorm(width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width, width),
            nn.LayerNorm(width),
        )
        self.activation = nn.GELU()

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.activation(inputs + self.block(inputs))


class TransitionScorer(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 64, dropout: float = 0.2) -> None:
        super().__init__()
        self.input_projection = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.encoder = nn.Sequential(
            ResidualBlock(hidden_size, dropout),
            ResidualBlock(hidden_size, dropout),
            ResidualBlock(hidden_size, dropout),
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, 1),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        hidden = self.input_projection(inputs)
        encoded = self.encoder(hidden)
        return self.head(encoded)

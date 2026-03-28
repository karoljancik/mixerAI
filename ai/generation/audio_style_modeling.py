from __future__ import annotations

import torch
from torch import nn


MODEL_TYPES = {"cnn", "resnet_attn"}


class AudioStyleClassifier(nn.Module):
    def __init__(self, base_channels: int = 24, dropout: float = 0.2) -> None:
        super().__init__()
        self.frontend = nn.Sequential(
            nn.AvgPool1d(kernel_size=8, stride=8),
            ConvBlock(1, base_channels, kernel_size=15, stride=2),
            ConvBlock(base_channels, base_channels * 2, kernel_size=9, stride=2),
            ConvBlock(base_channels * 2, base_channels * 4, kernel_size=7, stride=2),
            ConvBlock(base_channels * 4, base_channels * 4, kernel_size=5, stride=2),
        )
        self.head = nn.Sequential(
            nn.Linear(base_channels * 4, base_channels * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(base_channels * 4, 2),
        )

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        if waveform.dim() != 2:
            raise RuntimeError(f"Expected waveform batch with shape [batch, samples], got {list(waveform.shape)}")

        features = self.frontend(waveform.unsqueeze(1))
        pooled = features.mean(dim=-1)
        return self.head(pooled)


class AudioStyleResNetAttn(nn.Module):
    def __init__(self, base_channels: int = 24, dropout: float = 0.2) -> None:
        super().__init__()
        channels = [base_channels, base_channels * 2, base_channels * 4, base_channels * 6]
        self.stem = nn.Sequential(
            nn.AvgPool1d(kernel_size=8, stride=8),
            nn.Conv1d(1, channels[0], kernel_size=15, stride=2, padding=7),
            nn.BatchNorm1d(channels[0]),
            nn.GELU(),
        )
        self.encoder = nn.Sequential(
            ResidualConvBlock(channels[0], channels[0], kernel_size=9, stride=1, dropout=dropout),
            ResidualConvBlock(channels[0], channels[1], kernel_size=9, stride=2, dropout=dropout),
            ResidualConvBlock(channels[1], channels[1], kernel_size=7, stride=1, dropout=dropout),
            ResidualConvBlock(channels[1], channels[2], kernel_size=7, stride=2, dropout=dropout),
            ResidualConvBlock(channels[2], channels[2], kernel_size=5, stride=1, dropout=dropout),
            ResidualConvBlock(channels[2], channels[3], kernel_size=5, stride=2, dropout=dropout),
        )
        self.attention = nn.Sequential(
            nn.Conv1d(channels[3], channels[3] // 2, kernel_size=1),
            nn.GELU(),
            nn.Conv1d(channels[3] // 2, 1, kernel_size=1),
        )
        self.head = nn.Sequential(
            nn.Linear(channels[3] * 2, channels[3]),
            nn.LayerNorm(channels[3]),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(channels[3], 2),
        )

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        if waveform.dim() != 2:
            raise RuntimeError(f"Expected waveform batch with shape [batch, samples], got {list(waveform.shape)}")

        features = self.encoder(self.stem(waveform.unsqueeze(1)))
        attention_logits = self.attention(features).squeeze(1)
        attention_weights = torch.softmax(attention_logits, dim=-1).unsqueeze(1)
        attended = torch.sum(features * attention_weights, dim=-1)
        pooled = features.mean(dim=-1)
        combined = torch.cat([attended, pooled], dim=1)
        return self.head(combined)


class ConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, stride: int) -> None:
        super().__init__()
        padding = kernel_size // 2
        self.block = nn.Sequential(
            nn.Conv1d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding),
            nn.BatchNorm1d(out_channels),
            nn.GELU(),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.block(inputs)


class ResidualConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, stride: int, dropout: float) -> None:
        super().__init__()
        padding = kernel_size // 2
        self.main = nn.Sequential(
            nn.Conv1d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding),
            nn.BatchNorm1d(out_channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Conv1d(out_channels, out_channels, kernel_size=kernel_size, stride=1, padding=padding),
            nn.BatchNorm1d(out_channels),
        )
        self.skip = nn.Identity()
        if stride != 1 or in_channels != out_channels:
            self.skip = nn.Sequential(
                nn.Conv1d(in_channels, out_channels, kernel_size=1, stride=stride),
                nn.BatchNorm1d(out_channels),
            )
        self.activation = nn.GELU()

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        residual = self.skip(inputs)
        outputs = self.main(inputs)
        return self.activation(outputs + residual)


def build_audio_style_model(model_type: str, base_channels: int = 24, dropout: float = 0.2) -> nn.Module:
    normalized = model_type.strip().lower()
    if normalized == "cnn":
        return AudioStyleClassifier(base_channels=base_channels, dropout=dropout)
    if normalized == "resnet_attn":
        return AudioStyleResNetAttn(base_channels=base_channels, dropout=dropout)
    raise ValueError(f"Unsupported audio style model_type: {model_type}")

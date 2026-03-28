from __future__ import annotations

import math

import torch
import torch.nn.functional as F
from torch import nn


class AudioLatentAutoencoder(nn.Module):
    def __init__(
        self,
        phrase_samples: int,
        latent_dim: int = 128,
        base_channels: int = 32,
    ) -> None:
        super().__init__()
        self.phrase_samples = int(phrase_samples)
        self.latent_dim = int(latent_dim)
        self.base_channels = int(base_channels)

        channels = [base_channels, base_channels * 2, base_channels * 4, base_channels * 8]
        self.encoder = nn.Sequential(
            nn.Conv1d(1, channels[0], kernel_size=7, stride=1, padding=3),
            nn.GELU(),
            DownsampleBlock(channels[0], channels[1], stride=4),
            DownsampleBlock(channels[1], channels[2], stride=4),
            DownsampleBlock(channels[2], channels[3], stride=4),
            DownsampleBlock(channels[3], channels[3], stride=4),
        )
        self.reduced_length = self._infer_reduced_length(self.phrase_samples)
        self.to_latent = nn.Sequential(
            nn.Conv1d(channels[3], channels[3], kernel_size=3, stride=1, padding=1),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(channels[3], self.latent_dim),
        )

        self.from_latent = nn.Sequential(
            nn.Linear(self.latent_dim, channels[3] * self.reduced_length),
            nn.GELU(),
        )
        self.decoder = nn.Sequential(
            UpsampleBlock(channels[3], channels[3], stride=4),
            UpsampleBlock(channels[3], channels[2], stride=4),
            UpsampleBlock(channels[2], channels[1], stride=4),
            UpsampleBlock(channels[1], channels[0], stride=4),
            nn.Conv1d(channels[0], 1, kernel_size=7, stride=1, padding=3),
            nn.Tanh(),
        )

    def encode(self, waveform: torch.Tensor) -> torch.Tensor:
        if waveform.dim() != 2:
            raise RuntimeError(f"Expected waveform batch [batch, samples], got {list(waveform.shape)}")
        hidden = self.encoder(waveform.unsqueeze(1))
        return self.to_latent(hidden)

    def decode(self, latents: torch.Tensor) -> torch.Tensor:
        if latents.dim() != 2:
            raise RuntimeError(f"Expected latent batch [batch, dim], got {list(latents.shape)}")
        hidden = self.from_latent(latents)
        hidden = hidden.view(latents.size(0), self.base_channels * 8, self.reduced_length)
        reconstructed = self.decoder(hidden).squeeze(1)
        return reconstructed[:, : self.phrase_samples]

    def forward(self, waveform: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        latents = self.encode(waveform)
        reconstructed = self.decode(latents)
        return reconstructed, latents

    def _infer_reduced_length(self, phrase_samples: int) -> int:
        with torch.no_grad():
            sample = torch.zeros(1, 1, phrase_samples)
            hidden = self.encoder(sample)
        return int(hidden.size(-1))


class DownsampleBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, stride: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv1d(
                in_channels,
                out_channels,
                kernel_size=(stride * 2) + 1,
                stride=stride,
                padding=stride,
            ),
            nn.BatchNorm1d(out_channels),
            nn.GELU(),
            nn.Conv1d(out_channels, out_channels, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm1d(out_channels),
            nn.GELU(),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.block(inputs)


class UpsampleBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, stride: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.ConvTranspose1d(
                in_channels,
                out_channels,
                kernel_size=(stride * 2),
                stride=stride,
                padding=stride // 2,
            ),
            nn.BatchNorm1d(out_channels),
            nn.GELU(),
            nn.Conv1d(out_channels, out_channels, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm1d(out_channels),
            nn.GELU(),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.block(inputs)


def autoencoder_loss(
    reconstructed: torch.Tensor,
    target: torch.Tensor,
    latents: torch.Tensor,
    spectral_weight: float = 0.35,
    latent_weight: float = 0.0005,
) -> tuple[torch.Tensor, dict[str, float]]:
    waveform_l1 = F.l1_loss(reconstructed, target)
    spectral = multi_resolution_stft_loss(reconstructed, target)
    latent_penalty = latents.square().mean()
    total = waveform_l1 + (spectral_weight * spectral) + (latent_weight * latent_penalty)
    return total, {
        "waveform_l1": float(waveform_l1.item()),
        "spectral": float(spectral.item()),
        "latent_penalty": float(latent_penalty.item()),
    }


def multi_resolution_stft_loss(
    reconstructed: torch.Tensor,
    target: torch.Tensor,
    fft_sizes: tuple[int, ...] = (256, 512, 1024),
) -> torch.Tensor:
    total = reconstructed.new_tensor(0.0)
    for fft_size in fft_sizes:
        hop_length = fft_size // 4
        window = torch.hann_window(fft_size, device=reconstructed.device)
        reconstructed_spec = torch.stft(
            reconstructed,
            n_fft=fft_size,
            hop_length=hop_length,
            win_length=fft_size,
            window=window,
            return_complex=True,
        ).abs()
        target_spec = torch.stft(
            target,
            n_fft=fft_size,
            hop_length=hop_length,
            win_length=fft_size,
            window=window,
            return_complex=True,
        ).abs()
        mag_loss = F.l1_loss(torch.log1p(reconstructed_spec), torch.log1p(target_spec))
        spectral_convergence = torch.linalg.vector_norm(target_spec - reconstructed_spec) / (
            torch.linalg.vector_norm(target_spec) + 1e-6
        )
        total = total + mag_loss + spectral_convergence
    return total / max(1, len(fft_sizes))

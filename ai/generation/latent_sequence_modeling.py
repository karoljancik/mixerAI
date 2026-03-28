from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


class LatentPhraseGenerator(nn.Module):
    def __init__(
        self,
        latent_dim: int,
        style_count: int,
        width: int = 256,
        depth: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.latent_dim = int(latent_dim)
        self.width = int(width)
        self.depth = int(depth)
        self.input_projection = nn.Linear(latent_dim, width)
        self.style_embedding = nn.Embedding(style_count, width)
        self.gru = nn.GRU(
            input_size=width,
            hidden_size=width,
            num_layers=depth,
            dropout=dropout if depth > 1 else 0.0,
            batch_first=True,
        )
        self.output = nn.Sequential(
            nn.LayerNorm(width),
            nn.GELU(),
            nn.Linear(width, latent_dim),
        )
        self.bos_latent = nn.Parameter(torch.zeros(1, latent_dim))
        nn.init.normal_(self.bos_latent, mean=0.0, std=0.02)

    def forward(self, latents: torch.Tensor, style_indices: torch.Tensor) -> torch.Tensor:
        if latents.dim() != 3:
            raise RuntimeError(f"Expected latent batch [batch, time, dim], got {list(latents.shape)}")
        if style_indices.dim() != 1:
            raise RuntimeError(f"Expected style batch [batch], got {list(style_indices.shape)}")

        batch_size = latents.size(0)
        bos = self.bos_latent.unsqueeze(0).expand(batch_size, 1, -1)
        shifted_inputs = torch.cat([bos, latents[:, :-1, :]], dim=1)
        hidden = self.input_projection(shifted_inputs) + self.style_embedding(style_indices).unsqueeze(1)
        outputs, _ = self.gru(hidden)
        return self.output(outputs)

    def step(
        self,
        previous_latent: torch.Tensor,
        style_indices: torch.Tensor,
        hidden_state: torch.Tensor | None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if previous_latent.dim() != 2:
            raise RuntimeError(f"Expected previous latent [batch, dim], got {list(previous_latent.shape)}")

        inputs = self.input_projection(previous_latent).unsqueeze(1) + self.style_embedding(style_indices).unsqueeze(1)
        outputs, hidden_state = self.gru(inputs, hidden_state)
        next_latent = self.output(outputs[:, -1, :])
        return next_latent, hidden_state


def latent_prediction_loss(predicted: torch.Tensor, target: torch.Tensor) -> tuple[torch.Tensor, dict[str, float]]:
    mse = F.mse_loss(predicted, target)
    cosine = 1.0 - F.cosine_similarity(predicted, target, dim=-1).mean()
    total = mse + (0.15 * cosine)
    return total, {
        "mse": float(mse.item()),
        "cosine": float(cosine.item()),
    }


def sample_latent_sequence(
    model: LatentPhraseGenerator,
    style_index: int,
    phrase_count: int,
    temperature: float = 0.35,
    latent_mean: torch.Tensor | None = None,
    latent_std: torch.Tensor | None = None,
) -> torch.Tensor:
    device = model.bos_latent.device
    style_indices = torch.tensor([style_index], dtype=torch.long, device=device)
    hidden_state = None
    previous_latent = model.bos_latent.expand(1, -1)
    generated: list[torch.Tensor] = []

    with torch.inference_mode():
        for _ in range(max(1, int(phrase_count))):
            predicted, hidden_state = model.step(previous_latent, style_indices, hidden_state)
            if latent_std is not None:
                noise_scale = latent_std.to(device=device, dtype=predicted.dtype)
            else:
                noise_scale = torch.ones_like(predicted)
            noise = torch.randn_like(predicted) * float(temperature) * noise_scale
            next_latent = predicted + noise
            if latent_mean is not None and latent_std is not None:
                mean = latent_mean.to(device=device, dtype=predicted.dtype)
                std = latent_std.to(device=device, dtype=predicted.dtype)
                next_latent = torch.clamp(next_latent, mean - (3.0 * std), mean + (3.0 * std))
            generated.append(next_latent.squeeze(0).cpu())
            previous_latent = next_latent

    return torch.stack(generated)

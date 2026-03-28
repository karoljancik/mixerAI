from __future__ import annotations

import math

import torch


MU_LAW_AUDIO_TOKEN_COUNT = 256
BOS_TOKEN_ID = MU_LAW_AUDIO_TOKEN_COUNT
VOCAB_SIZE = MU_LAW_AUDIO_TOKEN_COUNT + 1


def chunk_waveform(waveform: torch.Tensor, chunk_size: int) -> torch.Tensor:
    if waveform.dim() != 1:
        raise RuntimeError(f"Expected mono waveform [samples], got {list(waveform.shape)}")
    if chunk_size <= 0:
        raise RuntimeError("chunk_size must be positive")

    length = int(waveform.numel())
    chunk_count = max(1, math.ceil(length / chunk_size))
    padded = torch.zeros(chunk_count * chunk_size, dtype=waveform.dtype)
    padded[:length] = waveform
    return padded.view(chunk_count, chunk_size).mean(dim=1)


def mu_law_encode(audio: torch.Tensor, quantization_channels: int = MU_LAW_AUDIO_TOKEN_COUNT) -> torch.Tensor:
    if audio.numel() == 0:
        return torch.zeros(0, dtype=torch.long)

    mu = float(quantization_channels - 1)
    clamped = torch.clamp(audio, -1.0, 1.0)
    magnitude = torch.log1p(mu * torch.abs(clamped)) / math.log1p(mu)
    signal = torch.sign(clamped) * magnitude
    encoded = ((signal + 1.0) * 0.5 * mu + 0.5).to(torch.long)
    return torch.clamp(encoded, 0, quantization_channels - 1)


def mu_law_decode(tokens: torch.Tensor, quantization_channels: int = MU_LAW_AUDIO_TOKEN_COUNT) -> torch.Tensor:
    if tokens.numel() == 0:
        return torch.zeros(0, dtype=torch.float32)

    mu = float(quantization_channels - 1)
    signal = (tokens.to(torch.float32) / mu) * 2.0 - 1.0
    magnitude = (1.0 / mu) * (torch.pow(1.0 + mu, torch.abs(signal)) - 1.0)
    return torch.sign(signal) * magnitude


def decode_tokens_to_waveform(
    tokens: torch.Tensor,
    chunk_size: int,
    quantization_channels: int = MU_LAW_AUDIO_TOKEN_COUNT,
) -> torch.Tensor:
    decoded = mu_law_decode(sanitize_audio_tokens(tokens), quantization_channels=quantization_channels)
    return decoded.repeat_interleave(chunk_size)


def sanitize_audio_tokens(tokens: torch.Tensor) -> torch.Tensor:
    if tokens.numel() == 0:
        return torch.zeros(0, dtype=torch.long, device=tokens.device)

    cleaned = tokens.to(torch.long)
    cleaned = torch.where(cleaned == BOS_TOKEN_ID, torch.zeros_like(cleaned), cleaned)
    return torch.clamp(cleaned, 0, MU_LAW_AUDIO_TOKEN_COUNT - 1)

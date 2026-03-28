from __future__ import annotations

import math

import torch
from torch import nn


class CausalSelfAttentionBlock(nn.Module):
    def __init__(self, width: int, num_heads: int, dropout: float) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(width)
        self.attention = nn.MultiheadAttention(
            embed_dim=width,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.norm2 = nn.LayerNorm(width)
        self.mlp = nn.Sequential(
            nn.Linear(width, width * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width * 4, width),
            nn.Dropout(dropout),
        )

    def forward(self, inputs: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        hidden = self.norm1(inputs)
        attended, _ = self.attention(hidden, hidden, hidden, attn_mask=attention_mask, need_weights=False)
        hidden = inputs + attended
        return hidden + self.mlp(self.norm2(hidden))


class PhraseTokenGenerator(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        style_count: int,
        sequence_length: int,
        width: int = 256,
        depth: int = 6,
        num_heads: int = 8,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.vocab_size = int(vocab_size)
        self.sequence_length = int(sequence_length)
        self._causal_mask_cache: dict[tuple[int, str], torch.Tensor] = {}
        self.token_embedding = nn.Embedding(vocab_size, width)
        self.style_embedding = nn.Embedding(style_count, width)
        self.position_embedding = nn.Parameter(torch.zeros(1, sequence_length, width))
        self.dropout = nn.Dropout(dropout)
        self.blocks = nn.ModuleList(
            [CausalSelfAttentionBlock(width=width, num_heads=num_heads, dropout=dropout) for _ in range(depth)]
        )
        self.norm = nn.LayerNorm(width)
        self.head = nn.Linear(width, vocab_size)
        nn.init.normal_(self.position_embedding, mean=0.0, std=0.02)

    def forward(self, tokens: torch.Tensor, style_indices: torch.Tensor) -> torch.Tensor:
        if tokens.dim() != 2:
            raise RuntimeError(f"Expected token batch [batch, time], got {list(tokens.shape)}")
        if style_indices.dim() != 1:
            raise RuntimeError(f"Expected style batch [batch], got {list(style_indices.shape)}")

        batch_size, time_steps = tokens.shape
        if time_steps > self.sequence_length:
            raise RuntimeError(f"Token sequence too long: {time_steps}, max {self.sequence_length}")

        token_hidden = self.token_embedding(tokens)
        style_hidden = self.style_embedding(style_indices).unsqueeze(1)
        hidden = token_hidden + style_hidden + self.position_embedding[:, :time_steps, :]
        hidden = self.dropout(hidden)
        attention_mask = self.get_causal_mask(time_steps, hidden.device)
        for block in self.blocks:
            hidden = block(hidden, attention_mask)
        return self.head(self.norm(hidden))

    def get_causal_mask(self, length: int, device: torch.device) -> torch.Tensor:
        device_key = str(device)
        cache_key = (int(length), device_key)
        if cache_key not in self._causal_mask_cache:
            self._causal_mask_cache[cache_key] = build_causal_mask(length, device)
        return self._causal_mask_cache[cache_key]


def build_causal_mask(length: int, device: torch.device) -> torch.Tensor:
    mask = torch.full((length, length), float("-inf"), device=device)
    return torch.triu(mask, diagonal=1)


def sample_tokens(
    model: PhraseTokenGenerator,
    prompt_tokens: torch.Tensor,
    style_index: int,
    steps: int,
    temperature: float = 1.0,
    top_k: int = 0,
    forbidden_token_ids: list[int] | None = None,
    step_stride: int = 1,
) -> torch.Tensor:
    model.eval()
    if prompt_tokens.dim() != 2:
        raise RuntimeError(f"Expected prompt token batch [batch, time], got {list(prompt_tokens.shape)}")

    batch_size, prompt_length = prompt_tokens.shape
    total_length = prompt_length + max(0, int(steps))
    result = torch.empty((batch_size, total_length), dtype=prompt_tokens.dtype, device=prompt_tokens.device)
    result[:, :prompt_length] = prompt_tokens
    style_indices = torch.tensor([style_index], dtype=torch.long, device=prompt_tokens.device)
    write_index = prompt_length
    step_stride = max(1, int(step_stride))

    with torch.inference_mode():
        while write_index < total_length:
            window_start = max(0, write_index - model.sequence_length)
            window = result[:, window_start:write_index]
            logits = model(window, style_indices)[:, -1, :]
            logits = logits / max(temperature, 1e-4)
            if forbidden_token_ids:
                logits[:, forbidden_token_ids] = float("-inf")
            if top_k > 0:
                values, indices = torch.topk(logits, k=min(top_k, logits.size(-1)), dim=-1)
                filtered = torch.full_like(logits, float("-inf"))
                filtered.scatter_(1, indices, values)
                logits = filtered
            probabilities = torch.softmax(logits, dim=-1)
            next_token = torch.multinomial(probabilities, num_samples=1)
            repeat_count = min(step_stride, total_length - write_index)
            result[:, write_index:write_index + repeat_count] = next_token.expand(-1, repeat_count)
            write_index += repeat_count

    return result

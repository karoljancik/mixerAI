from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import torch

from audio_style_modeling import build_audio_style_model
from generation_dataset import read_wave_mono, trim_or_pad
from style_modeling import INDEX_TO_STYLE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict liquid vs deep style for one audio file.")
    parser.add_argument("--input-path", required=True, help="Path to audio file")
    parser.add_argument("--model-path", required=True, help="Path to trained checkpoint")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional override clip length")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checkpoint = torch.load(Path(args.model_path), map_location="cpu")
    model = load_model_from_checkpoint(checkpoint)
    model.eval()

    sample_rate = int(checkpoint.get("sample_rate", 32000))
    max_samples = int(args.max_samples) if args.max_samples > 0 else int(checkpoint.get("max_samples", 0))

    waveform = load_audio_for_model(Path(args.input_path), sample_rate, max_samples)
    with torch.no_grad():
        logits = model(waveform.unsqueeze(0))
        probabilities = torch.softmax(logits, dim=1).squeeze(0)
        predicted_index = int(torch.argmax(probabilities).item())

    result = {
        "predicted_style": INDEX_TO_STYLE[predicted_index],
        "confidence": round(float(probabilities[predicted_index].item()), 6),
        "probabilities": {
            INDEX_TO_STYLE[index]: round(float(probabilities[index].item()), 6)
            for index in sorted(INDEX_TO_STYLE)
        },
        "model_type": str(checkpoint.get("model_type", "cnn")),
        "sample_rate": sample_rate,
        "max_samples": max_samples,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def load_model_from_checkpoint(checkpoint: dict) -> torch.nn.Module:
    model_type = str(checkpoint.get("model_type", "cnn"))
    base_channels = int(checkpoint.get("base_channels", 24))
    dropout = float(checkpoint.get("dropout", 0.2))
    model = build_audio_style_model(model_type=model_type, base_channels=base_channels, dropout=dropout)
    model.load_state_dict(checkpoint["model_state_dict"])
    return model


def load_audio_for_model(input_path: Path, sample_rate: int, max_samples: int) -> torch.Tensor:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        decode_audio(input_path, temp_path, sample_rate)
        waveform, decoded_rate = read_wave_mono(temp_path)
        if decoded_rate != sample_rate:
            raise RuntimeError(f"Decoded sample rate mismatch: got {decoded_rate}, expected {sample_rate}.")
        if max_samples > 0:
            waveform = trim_or_pad(waveform, max_samples)
        return waveform
    finally:
        temp_path.unlink(missing_ok=True)


def decode_audio(input_path: Path, output_path: Path, sample_rate: int) -> None:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-sample_fmt",
        "s16",
        "-y",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exception:
        raise RuntimeError("ffmpeg is required to run style prediction.") from exception
    except subprocess.CalledProcessError as exception:
        raise RuntimeError(f"ffmpeg failed while decoding {input_path}: {exception.stderr}") from exception


if __name__ == "__main__":
    raise SystemExit(main())

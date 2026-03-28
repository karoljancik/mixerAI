from __future__ import annotations

import argparse
import subprocess
import tempfile
import wave
from pathlib import Path

import torch

from audio_latent_modeling import AudioLatentAutoencoder
from latent_sequence_modeling import LatentPhraseGenerator, sample_latent_sequence
from style_modeling import STYLE_TO_INDEX


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a DnB track from latent audio autoencoder + latent sequence generator checkpoints.")
    parser.add_argument("--autoencoder-model-path", required=True, help="Path to trained audio latent autoencoder checkpoint")
    parser.add_argument("--generator-model-path", required=True, help="Path to trained latent phrase generator checkpoint")
    parser.add_argument("--style", choices=("liquid", "deep"), required=True, help="Target style")
    parser.add_argument("--duration-seconds", type=int, default=96, help="Approximate output duration")
    parser.add_argument("--temperature", type=float, default=0.3, help="Latent sampling noise scale")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output-path", required=True, help="Output WAV or MP3 path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    autoencoder_checkpoint = torch.load(Path(args.autoencoder_model_path), map_location=device)
    generator_checkpoint = torch.load(Path(args.generator_model_path), map_location=device)

    autoencoder = AudioLatentAutoencoder(
        phrase_samples=int(autoencoder_checkpoint["phrase_samples"]),
        latent_dim=int(autoencoder_checkpoint["latent_dim"]),
        base_channels=int(autoencoder_checkpoint["base_channels"]),
    ).to(device)
    autoencoder.load_state_dict(autoencoder_checkpoint["model_state_dict"])
    autoencoder.eval()

    generator = LatentPhraseGenerator(
        latent_dim=int(generator_checkpoint["latent_dim"]),
        style_count=len(STYLE_TO_INDEX),
        width=int(generator_checkpoint["width"]),
        depth=int(generator_checkpoint["depth"]),
        dropout=float(generator_checkpoint["dropout"]),
    ).to(device)
    generator.load_state_dict(generator_checkpoint["model_state_dict"])
    generator.eval()

    phrase_seconds = float(generator_checkpoint["phrase_seconds"])
    phrase_count = max(2, int(round(float(args.duration_seconds) / phrase_seconds)))
    latent_mean = tensor_or_none(generator_checkpoint.get("latent_mean"))
    latent_std = tensor_or_none(generator_checkpoint.get("latent_std"))
    style_index = STYLE_TO_INDEX[args.style]

    latent_sequence = sample_latent_sequence(
        generator,
        style_index=style_index,
        phrase_count=phrase_count,
        temperature=float(args.temperature),
        latent_mean=latent_mean,
        latent_std=latent_std,
    ).to(device)

    with torch.inference_mode():
        decoded = autoencoder.decode(latent_sequence)
    waveform = assemble_track(decoded.cpu(), sample_rate=int(autoencoder_checkpoint["sample_rate"]))

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_output(waveform, sample_rate=int(autoencoder_checkpoint["sample_rate"]), output_path=output_path)
    print(f"style={args.style}")
    print(f"device={device}")
    print(f"phrase_count={phrase_count}")
    print(f"output_path={output_path}")
    return 0


def tensor_or_none(value: object) -> torch.Tensor | None:
    if value is None:
        return None
    return torch.tensor(value, dtype=torch.float32)


def assemble_track(decoded_phrases: torch.Tensor, sample_rate: int) -> torch.Tensor:
    if decoded_phrases.numel() == 0:
        return torch.zeros(sample_rate, dtype=torch.float32)

    crossfade_seconds = 0.24
    crossfade_samples = int(round(sample_rate * crossfade_seconds))
    crossfade_samples = max(0, min(crossfade_samples, decoded_phrases.size(-1) // 8))

    track = decoded_phrases[0]
    for phrase_waveform in decoded_phrases[1:]:
        if crossfade_samples <= 0:
            track = torch.cat([track, phrase_waveform], dim=0)
            continue
        fade_out = torch.linspace(1.0, 0.0, crossfade_samples)
        fade_in = torch.linspace(0.0, 1.0, crossfade_samples)
        overlap = (track[-crossfade_samples:] * fade_out) + (phrase_waveform[:crossfade_samples] * fade_in)
        track = torch.cat([track[:-crossfade_samples], overlap, phrase_waveform[crossfade_samples:]], dim=0)

    peak = float(track.abs().max().item()) if track.numel() > 0 else 1.0
    if peak > 0.98:
        track = track / peak * 0.98
    return track


def write_output(waveform: torch.Tensor, sample_rate: int, output_path: Path) -> None:
    if output_path.suffix.lower() == ".wav":
        write_wav(waveform, sample_rate, output_path)
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        write_wav(waveform, sample_rate, temp_path)
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(temp_path),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-y",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exception:
        raise RuntimeError("ffmpeg is required to export generated latent tracks.") from exception
    finally:
        temp_path.unlink(missing_ok=True)


def write_wav(waveform: torch.Tensor, sample_rate: int, output_path: Path) -> None:
    pcm = torch.clamp(waveform, -1.0, 1.0).mul(32767.0).to(torch.int16).cpu().numpy().tobytes()
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)


if __name__ == "__main__":
    raise SystemExit(main())

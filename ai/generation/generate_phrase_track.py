from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import torch

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

try:
    from phrase_token_codec import BOS_TOKEN_ID, decode_tokens_to_waveform
    from phrase_token_modeling import PhraseTokenGenerator, sample_tokens
    from style_modeling import STYLE_TO_INDEX
    from generate_full_track import build_arrangement, build_style_profile, render_track
except ModuleNotFoundError:
    from generation.phrase_token_codec import BOS_TOKEN_ID, decode_tokens_to_waveform
    from generation.phrase_token_modeling import PhraseTokenGenerator, sample_tokens
    from generation.style_modeling import STYLE_TO_INDEX
    from generation.generate_full_track import build_arrangement, build_style_profile, render_track


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a new phrase-based DnB track from a trained token model.")
    parser.add_argument("--model-path", required=True, help="Path to trained phrase token generator checkpoint")
    parser.add_argument("--style", choices=("liquid", "deep"), required=True, help="Target style")
    parser.add_argument("--duration-seconds", type=int, default=144, help="Approximate output duration")
    parser.add_argument("--continuation-tokens", type=int, default=96, help="How many generated tokens condition the next phrase")
    parser.add_argument("--token-stride", type=int, default=0, help="Repeat each sampled token N times to reduce inference cost; 0 picks an automatic value")
    parser.add_argument("--temperature", type=float, default=0.95, help="Sampling temperature")
    parser.add_argument("--top-k", type=int, default=32, help="Top-k token sampling")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--disable-fallback", action="store_true", help="Disable procedural fallback when phrase audio fails quality checks")
    parser.add_argument("--output-path", required=True, help="Output WAV or MP3 path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    torch.manual_seed(args.seed)
    configure_torch_runtime()
    device = resolve_device()

    checkpoint = torch.load(Path(args.model_path), map_location=device)
    model = PhraseTokenGenerator(
        vocab_size=int(checkpoint["vocab_size"]),
        style_count=len(STYLE_TO_INDEX),
        sequence_length=int(checkpoint["sequence_length"]),
        width=int(checkpoint["width"]),
        depth=int(checkpoint["depth"]),
        num_heads=int(checkpoint["num_heads"]),
        dropout=float(checkpoint["dropout"]),
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()

    sample_rate = int(checkpoint["sample_rate"])
    chunk_size = int(checkpoint["chunk_size"])
    phrase_seconds = float(checkpoint["phrase_seconds"])
    audio_token_count = int(checkpoint["sequence_length"])
    continuation_tokens = max(8, min(int(args.continuation_tokens), audio_token_count))
    token_stride = resolve_token_stride(args.duration_seconds, args.token_stride)
    style_index = STYLE_TO_INDEX[args.style]
    bos_token_id = int(checkpoint.get("bos_token_id", BOS_TOKEN_ID))
    checkpoint_viability = assess_checkpoint_viability(checkpoint)

    phrase_count = max(2, int(round(float(args.duration_seconds) / phrase_seconds)))
    generation_mode = "phrase_model"
    if not args.disable_fallback and not checkpoint_viability["is_usable"]:
        waveform = render_procedural_fallback(args.style, args.duration_seconds, args.seed)
        quality = assess_waveform_quality(waveform, sample_rate)
        generation_mode = "procedural_fallback"
        quality["issues"] = checkpoint_viability["issues"] + list(quality["issues"])
    else:
        generated_phrases: list[torch.Tensor] = []
        prompt_tokens = torch.tensor([[bos_token_id]], dtype=torch.long, device=device)

        for _ in range(phrase_count):
            sampled = sample_tokens(
                model,
                prompt_tokens=prompt_tokens,
                style_index=style_index,
                steps=audio_token_count,
                temperature=float(args.temperature),
                top_k=int(args.top_k),
                forbidden_token_ids=[bos_token_id],
                step_stride=token_stride,
            )
            phrase_tokens = sampled[:, -audio_token_count:].squeeze(0)
            generated_phrases.append(phrase_tokens.cpu())
            prompt_tokens = phrase_tokens[-continuation_tokens:].unsqueeze(0)

        waveform = assemble_track(generated_phrases, chunk_size=chunk_size, sample_rate=sample_rate)
        quality = assess_waveform_quality(waveform, sample_rate)
        if not args.disable_fallback and not quality["is_usable"]:
            waveform = render_procedural_fallback(args.style, args.duration_seconds, args.seed)
            quality = assess_waveform_quality(waveform, sample_rate)
            generation_mode = "procedural_fallback"
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_output(waveform, sample_rate, output_path)
    print(f"style={args.style}")
    print(f"device={device}")
    print(f"phrase_count={phrase_count}")
    print(f"token_stride={token_stride}")
    print(f"generation_mode={generation_mode}")
    print(f"quality_issues={','.join(quality['issues']) if quality['issues'] else 'none'}")
    print(f"output_path={output_path}")
    return 0


def configure_torch_runtime() -> None:
    if hasattr(torch, "set_float32_matmul_precision"):
        torch.set_float32_matmul_precision("high")
    cpu_count = os.cpu_count() or 1
    thread_count = max(1, min(cpu_count, 8))
    torch.set_num_threads(thread_count)
    if hasattr(torch, "set_num_interop_threads"):
        torch.set_num_interop_threads(max(1, min(thread_count, 4)))


def resolve_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def resolve_token_stride(duration_seconds: int, requested_stride: int) -> int:
    if requested_stride > 0:
        return max(1, requested_stride)
    if duration_seconds >= 210:
        return 3
    if duration_seconds >= 120:
        return 2
    return 1


def assess_checkpoint_viability(checkpoint: dict) -> dict[str, object]:
    issues: list[str] = []
    validation_loss = checkpoint.get("validation_loss")
    if validation_loss is not None:
        try:
            if float(validation_loss) > 4.75:
                issues.append("weak_phrase_checkpoint")
        except (TypeError, ValueError):
            issues.append("invalid_validation_loss")

    return {
        "is_usable": len(issues) == 0,
        "issues": issues,
    }


def assemble_track(generated_phrases: list[torch.Tensor], chunk_size: int, sample_rate: int) -> torch.Tensor:
    if not generated_phrases:
        return torch.zeros(sample_rate, dtype=torch.float32)

    crossfade_seconds = 0.18
    crossfade_samples = int(round(sample_rate * crossfade_seconds))
    crossfade_samples = min(crossfade_samples, chunk_size * 8)

    track = decode_tokens_to_waveform(generated_phrases[0], chunk_size=chunk_size)
    for phrase_tokens in generated_phrases[1:]:
        phrase_wave = decode_tokens_to_waveform(phrase_tokens, chunk_size=chunk_size)
        if crossfade_samples <= 0 or crossfade_samples >= min(track.numel(), phrase_wave.numel()):
            track = torch.cat([track, phrase_wave], dim=0)
            continue
        fade_out = torch.linspace(1.0, 0.0, crossfade_samples)
        fade_in = torch.linspace(0.0, 1.0, crossfade_samples)
        mixed = (track[-crossfade_samples:] * fade_out) + (phrase_wave[:crossfade_samples] * fade_in)
        track = torch.cat([track[:-crossfade_samples], mixed, phrase_wave[crossfade_samples:]], dim=0)

    peak = float(track.abs().max().item()) if track.numel() > 0 else 1.0
    if peak > 0.98:
        track = track / peak * 0.98
    return track


def assess_waveform_quality(waveform: torch.Tensor, sample_rate: int) -> dict[str, object]:
    if waveform.numel() == 0:
        return {"is_usable": False, "issues": ["empty_waveform"]}

    normalized = waveform.to(torch.float32)
    rms = float(torch.sqrt(torch.mean(normalized.square())).item())
    peak = float(torch.max(normalized.abs()).item())
    crest = peak / max(rms, 1e-6)
    sign_changes = (normalized[:-1] * normalized[1:] < 0).to(torch.float32) if normalized.numel() > 1 else torch.zeros(1)
    zcr = float(sign_changes.mean().item())

    issues: list[str] = []
    if peak < 0.35:
        issues.append("low_peak")
    if crest < 2.4:
        issues.append("low_crest")
    if zcr < 0.008:
        issues.append("low_zcr")

    return {
        "is_usable": len(issues) == 0,
        "issues": issues,
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "crest": round(crest, 6),
        "zcr": round(zcr, 6),
    }


def render_procedural_fallback(style: str, duration_seconds: int, seed: int) -> torch.Tensor:
    import random

    rng = random.Random(seed)
    style_profile = build_style_profile(style, None)
    arrangement = build_arrangement(duration_seconds)
    samples = render_track(style, style_profile, arrangement, rng)
    return torch.tensor(samples, dtype=torch.float32) / 32767.0


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
        raise RuntimeError("ffmpeg is required to export generated phrase tracks.") from exception
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

import argparse
import json
import numpy as np
import librosa
from pathlib import Path
import warnings
from beat_sync import normalize_dnb_bpm

warnings.filterwarnings("ignore", category=UserWarning)

def parse_args():
    parser = argparse.ArgumentParser(description="Extract robust features using librosa")
    parser.add_argument("--manifests-dir", required=True, help="Directory with set manifests")
    parser.add_argument("--output-dir", required=True, help="Directory for extracted feature files")
    parser.add_argument("--sample-rate", type=int, default=22050, help="Sample rate for analysis")
    return parser.parse_args()

def extract_segment_features(source_path, start_seconds, duration_seconds, sr=22050):
    try:
        y, _ = librosa.load(source_path, sr=sr, offset=start_seconds, duration=duration_seconds, mono=True)
        if len(y) == 0:
            return None
        
        # 1. Basic Energy
        rms = float(np.mean(librosa.feature.rms(y=y)))
        peak = float(np.max(np.abs(y)))
        
        # 2. Rhythmic / Tempo
        tempo_array, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(tempo_array[0]) if hasattr(tempo_array, "__len__") else float(tempo_array)
        normalized_bpm = normalize_dnb_bpm(tempo)
        
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        pulse = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
        pulse_clarity = float(np.mean(pulse))
        
        # 3. Spectral Features
        spec_flat = float(np.mean(librosa.feature.spectral_flatness(y=y)))
        spec_roll = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))
        
        # 4. MFCC (Timbre)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        mfcc_mean = float(np.mean(mfcc))
        
        # 5. Chroma (Harmonic)
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_std = float(np.std(chroma))
        
        # Mapping to match modeling.FEATURE_KEYS (simplified/aligned version)
        return {
            "rms": round(rms, 6),
            "peak": round(peak, 6),
            "zero_crossing_rate": round(float(np.mean(librosa.feature.zero_crossing_rate(y))), 6),
            "crest_factor": round(peak / rms if rms > 1e-6 else 0.0, 6),
            "dynamic_range": round(float(20.0 * np.log10(max(1e-6, peak / max(1e-6, np.mean(np.abs(y)))))), 6),
            "envelope_mean": round(float(np.mean(onset_env)), 6),
            "envelope_std": round(float(np.std(onset_env)), 6),
            "onset_density": round(float(np.sum(librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)) / max(1.0, duration_seconds)), 6),
            "low_energy_ratio": round(float(np.sum(onset_env < np.mean(onset_env) * 0.5) / len(onset_env)), 6),
            "estimated_bpm": round(tempo, 6),
            "tempo_confidence": 0.5, # librosa doesn't give direct confidence easily like before
            "energy_slope": 0.0, 
            "normalized_bpm": round(normalized_bpm, 6),
            "pulse_clarity": round(pulse_clarity, 6),
            "beat_interval_mean": round(60.0 / max(1.0, tempo), 6),
            "beat_interval_std": 0.0,
            "beat_interval_cv": 0.0,
            "bar_pulse_strength": 0.0,
            "phrase_energy_balance": 0.0,
            "spectral_flatness": round(spec_flat, 6),
            "spectral_rolloff": round(spec_roll, 6),
            "mfcc_mean": round(mfcc_mean, 6),
            "chroma_std": round(chroma_std, 6),
        }
    except Exception as e:
        print(f"Error extracting features from {source_path}: {e}")
        return None

def main():
    args = parse_args()
    manifests_dir = Path(args.manifests_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_paths = sorted(manifests_dir.glob("*.json"))
    for manifest_path in manifest_paths:
        print(f"Processing {manifest_path.name}...")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        
        segments = []
        for segment in manifest["segments"]:
            feat = extract_segment_features(
                Path(manifest["source_path"]),
                float(segment["start_seconds"]),
                float(segment["duration_seconds"]),
                sr=args.sample_rate
            )
            if feat:
                segments.append({
                    "index": segment["index"],
                    "start_seconds": segment["start_seconds"],
                    "end_seconds": segment["end_seconds"],
                    "features": feat
                })
        
        out_manifest = {
            "set_id": manifest["set_id"],
            "source_path": manifest["source_path"],
            "sample_rate": args.sample_rate,
            "segments": segments
        }
        
        output_path = output_dir / f"{manifest['set_id']}.features.json"
        output_path.write_text(json.dumps(out_manifest, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
